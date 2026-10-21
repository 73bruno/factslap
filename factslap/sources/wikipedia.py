"""Wikipedia in the user's language (falls back to English), through the MediaWiki API."""
from __future__ import annotations

import httpx

from factslap.models import Passage, SourceName, StudyType
from factslap.net import request_json
from factslap.sources.base import clean_text, split_passages


class Wikipedia:
    name = SourceName.WIKIPEDIA

    async def search(
        self, client: httpx.AsyncClient, queries: list[str], claim: str, lang: str, limit: int
    ) -> list[Passage]:
        wiki_lang = lang if lang in {"es", "en"} else "en"
        # Search with the claim in its own language; English queries go to English Wikipedia.
        searches = [(wiki_lang, claim)]
        if wiki_lang != "en" and queries:
            searches.append(("en", queries[0]))
        passages: list[Passage] = []
        for code, text in searches:
            passages.extend(await self._search_one(client, code, text, max(2, limit // 2)))
        return passages

    async def _search_one(self, client: httpx.AsyncClient, code: str, query: str, limit: int) -> list[Passage]:
        api = f"https://{code}.wikipedia.org/w/api.php"
        data = await request_json(client, "GET", api, params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": query,
            "gsrlimit": limit, "prop": "extracts|info", "exintro": 1, "explaintext": 1, "inprop": "url",
        })
        pages = ((data or {}).get("query") or {}).get("pages") or {}
        passages = []
        for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
            extract = clean_text(page.get("extract"))
            if len(extract) < 80:
                continue
            for index, chunk in enumerate(split_passages(extract)[:2]):
                passages.append(Passage(
                    id=f"wiki:{code}:{page.get('pageid')}:{index}",
                    source=self.name,
                    title=page.get("title", ""),
                    text=chunk,
                    url=page.get("fullurl"),
                    authors=["Wikipedia contributors"],
                    study_type=StudyType.ENCYCLOPEDIA,
                    lang=code,
                ))
        return passages
