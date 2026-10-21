"""Test doubles: an LLM that answers by schema, and a source that returns fixed passages."""
from __future__ import annotations

from factslap.llm.client import CostMeter
from factslap.models import Passage, SourceName, StudyType


def passage(i: int, text: str, study: StudyType = StudyType.RCT, source=SourceName.SEMANTIC_SCHOLAR, **kw) -> Passage:
    return Passage(id=f"p{i}", source=source, title=f"Study {i}", text=text, year=2020 + i, study_type=study, **kw)


class FakeLLM:
    """Returns canned outputs keyed by the requested schema's class name. Records every call."""

    def __init__(self, outputs: dict):
        self.outputs = outputs
        self.calls: list[tuple[str, str]] = []

    async def generate(self, client, system, user, schema, meter: CostMeter, temperature=0.2, model=None):
        self.calls.append((schema.__name__, user))
        meter.add("fake", 100, 50)
        value = self.outputs[schema.__name__]
        if callable(value):  # computed from the prompt, e.g. stances that depend on passage order
            value = value(user)
        if isinstance(value, list):  # successive answers for repeated calls
            value = value.pop(0) if len(value) > 1 else value[0]
        return schema.model_validate(value)


class FakeSource:
    def __init__(self, name: SourceName, passages: list[Passage], fail: bool = False):
        self.name, self.passages, self.fail = name, passages, fail

    async def search(self, client, queries, claim, lang, limit):
        if self.fail:
            raise RuntimeError("source down")
        return self.passages[:limit]
