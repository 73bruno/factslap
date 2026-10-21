"""Common interface for evidence sources and small text helpers they share."""
from __future__ import annotations

import html
import re
from typing import Protocol

import httpx

from factslap.models import Passage, SourceName, StudyType

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


class Source(Protocol):
    name: SourceName

    async def search(
        self, client: httpx.AsyncClient, queries: list[str], claim: str, lang: str, limit: int
    ) -> list[Passage]:
        """Return passages for the claim. `queries` are English search queries from the planner."""
        ...


def clean_text(raw: str | None) -> str:
    """Strip HTML and collapse whitespace."""
    if not raw:
        return ""
    return _SPACES.sub(" ", _TAGS.sub(" ", html.unescape(raw))).strip()


def author_names(authors: list | None, limit: int = 6) -> list[str]:
    names: list[str] = []
    for author in authors or []:
        if isinstance(author, str):
            names.append(author)
        elif isinstance(author, dict) and author.get("name"):
            names.append(author["name"])
    return names[:limit]


_STUDY_TYPE_HINTS: list[tuple[str, StudyType]] = [
    ("meta-analysis", StudyType.META_ANALYSIS),
    ("metaanalysis", StudyType.META_ANALYSIS),
    ("systematic review", StudyType.SYSTEMATIC_REVIEW),
    ("systematic-review", StudyType.SYSTEMATIC_REVIEW),
    ("randomized controlled trial", StudyType.RCT),
    ("clinicaltrial", StudyType.RCT),
    ("clinical trial", StudyType.RCT),
    ("cohort", StudyType.OBSERVATIONAL),
    ("case-control", StudyType.OBSERVATIONAL),
    ("observational", StudyType.OBSERVATIONAL),
    ("review", StudyType.REVIEW),
]


def guess_study_type(labels: list[str] | None, title: str = "") -> StudyType:
    """Map publication-type labels (and, failing that, the title) to a study type."""
    haystack = " ".join(labels or []).lower() + " | " + title.lower()
    for hint, study_type in _STUDY_TYPE_HINTS:
        if hint in haystack:
            return study_type
    return StudyType.OTHER


def split_passages(text: str, max_words: int = 220, overlap: int = 40) -> list[str]:
    """Split long text into overlapping windows of whole sentences (for full texts and long abstracts)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        words = len(sentence.split())
        if current and count + words > max_words:
            chunks.append(" ".join(current))
            # keep the tail of the previous chunk as overlap
            tail: list[str] = []
            tail_words = 0
            for previous in reversed(current):
                tail_words += len(previous.split())
                tail.insert(0, previous)
                if tail_words >= overlap:
                    break
            current, count = tail, tail_words
        current.append(sentence)
        count += words
    if current:
        chunks.append(" ".join(current))
    return [c for c in chunks if c]
