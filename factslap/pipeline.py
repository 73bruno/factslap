"""The fact-checking pipeline, end to end. One implementation serves both the streaming and the plain API.

cache → plan → search (all sources in parallel) → rank → evidence → verdict → answer → verify → tone
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import httpx

from factslap import stages
from factslap.config import Settings
from factslap.llm.client import LLM, CostMeter, OpenAIEmbedder, build_llm
from factslap.models import (
    CheckResult,
    Passage,
    SourceName,
    Stance,
    StepEvent,
    Tone,
    VerificationReport,
)
from factslap.net import new_client
from factslap.retrieval.models_api import LLMReranker
from factslap.retrieval.ranker import rank
from factslap.sources import Source, build_sources
from factslap.sources.semantic_scholar import SemanticScholar
from factslap.store import SupabaseStore
from factslap.verify import check_answer, same_facts


class FactSlap:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        llm: LLM | None = None,
        sources: dict[SourceName, Source] | None = None,
        embedder: OpenAIEmbedder | None = None,
        reranker: LLMReranker | None = None,
        store: SupabaseStore | None = None,
    ):
        self.settings = s = settings or Settings()
        self.llm = llm or build_llm(s)
        self.sources = sources if sources is not None else build_sources(s)
        self.embedder = embedder if embedder is not None else (
            OpenAIEmbedder(s.openai_api_key, s.embedding_model, s.embedding_dims) if s.has_embeddings else None)
        self.reranker = reranker if reranker is not None else (
            LLMReranker(self.llm, s.fast_model) if s.llm_rerank else None)
        self.store = store if store is not None else (
            SupabaseStore(s.supabase_url, s.supabase_service_key) if s.has_index else None)

    async def check(self, claim: str, tone: Tone | None = Tone.CASUAL, **kwargs) -> CheckResult:
        result = None
        async for event in self.run(claim, tone, **kwargs):
            if isinstance(event, CheckResult):
                result = event
        assert result is not None
        return result

    async def run(
        self,
        claim: str,
        tone: Tone | None = Tone.CASUAL,
        *,
        ip: str | None = None,
        use_cache: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> AsyncIterator[StepEvent | CheckResult]:
        own_client = client is None
        client = client or new_client(self.settings.source_timeout_s)
        try:
            async for event in self._run(client, claim.strip(), tone, ip, use_cache):
                yield event
        finally:
            if own_client:
                await client.aclose()

    async def _run(self, client, claim, tone, ip, use_cache) -> AsyncIterator[StepEvent | CheckResult]:
        s = self.settings
        started = time.perf_counter()
        meter = CostMeter()
        steps: list[StepEvent] = []

        def step(name: str, message: str, t0: float, **data) -> StepEvent:
            event = StepEvent(step=name, message=message, ms=int((time.perf_counter() - t0) * 1000), data=data)
            steps.append(event)
            return event

        # 0. semantic cache: an almost identical claim checked recently
        claim_vector = None
        if self.embedder is not None:
            t0 = time.perf_counter()
            try:
                [claim_vector] = await self.embedder.embed(client, [claim], meter)
                if use_cache and self.store is not None:
                    cached = await self.store.similar_check(client, claim_vector)
                    if cached is not None:
                        yield step("cache", "Already checked recently", t0, original_claim=cached.claim)
                        cached.steps = steps
                        yield cached
                        return
            except Exception as exc:
                yield step("cache", "Cache unavailable", t0, error=str(exc)[:200])

        # 1. plan
        t0 = time.perf_counter()
        plan = await stages.plan(client, self.llm, claim, meter)
        yield step("plan", "Planned the search", t0, queries=plan.queries, sources=[x.value for x in plan.sources],
                   subclaims=plan.subclaims, lang=plan.lang, claim_type=plan.claim_type.value)

        # 2. search every chosen source (and our own index) in parallel
        t0 = time.perf_counter()
        passages, per_source = await self._search(client, plan.sources, plan.queries, claim, plan.lang, claim_vector)
        yield step("search", f"Found {len(passages)} passages", t0, per_source=per_source)

        # 3. rank: dedupe, BM25 + embeddings fused with RRF, then rerank
        t0 = time.perf_counter()
        ranked, stats = await rank(
            client, claim, plan.queries, passages, k=s.evidence_k, candidates=s.rerank_candidates,
            embedder=self.embedder, reranker=self.reranker, claim_vector=claim_vector, meter=meter,
        )
        s2 = self.sources.get(SourceName.SEMANTIC_SCHOLAR)
        if isinstance(s2, SemanticScholar):
            await s2.enrich(client, [p for p, _ in ranked])
        yield step("rank", f"Kept the {len(ranked)} most relevant", t0,
                   candidates=stats.candidates, unique=stats.after_dedupe, embeddings=stats.used_embeddings,
                   reranker=stats.used_reranker, notes=stats.notes, top=[p.title for p, _ in ranked[:5]])

        # 4. what each passage says about the claim
        t0 = time.perf_counter()
        evidence = await stages.assess(client, self.llm, claim, ranked, meter, s.reader_model) if ranked else []
        counts = {st.value: sum(e.stance == st for e in evidence) for st in Stance if st != Stance.IRRELEVANT}
        yield step("evidence", "Read the evidence", t0, **counts)

        # 5. verdict: a formula over stances and study quality, no tone involved
        t0 = time.perf_counter()
        verdict = stages.decide(evidence)
        yield step("verdict", verdict.label.value, t0, confidence=verdict.confidence, why=verdict.explanation)

        # 6-7. neutral answer, checked; one retry with the failures as feedback
        t0 = time.perf_counter()
        answer = await stages.write_answer(client, self.llm, claim, verdict, evidence, plan.lang, meter, s.answer_model)
        report = check_answer(answer, evidence, claim, verdict.label)
        if not report.passed:
            feedback = "; ".join(c.detail for c in report.checks if not c.passed)
            answer = await stages.write_answer(client, self.llm, claim, verdict, evidence, plan.lang, meter,
                                               s.answer_model, feedback=feedback)
            report = check_answer(answer, evidence, claim, verdict.label)
        yield step("verify", "Checked citations and numbers" if report.passed else "Some checks failed", t0,
                   checks=[c.model_dump() for c in report.checks])

        # 8. tone: reword only; if the rewrite touches citations or numbers, keep the neutral text
        styled = None
        if tone is not None and evidence:
            t0 = time.perf_counter()
            try:
                candidate = await stages.restyle(client, self.llm, answer, tone, verdict, plan.lang, meter,
                                                 s.answer_model)
                if same_facts(answer, candidate):
                    styled = candidate
                yield step("tone", f"Tone: {tone.value}" if styled
                           else "Kept the neutral wording", t0)
            except Exception as exc:
                yield step("tone", "Kept the neutral wording", t0, error=str(exc)[:200])

        result = CheckResult(
            claim=claim, lang=plan.lang, plan=plan, verdict=verdict, evidence=evidence, answer=answer,
            styled_answer=styled, verification=report, steps=steps, cost_usd=round(meter.usd, 5),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        await self._remember(client, result, stats.vectors, ranked, claim_vector, ip)
        yield result

    async def _search(self, client, chosen, queries, claim, lang, claim_vector):
        names = [n for n in chosen if n in self.sources]
        tasks = [self._timed(self.sources[n].search(client, queries, claim, lang, self.settings.per_source_limit))
                 for n in names]
        if self.store is not None and claim_vector is not None:
            names.append(SourceName.INDEX)
            tasks.append(self._timed(self.store.hybrid_search(client, " ".join([claim, *queries]), claim_vector)))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        passages: list[Passage] = []
        per_source: dict[str, int | str] = {}
        for name, result in zip(names, results):
            if isinstance(result, BaseException):
                per_source[name.value] = f"error: {type(result).__name__}"
            else:
                per_source[name.value] = len(result)
                passages.extend(result)
        return passages, per_source

    async def _timed(self, coro):
        return await asyncio.wait_for(coro, timeout=self.settings.source_timeout_s + 3)

    async def _remember(self, client, result, vectors, ranked, claim_vector, ip) -> None:
        if self.store is None:
            return
        try:
            await self.store.save_passages(client, [p for p, _ in ranked], vectors)
            await self.store.log_check(client, result, claim_vector, ip, salt=self.settings.supabase_url or "")
        except Exception:
            pass  # logging must never break an answer


__all__ = ["FactSlap", "VerificationReport"]
