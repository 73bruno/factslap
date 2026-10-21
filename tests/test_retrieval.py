from factslap.models import SourceName
from factslap.retrieval.fusion import rank_by, rrf
from factslap.retrieval.lexical import bm25_scores, tokenize
from factslap.retrieval.ranker import dedupe, rank, source_order
from tests.fakes import passage


def test_tokenize_folds_accents_and_drops_stopwords():
    assert tokenize("El café y la atención") == ["cafe", "atencion"]


def test_bm25_prefers_documents_with_query_terms():
    docs = ["knuckle cracking and arthritis in adults", "coffee and attention", "arthritis treatment options"]
    scores = bm25_scores("knuckle cracking arthritis", docs)
    assert scores.index(max(scores)) == 0
    assert scores[1] == 0


def test_rrf_rewards_items_ranked_well_everywhere():
    fused = rrf([["a", "b", "c"], ["b", "a", "c"], ["b", "c", "a"]])
    assert rank_by(fused)[0] == "b"


def test_dedupe_keeps_the_richer_copy_of_the_same_abstract():
    poor = passage(1, "Same abstract text about caffeine and attention in adults.", doi="10.1/x")
    rich = passage(2, "Same abstract text about caffeine and attention in adults.", doi="10.1/X", venue="Nature",
                   citation_count=10)
    other = passage(3, "Different text entirely about sleep.")
    kept = dedupe([poor, rich, other])
    assert {p.id for p in kept} == {"p2", "p3"}


def test_source_order_interleaves_sources():
    a = [passage(i, f"text {i}", source=SourceName.SEMANTIC_SCHOLAR) for i in range(3)]
    b = [passage(10 + i, f"text {10 + i}", source=SourceName.WIKIPEDIA) for i in range(2)]
    assert source_order(a + b)[:4] == ["p0", "p10", "p1", "p11"]


async def test_rank_without_optional_services_returns_top_k():
    passages = [passage(i, f"unrelated text number {i}") for i in range(10)]
    passages.append(passage(99, "Knuckle cracking was not associated with hand osteoarthritis."))
    ranked, stats = await rank(None, "knuckle cracking causes arthritis", ["knuckle cracking osteoarthritis"],
                               passages, k=3, candidates=20)
    assert len(ranked) == 3
    assert ranked[0][0].id == "p99"
    assert not stats.used_embeddings and not stats.used_reranker


def test_dedupe_keeps_one_source_per_paper():
    from factslap.models import SourceName as S

    a = passage(1, "Background. Knuckle cracking was studied in 215 people.", source=S.EUROPE_PMC)
    b = passage(2, "Knuckle cracking was studied in 215 people and compared.", source=S.OPENALEX, doi="10.1/kc",
                venue="JABFM")
    a.title = "Knuckle cracking and hand osteoarthritis."
    b.title = "Knuckle Cracking and Hand Osteoarthritis"
    assert [p.id for p in dedupe([a, b])] == ["p2"]
