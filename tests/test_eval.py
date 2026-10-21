from eval.datasets import load_myths
from eval.metrics import macro_f1, ndcg_at_k, percentile, recall_at_k, reciprocal_rank, unique_in_order
from eval.run import _markdown


def test_retrieval_metrics():
    gold = {7}
    ranked = [3, 7, 9]
    assert recall_at_k(gold, ranked, 1) == 0 and recall_at_k(gold, ranked, 2) == 1
    assert reciprocal_rank(gold, ranked) == 0.5
    assert 0 < ndcg_at_k(gold, ranked, 3) < 1
    assert unique_in_order([3, 3, None, 7, 3]) == [3, 7]


def test_macro_f1_and_percentile():
    assert macro_f1(["a", "b"], ["a", "b"]) == 1.0
    assert macro_f1(["a", "a", "b", "b"], ["a", "a", "a", "a"]) < 0.5
    assert percentile([100, 200, 300, 400], 50) in (200, 300)


def test_myths_are_labelled_and_bilingual():
    myths = load_myths()
    assert len(myths) == 30
    assert {m.label for m in myths} == {"supported", "refuted"}
    assert {m.lang for m in myths} == {"en", "es"}
    assert sum(m.demo for m in myths) >= 8


def test_markdown_table_for_retrieval_summary():
    table = _markdown({"v1": {"n": 2, "mrr": 0.5}, "rerank": {"n": 2, "mrr": 0.9}})
    assert table.splitlines()[0] == "| variant | n | mrr |"
    assert "| rerank | 2 | 0.9 |" in table
