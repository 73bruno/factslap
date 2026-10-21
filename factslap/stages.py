"""The LLM stages (plan, stance, answer, style, judge) and the deterministic verdict in between."""
from __future__ import annotations

import re

import httpx
from pydantic import BaseModel, Field

from factslap.llm import prompts
from factslap.llm.client import LLM, CostMeter
from factslap.models import (
    Answer,
    ClaimType,
    Evidence,
    Intention,
    Passage,
    Plan,
    SourceName,
    Stance,
    StudyType,
    Tone,
    Verdict,
    VerdictLabel,
)
from factslap.retrieval.ranker import paper_key
from factslap.verify import normalise, quote_in_passage

# ---------- plan ----------


class PlanOut(BaseModel):
    lang: str
    english_claim: str
    subclaims: list[str]
    queries: list[str]
    claim_type: ClaimType
    sources: list[SourceName]


async def plan(client: httpx.AsyncClient, llm: LLM, claim: str, meter: CostMeter) -> Plan:
    out = await llm.generate(client, prompts.PLANNER_SYSTEM, prompts.planner_user(claim), PlanOut, meter, 0.0)
    sources = [s for s in out.sources if s != SourceName.INDEX]
    # Always searched: the two scholarly catalogues, plus Wikipedia (cheap, and good on popular myths).
    for backbone in (SourceName.WIKIPEDIA, SourceName.OPENALEX, SourceName.SEMANTIC_SCHOLAR):
        if backbone not in sources:
            sources.insert(0, backbone)
    english = out.english_claim.strip() or claim
    queries = [english] + [q for q in out.queries if q.strip() and q.strip().lower() != english.lower()][:3]
    return Plan(
        claim=claim, lang=out.lang[:2].lower() or "en", subclaims=out.subclaims or [claim], english_claim=english,
        queries=queries, claim_type=out.claim_type, sources=sources,
    )


# ---------- stance ----------


class StanceItem(BaseModel):
    ref: int
    stance: Stance
    quote: str = ""
    rationale: str = ""
    design: StudyType | None = None  # study design as described in the passage, if any


class StanceOut(BaseModel):
    items: list[StanceItem]


async def assess(
    client: httpx.AsyncClient, llm: LLM, claim: str, ranked: list[tuple[Passage, float]], meter: CostMeter,
    model: str | None = None,
) -> list[Evidence]:
    passages = [p for p, _ in ranked]
    out = await llm.generate(client, prompts.STANCE_SYSTEM, prompts.stance_user(claim, passages), StanceOut, meter, 0.0,
                             model)
    by_ref = {item.ref: item for item in out.items}
    evidence: list[Evidence] = []
    for ref, (passage, score) in enumerate(ranked, start=1):
        item = by_ref.get(ref)
        if item is None or item.stance == Stance.IRRELEVANT:
            continue
        stance = item.stance
        if passage.study_type == StudyType.OTHER and item.design in RESEARCH_DESIGNS:
            passage.study_type = item.design  # the source gave no publication type; the text did
        # No verbatim proof, no vote: a quote that isn't in the passage turns the passage neutral.
        if stance in (Stance.SUPPORTS, Stance.REFUTES) and not quote_in_passage(item.quote, passage.text):
            stance = Stance.NEUTRAL
        evidence.append(Evidence(
            ref=0, passage=passage, stance=stance, quote=item.quote.strip(),
            rationale=item.rationale, rank_score=score,
        ))
    # A design found in one chunk of a paper applies to every chunk of that paper.
    designs = {paper_key(e.passage): e.passage.study_type for e in evidence if e.passage.study_type != StudyType.OTHER}
    for item in evidence:
        item.passage.study_type = designs.get(paper_key(item.passage), item.passage.study_type)
    for new_ref, item in enumerate(evidence, start=1):
        item.ref = new_ref  # renumber so citations are 1..n over the evidence actually shown
    return evidence


RESEARCH_DESIGNS = {StudyType.META_ANALYSIS, StudyType.SYSTEMATIC_REVIEW, StudyType.RCT, StudyType.OBSERVATIONAL,
                    StudyType.REVIEW}

# ---------- verdict (no LLM: a formula you can explain) ----------

QUALITY: dict[StudyType, float] = {
    StudyType.META_ANALYSIS: 1.0,
    StudyType.SYSTEMATIC_REVIEW: 0.95,
    StudyType.RCT: 0.85,
    StudyType.FACT_CHECK: 0.8,
    StudyType.REVIEW: 0.7,
    StudyType.DATA: 0.7,
    StudyType.OBSERVATIONAL: 0.6,
    StudyType.OTHER: 0.6,
    StudyType.ENCYCLOPEDIA: 0.5,
}
MIN_WEIGHT = 0.85  # e.g. a randomised trial plus anything else, or two ordinary sources
MIN_PAPERS = 2  # a verdict needs at least two independent papers on the winning side
AGREEMENT_FOR_LABEL = 0.7


