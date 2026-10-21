"""Google Fact Check Tools: published fact-checks of similar claims, in the user's language."""
from __future__ import annotations

import httpx

from factslap.models import Passage, SourceName, StudyType
from factslap.net import request_json
from factslap.sources.base import clean_text

API = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


class FactCheck:
    name = SourceName.FACT_CHECK

    def __init__(self, api_key: str | None):
        self.api_key = api_key

    async def search(
        self, client: httpx.AsyncClient, queries: list[str], claim: str, lang: str, limit: int
    ) -> list[Passage]:
        if not self.api_key:
            return []
        data = await request_json(client, "GET", API, params={
            "query": claim, "languageCode": lang, "pageSize": limit, "key": self.api_key,
        })
        passages = []
        for item in data.get("claims") or []:
            for review in item.get("claimReview") or []:  # every review, not just the first
                rating = review.get("textualRating")
                publisher = (review.get("publisher") or {}).get("name") or "Fact-checker"
                if not rating:
                    continue
                text = f'Claim reviewed: "{clean_text(item.get("text"))}". Rating by {publisher}: {rating}.'
                if review.get("title"):
                    text += f" {clean_text(review['title'])}"
                date = review.get("reviewDate") or ""
                passages.append(Passage(
                    id=f"factcheck:{review.get('url')}",
                    source=self.name,
                    title=clean_text(review.get("title")) or f"{publisher} fact-check",
                    text=text,
                    url=review.get("url"),
                    year=int(date[:4]) if date[:4].isdigit() else None,
                    authors=[publisher],
                    study_type=StudyType.FACT_CHECK,
                    lang=review.get("languageCode") or lang,
                ))
        return passages[:limit]
