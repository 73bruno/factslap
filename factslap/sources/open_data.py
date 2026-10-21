"""Structured open data: World Bank documents and Open Food Facts products.

Both are turned into plain factual passages. Nothing here is opinion: v1 injected a hand-written
mocking text for food products as if it were evidence, and that is gone.
"""
from __future__ import annotations

import httpx

from factslap.models import Passage, SourceName, StudyType
from factslap.net import request_json
from factslap.sources.base import clean_text, split_passages


class WorldBank:
    name = SourceName.WORLD_BANK
    API = "https://search.worldbank.org/api/v2/wds"

    async def search(
        self, client: httpx.AsyncClient, queries: list[str], claim: str, lang: str, limit: int
    ) -> list[Passage]:
        query = queries[0] if queries else claim
        data = await request_json(client, "GET", self.API, params={
            "format": "json", "qterm": query, "rows": min(limit, 5),
            "fl": "display_title,abstracts,docdt,url,docty",
        })
        passages = []
        for key, doc in (data.get("documents") or {}).items():
            if not isinstance(doc, dict) or key == "facets":
                continue
            abstract = doc.get("abstracts")
            if isinstance(abstract, dict):
                abstract = abstract.get("cdata!") or ""
            text = clean_text(abstract)
            if not text:
                continue
            date = doc.get("docdt") or ""
            for index, chunk in enumerate(split_passages(text)[:2]):
                passages.append(Passage(
                    id=f"wb:{key}:{index}",
                    source=self.name,
                    title=clean_text(doc.get("display_title")),
                    text=chunk,
                    url=doc.get("url"),
                    year=int(date[:4]) if date[:4].isdigit() else None,
                    authors=["World Bank"],
                    study_type=StudyType.DATA,
                ))
        return passages


class OpenFoodFacts:
    name = SourceName.OPEN_FOOD_FACTS
    API = "https://search.openfoodfacts.org/search"  # the new search service; the old cgi endpoint often returns 503

    async def search(
        self, client: httpx.AsyncClient, queries: list[str], claim: str, lang: str, limit: int
    ) -> list[Passage]:
        data = await request_json(client, "GET", self.API, params={
            "q": claim, "page_size": min(limit, 3),
            "fields": "code,product_name,brands,nutriments,nutriscore_grade,nova_group",
        })
        passages = []
        for product in data.get("hits") or []:
            name = product.get("product_name") or "Unknown product"
            n = product.get("nutriments") or {}
            brands = product.get("brands")
            brands = ", ".join(brands) if isinstance(brands, list) else brands
            facts = [f"{name}" + (f" ({brands})" if brands else "")]
            for label, key in [("sugars", "sugars_100g"), ("fat", "fat_100g"), ("saturated fat", "saturated-fat_100g"),
                               ("salt", "salt_100g"), ("protein", "proteins_100g"), ("energy kcal", "energy-kcal_100g")]:
                if n.get(key) is not None:
                    facts.append(f"{label}: {n[key]} per 100 g")
            if product.get("nutriscore_grade"):
                facts.append(f"Nutri-Score: {str(product['nutriscore_grade']).upper()}")
            if product.get("nova_group"):
                facts.append(f"NOVA processing group: {product['nova_group']} (4 = ultra-processed)")
            passages.append(Passage(
                id=f"off:{product.get('code')}",
                source=self.name,
                title=f"Open Food Facts: {name}",
                text=". ".join(facts) + ".",
                url=f"https://world.openfoodfacts.org/product/{product.get('code')}",
                authors=["Open Food Facts"],
                study_type=StudyType.DATA,
            ))
        return passages
