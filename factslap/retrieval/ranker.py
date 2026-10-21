"""Turn the raw candidates from every source into the few passages worth reading.

1. Remove duplicates (the same abstract often comes from two sources).
2. Rank three ways: the sources' own order, BM25 against the claim, and embedding similarity.
3. Fuse the rankings with reciprocal rank fusion (RRF) and keep the top candidates.
4. Rerank those with an LLM that reads them all at once, and keep the best k.
Steps 2c and 4 are optional, so the pipeline still runs (BM25 + RRF) without them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from factslap.llm.client import CostMeter, OpenAIEmbedder
from factslap.models import Passage
from factslap.retrieval.fusion import rank_by, rrf
from factslap.retrieval.lexical import bm25_scores
from factslap.retrieval.models_api import LLMReranker, cosine


@dataclass
class RankStats:
    candidates: int = 0
    after_dedupe: int = 0
    used_embeddings: bool = False
    used_reranker: bool = False
    notes: list[str] = field(default_factory=list)
    claim_vector: list[float] | None = None
    vectors: dict[str, list[float]] = field(default_factory=dict)  # passage id -> embedding, saved to the index


def _title_key(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())[:120]


def dedupe(passages: list[Passage]) -> list[Passage]:
    # The same paper often arrives through two catalogues, chunked differently. Keep it from one source only:
    # the one whose copy carries more metadata.
    by_title: dict[str, dict[str, list[Passage]]] = {}
    for p in passages:
        if len(_title_key(p.title)) >= 20:
            by_title.setdefault(_title_key(p.title), {}).setdefault(p.source.value, []).append(p)
    dropped: set[str] = set()
    for sources in by_title.values():
        if len(sources) > 1:
            keep = max(sources, key=lambda s: (max(_richness(p) for p in sources[s]), -min(len(p.text) for p in sources[s])))
            dropped |= {p.id for s, group in sources.items() if s != keep for p in group}
    passages = [p for p in passages if p.id not in dropped]

    best: dict[str, Passage] = {}
    for passage in passages:
        key = passage.dedupe_key
        current = best.get(key)
        # keep the copy with more metadata (year, venue, DOI)
        if current is None or _richness(passage) > _richness(current):
            best[key] = passage
    return list(best.values())


def _richness(p: Passage) -> int:
    return sum(x is not None for x in (p.year, p.venue, p.doi, p.citation_count))


def paper_key(p: Passage) -> str:
    title = _title_key(p.title)
    if len(title) >= 20:
        return f"title:{title}"
    if p.doi:
        return f"doi:{p.doi.lower()}"
    if p.corpus_id is not None:
        return f"s2:{p.corpus_id}"
    return f"id:{p.id}"


def diversify(ordered: list[tuple[Passage, float]], k: int, per_paper: int = 2) -> list[tuple[Passage, float]]:
    """Keep the best k, but no more than `per_paper` passages from the same paper (one long abstract
    split into chunks shouldn't crowd out every other study)."""
    counts: dict[str, int] = {}
    picked = []
    for passage, score in ordered:
        key = paper_key(passage)
        if counts.get(key, 0) < per_paper:
            counts[key] = counts.get(key, 0) + 1
            picked.append((passage, score))
            if len(picked) == k:
                break
    return picked


def source_order(passages: list[Passage]) -> list[str]:
    """Interleave sources so each source's top results come first (round robin)."""
    by_source: dict[str, list[str]] = {}
    for p in passages:
        by_source.setdefault(p.source.value, []).append(p.id)
    order: list[str] = []
    while any(by_source.values()):
        for ids in by_source.values():
            if ids:
                order.append(ids.pop(0))
    return order


async def rank(
    client: httpx.AsyncClient,
    claim: str,
    queries: list[str],
    passages: list[Passage],
    *,
    k: int,
    candidates: int,
    embedder: OpenAIEmbedder | None = None,
    reranker: LLMReranker | None = None,
    claim_vector: list[float] | None = None,
    meter: CostMeter | None = None,
) -> tuple[list[tuple[Passage, float]], RankStats]:
    meter = meter or CostMeter()
    stats = RankStats(candidates=len(passages))
    unique = dedupe(passages)
    stats.after_dedupe = len(unique)
    if not unique:
        return [], stats

    by_id = {p.id: p for p in unique}
    texts = [f"{p.title}. {p.text}" for p in unique]
    bm25 = bm25_scores(" ".join([claim, *queries]), texts)
    # Only passages that share terms with the claim get credit from BM25; the sources' own order is a weak prior.
    rankings = [source_order(unique), rank_by({p.id: s for p, s in zip(unique, bm25) if s > 0})]
    weights = [0.5, 1.0]

    if embedder is not None:
        try:
            if claim_vector is None:
                [claim_vector] = await embedder.embed(client, [claim], meter)
            doc_vecs = await embedder.embed(client, texts, meter)
            rankings.append(rank_by({p.id: cosine(claim_vector, v) for p, v in zip(unique, doc_vecs)}))
            weights.append(1.0)
            stats.used_embeddings = True
            stats.claim_vector = claim_vector
            stats.vectors = {p.id: v for p, v in zip(unique, doc_vecs)}
        except Exception as exc:  # embeddings are an improvement, never a requirement
            stats.notes.append(f"embeddings skipped: {exc}")

    fused = rrf(rankings, weights=weights)
    shortlist = [by_id[i] for i in rank_by(fused)[:candidates]]

    if reranker is not None and len(shortlist) > k:
        try:
            order = await reranker.rerank(client, claim, shortlist, min(len(shortlist), k * 2), meter)
            if order:
                stats.used_reranker = True
                # The reranker's order first; if it left out too much, top up from the fused ranking
                # (the stance step drops anything irrelevant anyway).
                chosen = {i for i, _ in order}
                rest = [(shortlist[i], 0.0) for i in range(len(shortlist)) if i not in chosen]
                return diversify([(shortlist[i], score) for i, score in order] + rest, k), stats
        except Exception as exc:
            stats.notes.append(f"reranker skipped: {exc}")

    return diversify([(p, fused[p.id]) for p in shortlist], k), stats
