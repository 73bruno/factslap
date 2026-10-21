"""Run the evaluation.

Retrieval (does the search find the right paper?), on SciFact, comparing pipeline versions:
    python -m eval.run retrieval --limit 100 --variants v1 abstracts snippets hybrid rerank

End to end (is the verdict right, are the citations real?), on SciFact or the hand-labelled myths:
    python -m eval.run full --dataset myths
    python -m eval.run full --dataset scifact --limit 50 --judge

Results go to eval/results/ as JSON plus a Markdown table printed to the terminal.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from eval.datasets import ClaimCase, load_myths, load_scifact
from eval.metrics import (
    accuracy,
    confusion,
    macro_f1,
    ndcg_at_k,
    percentile,
    recall_at_k,
    reciprocal_rank,
    unique_in_order,
)
from factslap import stages
from factslap.config import Settings
from factslap.llm.client import CostMeter, OpenAIChat, OpenAIEmbedder
from factslap.net import new_client
from factslap.pipeline import FactSlap
from factslap.retrieval.models_api import LLMReranker
from factslap.retrieval.ranker import rank
from factslap.sources.semantic_scholar import SemanticScholar

RESULTS = Path(__file__).parent / "results"

VARIANTS = {
    # name: (use body snippets, use embeddings, use reranker); "v1" reproduces the old ranking.
    "v1": None,
    "abstracts": (False, False, False),
    "snippets": (True, False, False),
    "hybrid": (True, True, False),
    "rerank": (True, True, True),
}


async def retrieve_variant(client, settings, variant, claim, queries, k):
    if variant == "v1":
        # v1: paper search only, abstracts only, sorted by citation count, top 3 kept.
        s2 = SemanticScholar(settings.semantic_scholar_api_key, use_snippets=False)
        passages = await s2.search(client, queries, claim, "en", 10)
        passages.sort(key=lambda p: p.citation_count or 0, reverse=True)
        return [p.corpus_id for p in passages[:3]]
    snippets, embeddings, rerank_on = VARIANTS[variant]
    s2 = SemanticScholar(settings.semantic_scholar_api_key, use_snippets=snippets)
    passages = await s2.search(client, queries, claim, "en", settings.per_source_limit)
    embedder = OpenAIEmbedder(settings.openai_api_key, settings.embedding_model, settings.embedding_dims) if embeddings else None
    llm = OpenAIChat(settings.openai_api_key, settings.fast_model, settings.fallback_model) if rerank_on else None
    reranker = LLMReranker(llm, settings.fast_model) if rerank_on else None
    ranked, _ = await rank(client, claim, queries, passages, k=k, candidates=settings.rerank_candidates,
                           embedder=embedder, reranker=reranker)
    return [p.corpus_id for p, _ in ranked]


async def eval_retrieval(cases: list[ClaimCase], variants: list[str], use_planner: bool, k: int) -> dict:
    settings = Settings()
    app = FactSlap(settings) if use_planner else None
    rows = []
    async with new_client(settings.source_timeout_s) as client:
        for case in [c for c in cases if c.gold_corpus_ids]:
            queries = [case.claim]
            if app is not None:
                plan = await stages.plan(client, app.llm, case.claim, CostMeter())
                queries = plan.queries
            row = {"id": case.id, "claim": case.claim, "gold": sorted(case.gold_corpus_ids), "variants": {}}
            for variant in variants:
                try:
                    ranked_ids = unique_in_order(await retrieve_variant(client, settings, variant, case.claim, queries, k))
                    row["variants"][variant] = ranked_ids
                except Exception as exc:
                    row["variants"][variant] = {"error": str(exc)[:200]}
                await asyncio.sleep(1.1)  # Semantic Scholar keys start at 1 request per second
            rows.append(row)
            print(f"  {len(rows)}/{len(cases)} {case.id}")
    summary = {}
    for variant in variants:
        ok = [r for r in rows if isinstance(r["variants"].get(variant), list)]
        if not ok:
            continue
        summary[variant] = {
            "n": len(ok),
            "errors": len(rows) - len(ok),
            "recall@3": _mean(recall_at_k(set(r["gold"]), r["variants"][variant], 3) for r in ok),
            f"recall@{k}": _mean(recall_at_k(set(r["gold"]), r["variants"][variant], k) for r in ok),
            "mrr": _mean(reciprocal_rank(set(r["gold"]), r["variants"][variant]) for r in ok),
            f"ndcg@{k}": _mean(ndcg_at_k(set(r["gold"]), r["variants"][variant], k) for r in ok),
        }
    return {"summary": summary, "rows": rows}


async def eval_full(cases: list[ClaimCase], use_judge: bool) -> dict:
    settings = Settings()
    app = FactSlap(settings)
    rows = []
    async with new_client(settings.source_timeout_s) as client:
        for case in cases:
            started = time.perf_counter()
            try:
                result = await app.check(case.claim, tone=None, use_cache=False, client=client)
            except Exception as exc:
                rows.append({"id": case.id, "claim": case.claim, "gold": case.label, "error": str(exc)[:300]})
                continue
            faithfulness = None
            if use_judge and result.evidence:
                faithfulness = await stages.judge(client, app.llm, result.answer, result.evidence, CostMeter(),
                                                  settings.reader_model)
            rows.append({
                "id": case.id, "claim": case.claim, "lang": case.lang, "gold": case.label,
                "predicted": result.verdict.label.value, "confidence": result.verdict.confidence,
                "verification_passed": result.verification.passed, "faithfulness": faithfulness,
                "cited_corpus_ids": [e.passage.corpus_id for e in result.evidence if e.passage.corpus_id],
                "gold_corpus_ids": sorted(case.gold_corpus_ids),
                "latency_ms": int((time.perf_counter() - started) * 1000), "cost_usd": result.cost_usd,
                "per_source": next((st.data.get("per_source") for st in result.steps if st.step == "search"), None),
                "answer": result.answer.text,
            })
            print(f"  {len(rows)}/{len(cases)} {case.id}: {rows[-1]['predicted']} (gold {case.label})")
    done = [r for r in rows if "predicted" in r]
    gold, predicted = [r["gold"] for r in done], [r["predicted"] for r in done]
    judged = [r["faithfulness"] for r in done if r["faithfulness"] is not None]
    summary = {
        "n": len(done), "errors": len(rows) - len(done),
        "accuracy": accuracy(gold, predicted), "macro_f1": macro_f1(gold, predicted),
        "confusion": confusion(gold, predicted),
        "verification_pass_rate": _mean(r["verification_passed"] for r in done),
        "faithfulness": _mean(judged) if judged else None,
        "latency_p50_ms": percentile([r["latency_ms"] for r in done], 50),
        "latency_p95_ms": percentile([r["latency_ms"] for r in done], 95),
        "cost_per_claim_usd": _mean(r["cost_usd"] for r in done),
    }
    return {"summary": summary, "rows": rows}


def _mean(values) -> float:
    values = list(values)
    return round(sum(values) / len(values), 4) if values else 0.0


def _markdown(summary: dict) -> str:
    if summary and all(isinstance(v, dict) for v in summary.values()):  # retrieval: one row per variant
        columns = list(next(iter(summary.values())).keys())
        lines = ["| variant | " + " | ".join(columns) + " |", "|---" * (len(columns) + 1) + "|"]
        lines += [f"| {name} | " + " | ".join(str(m[c]) for c in columns) + " |" for name, m in summary.items()]
        return "\n".join(lines)
    return "\n".join(f"- {key}: {value}" for key, value in summary.items())


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    retrieval = sub.add_parser("retrieval")
    retrieval.add_argument("--split", default="dev")
    retrieval.add_argument("--limit", type=int, default=100)
    retrieval.add_argument("--variants", nargs="+", default=["v1", "abstracts", "snippets"], choices=list(VARIANTS))
    retrieval.add_argument("--planner", action="store_true", help="use LLM-planned queries instead of the raw claim")
    retrieval.add_argument("-k", type=int, default=8)
    full = sub.add_parser("full")
    full.add_argument("--dataset", choices=["myths", "scifact"], default="myths")
    full.add_argument("--split", default="dev")
    full.add_argument("--limit", type=int, default=None)
    full.add_argument("--judge", action="store_true", help="also score faithfulness with an LLM judge")
    args = parser.parse_args()

    if args.mode == "retrieval":
        cases = load_scifact(args.split, args.limit)
        output = asyncio.run(eval_retrieval(cases, args.variants, args.planner, args.k))
        name = f"retrieval_scifact_{args.split}_{len(cases)}"
    else:
        cases = load_myths() if args.dataset == "myths" else load_scifact(args.split, args.limit)
        if args.dataset == "myths" and args.limit:
            cases = cases[: args.limit]
        output = asyncio.run(eval_full(cases, args.judge))
        name = f"full_{args.dataset}_{len(cases)}"

    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{datetime.now():%Y%m%d-%H%M}_{name}.json"
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print("\n" + _markdown(output["summary"]) + f"\n\nSaved {path}")


if __name__ == "__main__":
    main()