def decide(evidence: list[Evidence]) -> Verdict:
    support = sum(QUALITY[e.passage.study_type] for e in evidence if e.stance == Stance.SUPPORTS)
    refute = sum(QUALITY[e.passage.study_type] for e in evidence if e.stance == Stance.REFUTES)
    n_support = sum(e.stance == Stance.SUPPORTS for e in evidence)
    n_refute = sum(e.stance == Stance.REFUTES for e in evidence)
    papers = {
        side: {paper_key(e.passage) for e in evidence if e.stance == side} for side in (Stance.SUPPORTS, Stance.REFUTES)
    }
    total = support + refute
    winning = Stance.SUPPORTS if support > refute else Stance.REFUTES
    clear_side = total > 0 and max(support, refute) / total >= AGREEMENT_FOR_LABEL
    if total >= MIN_WEIGHT and clear_side and len(papers[winning]) < MIN_PAPERS:
        return Verdict(
            label=VerdictLabel.NOT_ENOUGH_EVIDENCE, confidence=0.5, supporting=n_support, refuting=n_refute,
            explanation=f"Only one paper takes a side; at least {MIN_PAPERS} independent papers are needed to decide.",
        )
    if total < MIN_WEIGHT:
        return Verdict(
            label=VerdictLabel.NOT_ENOUGH_EVIDENCE, confidence=0.5, supporting=n_support, refuting=n_refute,
            explanation=f"Evidence weight {total:.2f} is below the {MIN_WEIGHT} needed to decide.",
        )
    agreement = max(support, refute) / total
    strength = min(1.0, total / 3.0)  # three good sources saturate it
    confidence = round(max(0.05, min(0.99, agreement * strength)), 2)
    if agreement < AGREEMENT_FOR_LABEL:
        label = VerdictLabel.MIXED
    else:
        label = VerdictLabel.SUPPORTED if support > refute else VerdictLabel.REFUTED
    return Verdict(
        label=label, confidence=confidence, supporting=n_support, refuting=n_refute,
        explanation=(f"Support weight {support:.2f} vs refute weight {refute:.2f} (by study quality); "
                     f"agreement {agreement:.0%}, strength {strength:.0%}."),
    )


# ---------- answer and tone ----------


class AnswerOut(BaseModel):
    text: str
    short: str


def cited_refs(text: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\[(\d+)\]", text)})


async def write_answer(
    client: httpx.AsyncClient, llm: LLM, claim: str, verdict: Verdict, evidence: list[Evidence], lang: str,
    meter: CostMeter, model: str | None = None, feedback: str = "",
) -> Answer:
    user = prompts.answer_user(claim, verdict, evidence, lang)
    if feedback:
        user += f"\n\nA previous draft failed these checks, fix them: {feedback}"
    out = await llm.generate(client, prompts.ANSWER_SYSTEM, user, AnswerOut, meter, 0.3, model)
    return Answer(text=out.text.strip(), short=out.short.strip(), cited_refs=cited_refs(out.text + " " + out.short))


async def restyle(
    client: httpx.AsyncClient, llm: LLM, answer: Answer, tone: Tone, intention: Intention, verdict: Verdict, lang: str,
    meter: CostMeter, model: str | None = None,
) -> Answer:
    user = prompts.style_user(answer.text, answer.short, tone, intention, verdict.label.value, lang)
    out = await llm.generate(client, prompts.STYLE_SYSTEM, user, AnswerOut, meter, 0.7, model)
    return Answer(text=out.text.strip(), short=out.short.strip(), cited_refs=cited_refs(out.text + " " + out.short))


# ---------- judge (used by the evaluation, optional in production) ----------


class SentenceJudgement(BaseModel):
    sentence: str
    label: str = Field(description="supported, partial or unsupported")


class JudgeOut(BaseModel):
    sentences: list[SentenceJudgement]


async def judge(
    client: httpx.AsyncClient, llm: LLM, answer: Answer, evidence: list[Evidence], meter: CostMeter, model: str | None = None,
) -> float:
    """Share of answer sentences fully supported by their cited evidence (faithfulness)."""
    out = await llm.generate(client, prompts.JUDGE_SYSTEM, prompts.judge_user(answer.text, evidence), JudgeOut, meter, 0.0,
                             model)
    if not out.sentences:
        return 0.0
    return sum(normalise(s.label) == "supported" for s in out.sentences) / len(out.sentences)
