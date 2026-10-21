"""Model-based retrieval helpers: cosine similarity and an LLM reranker (same OpenAI key, cheap model)."""
from __future__ import annotations

import httpx
from pydantic import BaseModel

from factslap.llm.client import LLM, CostMeter, OpenAIEmbedder
from factslap.llm.prompts import RERANK_SYSTEM, rerank_user
from factslap.models import Passage

__all__ = ["OpenAIEmbedder", "LLMReranker", "cosine"]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # inputs are unit length


class RerankOut(BaseModel):
    ranking: list[int]  # passage numbers, most useful first


class LLMReranker:
    """Listwise reranking: the model sees every candidate at once and orders them by how directly they
    test the claim. Plays the role of a cross-encoder without adding another provider."""

    def __init__(self, llm: LLM, model: str):
        self.llm, self.model = llm, model

    async def rerank(
        self, client: httpx.AsyncClient, claim: str, passages: list[Passage], top_k: int, meter: CostMeter,
    ) -> list[tuple[int, float]]:
        if not passages:
            return []
        out = await self.llm.generate(client, RERANK_SYSTEM, rerank_user(claim, passages, top_k), RerankOut, meter,
                                      0.0, self.model)
        seen: list[int] = []
        for number in out.ranking:
            index = number - 1
            if 0 <= index < len(passages) and index not in seen:
                seen.append(index)
        return [(index, 1.0 / (rank + 1)) for rank, index in enumerate(seen[:top_k])]
