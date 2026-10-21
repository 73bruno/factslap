"""Europe PMC: biomedical literature with study types; abstracts split into passages."""
from __future__ import annotations

import asyncio

import httpx

from factslap.models import Passage, SourceName
from factslap.net import request_json
from factslap.sources.base import clean_text, guess_study_type, split_passages

API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class EuropePMC:
    name = SourceName.EUROPE_PMC

    async def search(
        self, client: httpx.AsyncClient, queries: list[str], claim: str, lang: str, limit: int
    ) -> list[Passage]:
        # One search per query, in parallel: OR-ing them into a single query made results swing wildly
        # when one query changed by a word. HAS_ABSTRACT filters out empty records.
        per_query = max(3, limit // 2 + 1)
        responses = await asyncio.gather(*[
            request_json(client, "GET", API, params={
                "query": f"({query}) AND HAS_ABSTRACT:y", "format": "json", "resultType": "core", "pageSize": per_query,
            }) for query in queries[:4]
        ], return_exceptions=True)
        records, seen = [], set()
        for response in responses:
            if isinstance(response, BaseException):
                continue
            for record in (response.get("resultList") or {}).get("result") or []:
                if record.get("id") not in seen:
                    seen.add(record.get("id"))
                    records.append(record)
        if not records and responses and all(isinstance(r, BaseException) for r in responses):
            raise responses[0]
        passages: list[Passage] = []
        for record in records:
            abstract = clean_text(record.get("abstractText"))
            if not abstract:
                continue
            types = (record.get("pubTypeList") or {}).get("pubType") or []
            if isinstance(types, str):
                types = [types]
            record_id = record.get("pmcid") or record.get("pmid") or record.get("id")
            title = clean_text(record.get("title"))
            year = record.get("pubYear")
            for index, chunk in enumerate(split_passages(abstract)):
                passages.append(Passage(
                    id=f"epmc:{record_id}:{index}",
                    source=self.name,
                    title=title,
                    text=chunk,
                    url=f"https://europepmc.org/article/{record.get('source', 'MED')}/{record.get('id')}",
                    year=int(year) if year and str(year).isdigit() else None,
                    authors=[a.strip() for a in (record.get("authorString") or "").split(",") if a.strip()][:6],
                    venue=((record.get("journalInfo") or {}).get("journal") or {}).get("title"),
                    doi=record.get("doi"),
                    study_type=guess_study_type(types, title),
                    citation_count=record.get("citedByCount"),
                ))
        return passages
