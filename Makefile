.PHONY: test lint eval-retrieval eval-myths check

test:
	.venv/bin/python -m pytest -q

lint:
	.venv/bin/ruff check factslap eval tests

# Retrieval ablation on SciFact (needs SEMANTIC_SCHOLAR_API_KEY; hybrid/rerank need GEMINI/VOYAGE keys)
eval-retrieval:
	.venv/bin/python -m eval.run retrieval --limit 100 --variants v1 abstracts snippets hybrid rerank

# End-to-end verdicts on the 30 hand-labelled myths
eval-myths:
	.venv/bin/python -m eval.run full --dataset myths --judge

# Try one claim: make check CLAIM="Sugar makes kids hyperactive"
check:
	.venv/bin/python -m factslap "$(CLAIM)" --tone debate
