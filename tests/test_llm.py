import json

import httpx
import pytest
import respx

from factslap.llm.client import CHAT_API, EMBEDDINGS_API, CostMeter, LLMError, OpenAIChat, OpenAIEmbedder, json_schema_for
from factslap.retrieval.models_api import LLMReranker
from factslap.stages import PlanOut, StanceOut
from tests.fakes import FakeLLM, passage

PLAN = '{"lang":"en","english_claim":"x","subclaims":["x"],"queries":["q"],"claim_type":"health","sources":["semantic_scholar"]}'


def chat_reply(content: str, prompt_tokens=1000, completion_tokens=100):
    return {"choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}


def test_schema_has_no_refs_or_titles():
    schema = json_schema_for(StanceOut)
    assert "$ref" not in str(schema) and "title" not in str(schema)
    assert schema["properties"]["items"]["items"]["properties"]["stance"]["enum"] == [
        "supports", "refutes", "neutral", "irrelevant"]


@respx.mock
async def test_chat_sends_schema_skips_reasoning_and_counts_cost():
    route = respx.post(CHAT_API).respond(json=chat_reply(PLAN))
    meter = CostMeter()
    async with httpx.AsyncClient() as client:
        out = await OpenAIChat("key", "gpt-5.6-luna").generate(client, "sys", "user", PlanOut, meter)
    body = json.loads(route.calls[0].request.read())
    assert body["model"] == "gpt-5.6-luna" and body["reasoning_effort"] == "none"
    assert body["response_format"]["json_schema"]["name"] == "PlanOut"
    assert route.calls[0].request.headers["authorization"] == "Bearer key"
    assert out.queries == ["q"]
    assert meter.usd == pytest.approx((1000 * 0.20 + 100 * 1.20) / 1_000_000)


@respx.mock
async def test_invalid_output_falls_back_to_the_second_model():
    respx.post(CHAT_API).mock(side_effect=[
        httpx.Response(200, json=chat_reply('{"lang": 3}')),
        httpx.Response(200, json=chat_reply(PLAN)),
    ])
    meter = CostMeter()
    async with httpx.AsyncClient() as client:
        out = await OpenAIChat("key", "gpt-5.6-terra", "gpt-5.4-mini").generate(client, "s", "u", PlanOut, meter)
    assert out.claim_type.value == "health"
    assert meter.calls == ["gpt-5.6-terra", "gpt-5.4-mini"]


def test_missing_key_is_a_clear_error():
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        OpenAIChat("", "gpt-5.6-luna")


@respx.mock
async def test_embeddings_keep_input_order():
    respx.post(EMBEDDINGS_API).respond(json={"data": [
        {"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}], "usage": {"total_tokens": 8}})
    async with httpx.AsyncClient() as client:
        vectors = await OpenAIEmbedder("key", dims=2).embed(client, ["a", "b"], CostMeter())
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


async def test_llm_reranker_ignores_out_of_range_and_repeated_numbers():
    llm = FakeLLM({"RerankOut": {"ranking": [3, 3, 9, 1]}})
    passages = [passage(i, f"text {i}") for i in range(1, 5)]
    order = await LLMReranker(llm, "gpt-5.6-luna").rerank(None, "claim", passages, 3, CostMeter())
    assert [index for index, _ in order] == [2, 0]
