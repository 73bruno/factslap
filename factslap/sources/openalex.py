"""OpenAlex: an open catalogue of 250M+ scholarly works (CC0, no key needed), searched by relevance.

Europe PMC sorts by date, which buries classic trials; OpenAlex ranks by relevance, so it finds them.
Abstracts come as an inverted index (word -> positions) and are rebuilt here.
"""
from __future__ import annotations

import asyncio

import httpx

from factslap.models import Passage, SourceName
from factslap.net import request_json
from factslap.sources.base import clean_text, guess_study_type, split_passages

API = "https://api.openalex.org/works"
FIELDS = "id,doi,title,publication_year,cited_by_count,type,abstract_inverted_index,authorships,primary_location"


def rebuild_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions = [(pos, word) for word, places in inverted.items() for pos in places]
    return " ".join(word for _, word in sorted(positions))


class OpenAlex:
    name = SourceName.OPENALEX

    def __init__(self, api_key: str | None = None):
        # Without a key, OpenAlex shares one small daily budget per IP address, which a server runs out of fast.
        self.key_params = {"api_key": api_key} if api_key else {}

    async def search(
        self, client: httpx.AsyncClient, queries: list[str], claim: str, lang: str, limit: int
    ) -> list[Passage]:
        per_query = max(4, limit // 2 + 2)  # some works have no abstract and get skipped
        responses = await asyncio.gather(*[
            request_json(client, "GET", API, params={"search": q, "per_page": per_query, "select": FIELDS, **self.key_params})
            for q in queries[:4]
        ], return_exceptions=True)
        if responses and all(isinstance(r, BaseException) for r in responses):
            raise responses[0]
        passages: list[Passage] = []
        seen: set[str] = set()
        for response in responses:
            if isinstance(response, BaseException):
                continue
            for work in response.get("results") or []:
                work_id = (work.get("id") or "").rsplit("/", 1)[-1]
                abstract = clean_text(rebuild_abstract(work.get("abstract_inverted_index")))
                if not work_id or work_id in seen or len(abstract.split()) < 30:
                    continue
                seen.add(work_id)
                title = clean_text(work.get("title"))
                doi = (work.get("doi") or "").removeprefix("https://doi.org/") or None
                venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
                authors = [a.get("author", {}).get("display_name") for a in work.get("authorships") or []]
                for index, chunk in enumerate(split_passages(abstract)):
                    passages.append(Passage(
                        id=f"openalex:{work_id}:{index}",
                        source=self.name,
                        title=title,
                        text=chunk,
                        url=f"https://doi.org/{doi}" if doi else work.get("id"),
                        year=work.get("publication_year"),
                        authors=[a for a in authors if a][:6],
                        venue=venue,
                        doi=doi,
                        study_type=guess_study_type([work.get("type") or ""], title),
                        citation_count=work.get("cited_by_count"),
                    ))
        return passages
