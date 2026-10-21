"""BM25 over the candidate passages of one request (no index needed, works in any language)."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

_WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = set("""
a an and are as at be by for from has have in is it its of on or that the this to was were with
el la los las un una unos unas y o de del al en que es son por para con se su sus lo como mas más
""".split())


def tokenize(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return [t for t in _WORD.findall(folded) if t not in STOPWORDS and len(t) > 1]


def bm25_scores(query: str, documents: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Okapi BM25 score of `query` against each document."""
    docs = [tokenize(d) for d in documents]
    if not docs:
        return []
    avg_len = sum(len(d) for d in docs) / len(docs) or 1.0
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))
    n = len(docs)
    terms = tokenize(query)
    scores = []
    for doc in docs:
        tf = Counter(doc)
        score = 0.0
        for term in terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            freq = tf[term]
            score += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * len(doc) / avg_len))
        scores.append(score)
    return scores
