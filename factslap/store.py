"""Our own passage index and check log in Supabase, through its REST API (PostgREST)."""
from __future__ import annotations

import hashlib

import httpx

from factslap.models import CheckResult, Passage, SourceName, StudyType
from factslap.net import request_json


class SupabaseStore:
    def __init__(self, url: str, service_key: str):
        self.rest = url.rstrip("/") + "/rest/v1"
        self.headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}

    # ---- index as a source ----
    name = SourceName.INDEX

    async def hybrid_search(
        self, client: httpx.AsyncClient, query_text: str, query_embedding: list[float], limit: int = 15,
    ) -> list[Passage]:
        rows = await request_json(client, "POST", f"{self.rest}/rpc/hybrid_search", headers=self.headers, json={
            "query_text": query_text, "query_embedding": query_embedding, "match_count": limit,
        })
        return [_row_to_passage(row) for row in rows or []]

    async def save_passages(
        self, client: httpx.AsyncClient, passages: list[Passage], vectors: dict[str, list[float]],
    ) -> None:
        rows = [{
            "id": p.id, "source": p.source.value, "title": p.title, "body": p.text, "url": p.url, "year": p.year,
            "authors": p.authors, "venue": p.venue, "doi": p.doi, "corpus_id": p.corpus_id,
            "study_type": p.study_type.value, "lang": p.lang, "embedding": vectors.get(p.id),
        } for p in passages if p.source != SourceName.INDEX]
        if rows:
            await request_json(client, "POST", f"{self.rest}/passages", json=rows, headers={
                **self.headers, "Prefer": "resolution=merge-duplicates,return=minimal",
            })

    # ---- semantic cache and log ----

    async def similar_check(self, client: httpx.AsyncClient, claim_embedding: list[float]) -> CheckResult | None:
        rows = await request_json(client, "POST", f"{self.rest}/rpc/similar_check", headers=self.headers,
                                  json={"query_embedding": claim_embedding})
        if rows and rows[0].get("result"):
            return CheckResult.model_validate(rows[0]["result"])
        return None

    async def log_check(
        self, client: httpx.AsyncClient, result: CheckResult, claim_embedding: list[float] | None, ip: str | None,
        salt: str,
    ) -> None:
        await request_json(client, "POST", f"{self.rest}/checks", headers={**self.headers, "Prefer": "return=minimal"}, json={
            "claim": result.claim, "lang": result.lang, "claim_embedding": claim_embedding,
            "verdict": result.verdict.label.value, "confidence": result.verdict.confidence,
            "evidence_ids": [e.passage.id for e in result.evidence],
            "verification_passed": result.verification.passed, "latency_ms": result.latency_ms,
            "cost_usd": result.cost_usd,
            "ip_hash": hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:16] if ip else None,
            "result": result.model_dump(mode="json"),
        })


def _row_to_passage(row: dict) -> Passage:
    return Passage(
        id=row["id"], source=_source(row.get("source")), title=row.get("title") or "", text=row.get("body") or "",
        url=row.get("url"), year=row.get("year"), authors=row.get("authors") or [], venue=row.get("venue"),
        doi=row.get("doi"), corpus_id=row.get("corpus_id"),
        study_type=StudyType(row.get("study_type") or "other"), lang=row.get("lang") or "en",
    )


def _source(value: str | None) -> SourceName:
    try:
        return SourceName(value)
    except ValueError:
        return SourceName.INDEX
