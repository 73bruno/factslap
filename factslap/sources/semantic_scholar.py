"""Semantic Scholar: passages from paper bodies (snippet search) plus abstracts (paper search)."""
from __future__ import annotations

import asyncio
import time
import weakref

import httpx

from factslap.models import Passage, SourceName
from factslap.net import SourceError, request_json
from factslap.sources.base import author_names, clean_text, guess_study_type

API = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = "corpusId,title,abstract,tldr,year,authors,venue,url,citationCount,externalIds,publicationTypes"


class SemanticScholar:
    """Keys start at 1 request per second, so calls are spaced out and kept to two per check."""

    name = SourceName.SEMANTIC_SCHOLAR
    min_interval_s = 1.05
    _locks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()  # one lock per event loop
    _last_call = 0.0

    def __init__(self, api_key: str | None = None, use_snippets: bool = True):
        self.headers = {"x-api-key": api_key} if api_key else {}
        self.use_snippets = use_snippets

    async def search(
        self, client: httpx.AsyncClient, queries: list[str], claim: str, lang: str, limit: int
    ) -> list[Passage]:
        # Two calls: body snippets for the plain claim, abstracts for the most technical query.
        calls = [self._snippets(client, queries[0], limit)] if self.use_snippets and queries else []
        calls += [self._papers(client, q, limit) for q in queries[1:2] or queries[:1]]
        results = await asyncio.gather(*calls, return_exceptions=True)
        passages: list[Passage] = []
        errors = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(result)
            else:
                passages.extend(result)
        if not passages and errors:
            raise SourceError(f"Semantic Scholar: {errors[0]}")
        return passages

    async def _get(self, client: httpx.AsyncClient, method: str, url: str, **kwargs):
        loop = asyncio.get_running_loop()
        lock = SemanticScholar._locks.setdefault(loop, asyncio.Lock())
        async with lock:  # one call at a time, at least min_interval_s apart
            wait = SemanticScholar._last_call + self.min_interval_s - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                return await request_json(client, method, url, attempts=2, base_delay=1.1, **kwargs)
            finally:
                SemanticScholar._last_call = time.monotonic()

    async def _papers(self, client: httpx.AsyncClient, query: str, limit: int) -> list[Passage]:
        data = await self._get(
            client, "GET", f"{API}/paper/search",
            params={"query": query, "limit": limit, "fields": PAPER_FIELDS}, headers=self.headers,
        )
        passages = []
        for paper in data.get("data") or []:
            abstract = clean_text(paper.get("abstract"))
            tldr = clean_text((paper.get("tldr") or {}).get("text"))
            text = abstract or tldr
            if not text:
                continue
            ids = paper.get("externalIds") or {}
            passages.append(Passage(
                id=f"s2:{paper.get('corpusId')}:abstract",
                source=self.name,
                title=clean_text(paper.get("title")),
                text=text,
                url=paper.get("url"),
                year=paper.get("year"),
                authors=author_names(paper.get("authors")),
                venue=paper.get("venue") or None,
                doi=ids.get("DOI"),
                corpus_id=_as_int(paper.get("corpusId")),
                study_type=guess_study_type(paper.get("publicationTypes"), paper.get("title") or ""),
                citation_count=paper.get("citationCount"),
            ))
        return passages

    async def _snippets(self, client: httpx.AsyncClient, query: str, limit: int) -> list[Passage]:
        data = await self._get(
            client, "GET", f"{API}/snippet/search",
            params={"query": query, "limit": limit}, headers=self.headers,
        )
        passages = []
        for match in data.get("data") or []:
            snippet = match.get("snippet") or {}
            paper = match.get("paper") or {}
            text = clean_text(snippet.get("text"))
            corpus_id = _as_int(paper.get("corpusId"))
            if not text or corpus_id is None:
                continue
            offset = (snippet.get("snippetOffset") or {}).get("start", 0) if isinstance(snippet.get("snippetOffset"), dict) else 0
            passages.append(Passage(
                id=f"s2:{corpus_id}:{snippet.get('snippetKind', 'body')}:{offset}",
                source=self.name,
                title=clean_text(paper.get("title")),
                text=text,
                url=f"https://www.semanticscholar.org/p/{corpus_id}",
                authors=author_names(paper.get("authors")),
                corpus_id=corpus_id,
                study_type=guess_study_type(None, paper.get("title") or ""),
                source_score=match.get("score"),
            ))
        return passages

    async def enrich(self, client: httpx.AsyncClient, passages: list[Passage]) -> None:
        """Fill year, venue, DOI and study type for snippet passages (one batch call, after reranking)."""
        missing = sorted({p.corpus_id for p in passages if p.corpus_id is not None and p.year is None})
        if not missing:
            return
        try:
            papers = await self._get(
                client, "POST", f"{API}/paper/batch",
                params={"fields": "corpusId,year,venue,externalIds,publicationTypes,citationCount,url"},
                json={"ids": [f"CorpusId:{cid}" for cid in missing]}, headers=self.headers,
            )
        except SourceError:
            return  # enrichment is optional
        by_id = {_as_int(p.get("corpusId")): p for p in papers or [] if p}
        for passage in passages:
            paper = by_id.get(passage.corpus_id)
            if not paper:
                continue
            passage.year = passage.year or paper.get("year")
            passage.venue = passage.venue or paper.get("venue") or None
            passage.doi = passage.doi or (paper.get("externalIds") or {}).get("DOI")
            passage.citation_count = passage.citation_count or paper.get("citationCount")
            passage.study_type = guess_study_type(paper.get("publicationTypes"), passage.title)


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
