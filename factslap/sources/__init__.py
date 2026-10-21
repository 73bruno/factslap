"""Evidence sources. Each one returns `Passage` objects through the same `search` interface."""
from __future__ import annotations

from factslap.config import Settings
from factslap.models import SourceName
from factslap.sources.base import Source
from factslap.sources.europe_pmc import EuropePMC
from factslap.sources.fact_check import FactCheck
from factslap.sources.open_data import OpenFoodFacts, WorldBank
from factslap.sources.openalex import OpenAlex
from factslap.sources.semantic_scholar import SemanticScholar
from factslap.sources.wikipedia import Wikipedia


def build_sources(settings: Settings) -> dict[SourceName, Source]:
    return {
        SourceName.SEMANTIC_SCHOLAR: SemanticScholar(settings.semantic_scholar_api_key),
        SourceName.EUROPE_PMC: EuropePMC(),
        SourceName.OPENALEX: OpenAlex(settings.openalex_api_key),
        SourceName.FACT_CHECK: FactCheck(settings.google_api_key),
        SourceName.WIKIPEDIA: Wikipedia(),
        SourceName.WORLD_BANK: WorldBank(),
        SourceName.OPEN_FOOD_FACTS: OpenFoodFacts(),
    }


__all__ = ["Source", "build_sources"]
