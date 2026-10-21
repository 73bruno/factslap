"""Data shapes shared by every stage of the pipeline."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SourceName(str, Enum):
    SEMANTIC_SCHOLAR = "semantic_scholar"
    EUROPE_PMC = "europe_pmc"
    OPENALEX = "openalex"
    FACT_CHECK = "fact_check"
    WIKIPEDIA = "wikipedia"
    WORLD_BANK = "world_bank"
    OPEN_FOOD_FACTS = "open_food_facts"
    INDEX = "index"  # our own Supabase index of passages seen before


class StudyType(str, Enum):
    META_ANALYSIS = "meta_analysis"
    SYSTEMATIC_REVIEW = "systematic_review"
    RCT = "rct"
    OBSERVATIONAL = "observational"
    REVIEW = "review"
    FACT_CHECK = "fact_check"
    ENCYCLOPEDIA = "encyclopedia"
    DATA = "data"
    OTHER = "other"


class Passage(BaseModel):
    """One piece of evidence text, whatever source it came from."""

    id: str  # stable id, e.g. "s2:12345#2" or "epmc:PMC123"
    source: SourceName
    title: str
    text: str
    url: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    doi: str | None = None
    corpus_id: int | None = None  # Semantic Scholar CorpusId, used by the SciFact eval
    study_type: StudyType = StudyType.OTHER
    citation_count: int | None = None
    lang: str = "en"
    source_score: float | None = None  # score given by the source itself, if any

    @property
    def dedupe_key(self) -> str:
        """Same paper and same opening text: the same abstract seen through two sources."""
        if self.doi:
            base = f"doi:{self.doi.lower()}"
        elif self.corpus_id is not None:
            base = f"s2:{self.corpus_id}"
        else:
            base = self.id
        opening = " ".join(self.text.lower().split())[:80]
        return f"{base}|{opening}"


class ClaimType(str, Enum):
    HEALTH = "health"
    NUTRITION = "nutrition"
    SCIENCE = "science"
    ECONOMY = "economy"
    GENERAL = "general"


class Plan(BaseModel):
    """What the planner decided to look for."""

    claim: str
    lang: str = Field(description="ISO code of the claim's language, e.g. 'es' or 'en'")
    subclaims: list[str] = Field(description="Atomic claims to verify; usually just one")
    english_claim: str = ""  # the claim in plain English, used as one more search query
    queries: list[str] = Field(description="2-3 short English search queries for scientific databases")
    claim_type: ClaimType = ClaimType.GENERAL
    sources: list[SourceName] = Field(default_factory=list)


class Stance(str, Enum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    NEUTRAL = "neutral"
    IRRELEVANT = "irrelevant"


class Evidence(BaseModel):
    """A ranked passage plus what it says about the claim."""

    ref: int  # 1-based number used in citations like [1]
    passage: Passage
    stance: Stance
    quote: str = Field(description="Exact sentence from the passage that shows the stance")
    rationale: str = ""
    rank_score: float = 0.0


class VerdictLabel(str, Enum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    MIXED = "mixed"
    NOT_ENOUGH_EVIDENCE = "not_enough_evidence"


class Verdict(BaseModel):
    label: VerdictLabel
    confidence: float = Field(ge=0, le=1)
    supporting: int = 0
    refuting: int = 0
    explanation: str = ""  # how the label and confidence were reached, in plain words


class Tone(str, Enum):
    ACADEMIC = "academic"
    CASUAL = "casual"
    AGGRESSIVE = "aggressive"  # "win the argument" mode: witty, never insulting


DISCLAIMER = (
    "The verdict is decided first, from the evidence alone. The tone only changes the wording, "
    "never the verdict or the sources. FactSlap summarises published research and can be wrong; "
    "it is not medical, legal or financial advice."
)


class Answer(BaseModel):
    text: str  # with inline citations like [1][2]
    short: str = ""  # tweet-sized version
    cited_refs: list[int] = Field(default_factory=list)


class Check(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class VerificationReport(BaseModel):
    passed: bool
    checks: list[Check] = Field(default_factory=list)


class StepEvent(BaseModel):
    """Emitted after each pipeline stage; the web shows them as the 'how we checked' trace."""

    step: str
    message: str
    ms: int = 0
    data: dict = Field(default_factory=dict)


class CheckResult(BaseModel):
    claim: str
    lang: str
    plan: Plan
    verdict: Verdict
    evidence: list[Evidence]
    answer: Answer  # neutral version
    styled_answer: Answer | None = None  # same facts, chosen tone
    verification: VerificationReport
    steps: list[StepEvent] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER
    share_id: str | None = None  # short id for the public link /c/<id>, set by the API
    cost_usd: float = 0.0
    latency_ms: int = 0
