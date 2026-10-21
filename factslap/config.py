"""Settings read from the environment. Optional services switch off when their key is missing."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value or None


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    semantic_scholar_api_key: str | None = field(default_factory=lambda: _env("SEMANTIC_SCHOLAR_API_KEY"))
    google_api_key: str | None = field(default_factory=lambda: _env("GOOGLE_API_KEY"))  # Fact Check Tools
    openalex_api_key: str | None = field(default_factory=lambda: _env("OPENALEX_API_KEY"))
    supabase_url: str | None = field(default_factory=lambda: _env("SUPABASE_URL"))
    supabase_service_key: str | None = field(default_factory=lambda: _env("SUPABASE_SERVICE_KEY"))

    # One provider (OpenAI), a cheap model for simple steps and a stronger one where quality matters.
    fast_model: str = field(default_factory=lambda: _env("FACTSLAP_FAST_MODEL", "gpt-5.6-luna"))        # plan, rerank
    reader_model: str = field(default_factory=lambda: _env("FACTSLAP_READER_MODEL", "gpt-5.6-terra"))   # stance
    answer_model: str = field(default_factory=lambda: _env("FACTSLAP_ANSWER_MODEL", "gpt-5.6-terra"))   # answer, tone
    fallback_model: str = field(default_factory=lambda: _env("FACTSLAP_FALLBACK_MODEL", "gpt-5.4-mini"))
    embedding_model: str = field(default_factory=lambda: _env("FACTSLAP_EMBEDDING_MODEL", "text-embedding-3-small"))
    embedding_dims: int = 768
    llm_rerank: bool = field(default_factory=lambda: _env("FACTSLAP_LLM_RERANK", "1") == "1")

    # Pipeline sizes
    per_source_limit: int = 8
    rerank_candidates: int = 30
    evidence_k: int = 8
    source_timeout_s: float = 12.0

    @property
    def has_llm(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_embeddings(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_index(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)
