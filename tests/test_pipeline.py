import re

from factslap.config import Settings
from factslap.models import CheckResult, SourceName, StepEvent, StudyType, Tone, VerdictLabel
from factslap.pipeline import FactSlap
from tests.fakes import FakeLLM, FakeSource, passage

CLAIM = "Cracking your knuckles causes arthritis"
TEXTS = [
    "In 300 adults, habitual knuckle cracking was not associated with hand osteoarthritis.",
    "A lifelong self-experiment found no arthritis in either hand after 60 years of cracking.",
    "Knuckle cracking produces a cavitation sound inside the joint fluid.",
]


def make_app(llm_outputs, failing_source=False):
    sources = {
        SourceName.SEMANTIC_SCHOLAR: FakeSource(SourceName.SEMANTIC_SCHOLAR, [
            passage(1, TEXTS[0], StudyType.OBSERVATIONAL), passage(2, TEXTS[1], StudyType.OTHER),
        ]),
        SourceName.WIKIPEDIA: FakeSource(SourceName.WIKIPEDIA, [passage(3, TEXTS[2], StudyType.ENCYCLOPEDIA,
                                                                        source=SourceName.WIKIPEDIA)],
                                         fail=failing_source),
    }
    settings = Settings(openai_api_key=None, supabase_url=None, supabase_service_key=None, llm_rerank=False)
    llm = FakeLLM(llm_outputs)
    return FactSlap(settings, llm=llm, sources=sources), llm


def stances(prompt: str) -> dict:
    """Refute with the two study passages, whatever order the ranker put them in."""
    items = []
    for ref, block in enumerate(re.findall(r'<passage ref="\d+">(.*?)</passage>', prompt, re.S), start=1):
        quote = next((t for t in TEXTS[:2] if t in block), None)
        items.append({"ref": ref, "stance": "refutes", "quote": quote, "rationale": "no link"} if quote
                     else {"ref": ref, "stance": "irrelevant"})
    return {"items": items}


def outputs(answer_text="Studies of habitual crackers found no link with arthritis [1][2].", styled_text=None):
    answers = [{"text": answer_text, "short": "No link found [1]."}]
    if styled_text:
        answers.append({"text": styled_text, "short": "Nope [1]."})
    return {
        "PlanOut": {"lang": "en", "english_claim": CLAIM, "subclaims": [CLAIM], "queries": ["knuckle cracking osteoarthritis"],
                    "claim_type": "health", "sources": ["wikipedia"]},
        "StanceOut": stances,
        "AnswerOut": answers,
    }


async def run(app, tone=Tone.AGGRESSIVE):
    events = [e async for e in app.run(CLAIM, tone)]
    return [e for e in events if isinstance(e, StepEvent)], events[-1]


async def test_full_run_refutes_the_myth_with_verified_citations():
    app, llm = make_app(outputs())
    steps, result = await run(app, tone=None)
    assert isinstance(result, CheckResult)
    assert result.verdict.label == VerdictLabel.REFUTED
    assert [e.stance.value for e in result.evidence] == ["refutes", "refutes"]
    assert result.verification.passed
    assert [s.step for s in steps] == ["plan", "search", "rank", "evidence", "verdict", "verify"]
    assert result.cost_usd > 0


async def test_semantic_scholar_is_always_searched_and_a_failing_source_is_reported():
    app, _ = make_app(outputs(), failing_source=True)
    steps, result = await run(app, tone=None)
    search = next(s for s in steps if s.step == "search")
    assert search.data["per_source"]["semantic_scholar"] == 2
    assert search.data["per_source"]["wikipedia"].startswith("error")
    assert result.verdict.label == VerdictLabel.REFUTED


async def test_answer_with_invented_number_is_retried_with_feedback():
    out = outputs()
    out["AnswerOut"] = [{"text": "No link in 9000 people [1].", "short": "No [1]."},
                        {"text": "No link with arthritis in 300 adults [1][2].", "short": "No [1]."}]
    app, llm = make_app(out)
    _, result = await run(app, tone=None)
    assert result.verification.passed
    retry_prompt = [user for name, user in llm.calls if name == "AnswerOut"][1]
    assert "9000" in retry_prompt


async def test_tone_that_changes_the_facts_is_discarded():
    out = outputs(styled_text="LOL, 5000 studies say no [1].")
    app, _ = make_app(out)
    steps, result = await run(app, tone=Tone.AGGRESSIVE)
    assert result.styled_answer is None
    assert result.verdict.label == VerdictLabel.REFUTED
    assert next(s for s in steps if s.step == "tone").message == "Kept the neutral wording"


async def test_tone_never_reaches_the_verdict_stage():
    app, llm = make_app(outputs(styled_text="Nice try: no link at all [1][2]."))
    _, result = await run(app, tone=Tone.AGGRESSIVE)
    stance_prompts = [user for name, user in llm.calls if name in {"StanceOut", "PlanOut"}]
    assert all("aggressive" not in p.lower() for p in stance_prompts)
    assert result.styled_answer is not None


async def test_intention_shapes_wording_but_never_the_verdict():
    from factslap.models import Intention

    app, llm = make_app(outputs(styled_text="Sorry, the studies are not on your side: no link [1][2]."))
    events = [e async for e in app.run(CLAIM, Tone.CASUAL, intention=Intention.VALIDATE)]
    result = events[-1]
    assert result.verdict.label == VerdictLabel.REFUTED
    assert result.intention == Intention.VALIDATE
    style_prompt = [user for name, user in llm.calls if name == "AnswerOut"][-1]
    assert "verdict (final): refuted" in style_prompt
    assert "evidence" in result.disclaimer
