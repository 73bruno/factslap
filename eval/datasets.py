"""Evaluation datasets.

SciFact (Wadden et al., 2020, Allen Institute for AI): scientific claims with the abstracts that support or
contradict them. Claims are CC BY 4.0 and abstracts ODC-By 1.0. Its document ids are Semantic Scholar
CorpusIds, so we can check whether the live search finds the right paper.
Data is downloaded on demand into eval/data/ (git-ignored).
"""
from __future__ import annotations

import json
import tarfile
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
SCIFACT_URL = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz"
MYTHS_FILE = Path(__file__).parent / "myths.jsonl"

LABELS = {"SUPPORT": "supported", "CONTRADICT": "refuted"}


@dataclass
class ClaimCase:
    id: str
    claim: str
    label: str  # supported | refuted | not_enough_evidence | mixed
    gold_corpus_ids: set[int]
    lang: str = "en"
    demo: bool = False


def download_scifact() -> Path:
    target = DATA_DIR / "scifact"
    if (target / "claims_dev.jsonl").exists():
        return target
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    archive = DATA_DIR / "scifact.tar.gz"
    urllib.request.urlretrieve(SCIFACT_URL, archive)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name.endswith(".jsonl"):
                member.name = Path(member.name).name  # flatten, and never write outside the target folder
                tar.extract(member, target)
    archive.unlink()
    return target


def load_scifact(split: str = "dev", limit: int | None = None) -> list[ClaimCase]:
    folder = download_scifact()
    cases = []
    with open(folder / f"claims_{split}.jsonl") as handle:
        for line in handle:
            row = json.loads(line)
            evidence = row.get("evidence") or {}
            votes = Counter(LABELS[s["label"]] for sets in evidence.values() for s in sets if s.get("label") in LABELS)
            if not votes:
                label = "not_enough_evidence"
            elif len(votes) > 1:
                label = "mixed"
            else:
                label = votes.most_common(1)[0][0]
            gold = {int(d) for d in evidence}  # empty for not-enough-info claims; those skip the retrieval metrics
            cases.append(ClaimCase(id=f"scifact-{row['id']}", claim=row["claim"], label=label, gold_corpus_ids=gold))
            if limit and len(cases) >= limit:
                break
    return cases


def load_myths() -> list[ClaimCase]:
    cases = []
    with open(MYTHS_FILE) as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                cases.append(ClaimCase(id=row["id"], claim=row["claim"], label=row["label"], gold_corpus_ids=set(),
                                       lang=row.get("lang", "en"), demo=row.get("demo", False)))
    return cases
