"""Retrieval and classification metrics (plain Python, no dependencies)."""
from __future__ import annotations

import math
from collections import Counter


def recall_at_k(gold: set, ranked: list, k: int) -> float:
    if not gold:
        return 0.0
    return len(gold & set(ranked[:k])) / len(gold)


def reciprocal_rank(gold: set, ranked: list) -> float:
    for position, item in enumerate(ranked, start=1):
        if item in gold:
            return 1 / position
    return 0.0


def ndcg_at_k(gold: set, ranked: list, k: int) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, item in enumerate(ranked[:k]) if item in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal if ideal else 0.0


def unique_in_order(items: list) -> list:
    seen, out = set(), []
    for item in items:
        if item is not None and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def accuracy(gold: list[str], predicted: list[str]) -> float:
    return sum(g == p for g, p in zip(gold, predicted)) / len(gold) if gold else 0.0


def macro_f1(gold: list[str], predicted: list[str]) -> float:
    labels = sorted(set(gold))
    scores = []
    for label in labels:
        tp = sum(g == p == label for g, p in zip(gold, predicted))
        fp = sum(p == label and g != label for g, p in zip(gold, predicted))
        fn = sum(g == label and p != label for g, p in zip(gold, predicted))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def confusion(gold: list[str], predicted: list[str]) -> dict[str, dict[str, int]]:
    table: dict[str, Counter] = {}
    for g, p in zip(gold, predicted):
        table.setdefault(g, Counter())[p] += 1
    return {g: dict(c) for g, c in table.items()}


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q / 100 * (len(ordered) - 1))))
    return ordered[index]
