"""Deterministic checks on an answer before it reaches the user. No LLM involved."""
from __future__ import annotations

import re
import unicodedata

from factslap.models import Answer, Check, Evidence, Stance, VerdictLabel, VerificationReport

_NUMBER = re.compile(r"(?<![\[\w])(\d+(?:[.,]\d+)?)(?![\]\w])")


def normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "").lower()
    folded = folded.replace("’", "'").replace("“", '"').replace("”", '"')
    return " ".join(folded.split())


def quote_in_passage(quote: str, passage_text: str) -> bool:
    """True if the quote appears in the passage, ignoring case, spacing and a trailing full stop."""
    q = normalise(quote).rstrip(".")
    return len(q) >= 12 and q in normalise(passage_text)


def numbers_in(text: str) -> set[str]:
    """Numbers in running text, ignoring citation markers like [2]."""
    without_citations = re.sub(r"\[\d+\]", " ", text)
    return {n.replace(",", ".") for n in _NUMBER.findall(without_citations)}


def check_answer(
    answer: Answer, evidence: list[Evidence], claim: str, verdict_label: VerdictLabel,
) -> VerificationReport:
    refs = {e.ref for e in evidence}
    checks: list[Check] = []

    unknown = [r for r in answer.cited_refs if r not in refs]
    checks.append(Check(
        name="citations_exist", passed=not unknown,
        detail=f"unknown citation numbers: {unknown}" if unknown else f"{len(answer.cited_refs)} citations, all valid",
    ))

    needs_citations = verdict_label != VerdictLabel.NOT_ENOUGH_EVIDENCE
    checks.append(Check(
        name="has_citations", passed=bool(answer.cited_refs) or not needs_citations,
        detail="answer cites evidence" if answer.cited_refs else "answer has no citations",
    ))

    allowed = numbers_in(claim)
    for e in evidence:
        allowed |= numbers_in(e.passage.text) | numbers_in(e.passage.title) | {str(e.passage.year)}
    invented = sorted(numbers_in(answer.text + " " + answer.short) - allowed)
    checks.append(Check(
        name="numbers_grounded", passed=not invented,
        detail=f"numbers not found in any source: {invented}" if invented else "every number appears in the sources",
    ))

    voting = [e for e in evidence if e.stance in (Stance.SUPPORTS, Stance.REFUTES)]
    bad_quotes = [e.ref for e in voting if not quote_in_passage(e.quote, e.passage.text)]
    checks.append(Check(
        name="quotes_verbatim", passed=not bad_quotes,
        detail=f"quotes not found verbatim: {bad_quotes}" if bad_quotes else f"{len(voting)} quotes found word for word",
    ))

    return VerificationReport(passed=all(c.passed for c in checks), checks=checks)


def same_facts(original: Answer, styled: Answer) -> bool:
    """A restyled answer must keep the citations and may not introduce numbers."""
    return (set(styled.cited_refs) <= set(original.cited_refs) and bool(styled.cited_refs) == bool(original.cited_refs)
            and numbers_in(styled.text + " " + styled.short) <= numbers_in(original.text + " " + original.short))
