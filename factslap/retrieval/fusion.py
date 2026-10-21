"""Reciprocal rank fusion: merge several rankings without having to calibrate their scores."""
from __future__ import annotations

from collections import defaultdict


def rrf(rankings: list[list[str]], k: int = 60, weights: list[float] | None = None) -> dict[str, float]:
    """Each ranking is a list of ids, best first. Returns id -> fused score (higher is better)."""
    weights = weights or [1.0] * len(rankings)
    fused: dict[str, float] = defaultdict(float)
    for ranking, weight in zip(rankings, weights):
        for position, item_id in enumerate(ranking):
            fused[item_id] += weight / (k + position + 1)
    return dict(fused)


def rank_by(scores: dict[str, float]) -> list[str]:
    return [item for item, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]
