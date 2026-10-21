from factslap.models import Answer, Evidence, Stance, StudyType, VerdictLabel
from factslap.stages import cited_refs, decide
from factslap.verify import check_answer, numbers_in, quote_in_passage, same_facts
from tests.fakes import passage


def ev(ref, stance, study=StudyType.RCT, text="Caffeine improved reaction time in 40 adults.", quote=None):
    p = passage(ref, text, study)
    p.title = f"A distinct study about caffeine number {ref}"
    return Evidence(ref=ref, passage=p, stance=stance, quote=quote if quote is not None else text)


def test_no_evidence_means_not_enough_evidence():
    assert decide([]).label == VerdictLabel.NOT_ENOUGH_EVIDENCE


def test_one_weak_source_is_not_enough():
    verdict = decide([ev(1, Stance.SUPPORTS, StudyType.ENCYCLOPEDIA)])
    assert verdict.label == VerdictLabel.NOT_ENOUGH_EVIDENCE


def test_agreeing_good_sources_give_a_confident_verdict():
    verdict = decide([ev(1, Stance.REFUTES, StudyType.META_ANALYSIS), ev(2, Stance.REFUTES), ev(3, Stance.REFUTES)])
    assert verdict.label == VerdictLabel.REFUTED
    assert verdict.confidence > 0.8


def test_split_evidence_is_mixed():
    verdict = decide([ev(1, Stance.SUPPORTS), ev(2, Stance.REFUTES), ev(3, Stance.NEUTRAL)])
    assert verdict.label == VerdictLabel.MIXED


def test_quote_matching_ignores_case_and_spacing():
    assert quote_in_passage("caffeine  improved REACTION time", "Overall, caffeine improved reaction time in adults.")
    assert not quote_in_passage("caffeine cured cancer", "Overall, caffeine improved reaction time in adults.")
    assert not quote_in_passage("short", "short")  # too short to prove anything


def test_numbers_ignore_citation_markers():
    assert numbers_in("In 40 adults [2], 3.5 hours [10]") == {"40", "3.5"}
    assert numbers_in("un 3,5 %") == {"3.5"}


def test_check_answer_catches_invented_numbers_and_unknown_citations():
    evidence = [ev(1, Stance.SUPPORTS)]
    answer = Answer(text="Caffeine helped 400 adults [1][3].", cited_refs=cited_refs("[1][3]"))
    report = check_answer(answer, evidence, "caffeine helps", VerdictLabel.SUPPORTED)
    failed = {c.name for c in report.checks if not c.passed}
    assert failed == {"citations_exist", "numbers_grounded"}


def test_check_answer_passes_a_grounded_answer():
    evidence = [ev(1, Stance.SUPPORTS)]
    answer = Answer(text="In a trial with 40 adults, caffeine improved reaction time [1].", cited_refs=[1])
    assert check_answer(answer, evidence, "caffeine helps", VerdictLabel.SUPPORTED).passed


def test_restyled_answer_may_not_add_numbers_or_drop_citations():
    neutral = Answer(text="40 adults reacted faster [1].", cited_refs=[1])
    assert same_facts(neutral, Answer(text="Forty? No, 40 adults, and they were faster [1].", cited_refs=[1]))
    assert not same_facts(neutral, Answer(text="400 adults reacted faster [1].", cited_refs=[1]))
    assert not same_facts(neutral, Answer(text="Adults reacted faster.", cited_refs=[]))


def test_one_paper_alone_cannot_decide():
    one = ev(1, Stance.SUPPORTS, StudyType.SYSTEMATIC_REVIEW)
    same_paper = ev(2, Stance.SUPPORTS, StudyType.SYSTEMATIC_REVIEW)
    same_paper.passage.title = one.passage.title  # two chunks of the same review
    verdict = decide([one, same_paper])
    assert verdict.label == VerdictLabel.NOT_ENOUGH_EVIDENCE
    assert "independent papers" in verdict.explanation
