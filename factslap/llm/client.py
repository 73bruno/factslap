"""OpenAI calls with structured output, a fallback model and per-request cost tracking."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from factslap.net import request_json

T = TypeVar("T", bound=BaseModel)
CHAT_API = "https://api.openai.com/v1/chat/completions"
EMBEDDINGS_API = "https://api.openai.com/v1/embeddings"

# USD per 1M tokens (input, output), from OpenAI's model pages. Used for the cost meter and the daily cap.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o-mini": (0.15, 0.60),
    "text-embedding-3-small": (0.02, 0.0),
}
DEFAULT_PRICE = (5.00, 30.00)  # unknown model: assume the expensive end, so the spend cap stays safe


@dataclass
class CostMeter:
    """One per request (v1 used a module-level counter shared by every concurrent request)."""

    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    calls: list[str] = field(default_factory=list)

    def add(self, model: str, tokens_in: int, tokens_out: int) -> None:
        price_in, price_out = PRICES.get(model, DEFAULT_PRICE)
        self.input_tokens += tokens_in
        self.output_tokens += tokens_out
        self.usd += (tokens_in * price_in + tokens_out * price_out) / 1_000_000
        self.calls.append(model)


class LLM(Protocol):
    async def generate(
        self, client: httpx.AsyncClient, system: str, user: str, schema: type[T],
        meter: CostMeter, temperature: float = 0.2, model: str | None = None,
    ) -> T: ...


class LLMError(RuntimeError):
    pass


def json_schema_for(schema: type[BaseModel]) -> dict:
    """Pydantic schema with $refs inlined and titles/defaults dropped."""
    raw = schema.model_json_schema()
    defs = raw.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k not in {"title", "default"}}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(raw)


def _parse(text: str, schema: type[T]) -> T:
    try:
        return schema.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMError(f"invalid structured output: {exc}") from exc


class OpenAIChat:
    """Chat Completions with a JSON schema. `model` picks the model for this call; the fallback model
    is tried once if the first call fails (network, quota or output that doesn't match the schema)."""

    def __init__(self, api_key: str, default_model: str, fallback_model: str | None = None):
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set")
        self.api_key, self.default_model, self.fallback_model = api_key, default_model, fallback_model

    async def generate(self, client, system, user, schema, meter, temperature=0.2, model=None):
        models = [model or self.default_model]
        if self.fallback_model and self.fallback_model not in models:
            models.append(self.fallback_model)
        errors = []
        for name in models:
            try:
                return await self._call(client, name, system, user, schema, meter, temperature)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        raise LLMError("; ".join(errors))

    async def _call(self, client, model, system, user, schema, meter, temperature):
        body = {
            "model": model,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "schema": json_schema_for(schema), "strict": False,
            }},
        }
        if model.startswith("gpt-5"):
            body["reasoning_effort"] = "none"  # these steps need speed, not long reasoning
        data = await request_json(client, "POST", CHAT_API, headers={"Authorization": f"Bearer {self.api_key}"}, json=body)
        usage = data.get("usage") or {}
        meter.add(model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        return _parse(data["choices"][0]["message"]["content"], schema)


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dims: int = 768):
        self.api_key, self.model, self.dims = api_key, model, dims

    async def embed(self, client: httpx.AsyncClient, texts: list[str], meter: CostMeter | None = None) -> list[list[float]]:
        if not texts:
            return []
        data = await request_json(
            client, "POST", EMBEDDINGS_API, headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": [t[:8000] for t in texts], "dimensions": self.dims},
        )
        if meter is not None:
            meter.add(self.model, (data.get("usage") or {}).get("total_tokens", 0), 0)
        # OpenAI embeddings come back unit-length, so a dot product is the cosine similarity.
        return [item["embedding"] for item in sorted(data["data"], key=lambda d: d["index"])]


def build_llm(settings) -> OpenAIChat:
    return OpenAIChat(settings.openai_api_key, settings.fast_model, settings.fallback_model)
