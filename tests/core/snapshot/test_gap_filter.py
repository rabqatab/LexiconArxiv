from src.core.snapshot.gap_filter import (
    AI_CONCEPT_IDS,
    Classification,
    Thresholds,
    classify,
)


def _work(**kwargs) -> dict:
    base = {
        "id": "https://openalex.org/W0",
        "publication_year": 2024,
        "cited_by_count": 0,
        "concepts": [],
    }
    base.update(kwargs)
    return base


def test_anchor_inject_when_citers_meets_threshold():
    work = _work(id="https://openalex.org/W42")
    cls = classify(work, anchor_set={"W42": 5},
                   taxonomy=AI_CONCEPT_IDS, thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.ANCHOR_INJECT


def test_anchor_inject_rejected_below_threshold():
    work = _work(id="https://openalex.org/W42")
    cls = classify(work, anchor_set={"W42": 1},
                   taxonomy=AI_CONCEPT_IDS, thresholds=Thresholds(), now_year=2026)
    # not anchor; falls through to concept check; no AI concepts → REJECT
    assert cls is Classification.REJECT


def test_concept_inject_recent_meets_threshold():
    ai_concept = next(iter(AI_CONCEPT_IDS))
    work = _work(
        publication_year=2024, cited_by_count=60,
        concepts=[{"id": f"https://openalex.org/{ai_concept}", "display_name": "AI"}],
    )
    cls = classify(work, anchor_set={}, taxonomy=AI_CONCEPT_IDS,
                   thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.CONCEPT_INJECT


def test_concept_reject_recent_below_threshold():
    ai_concept = next(iter(AI_CONCEPT_IDS))
    work = _work(
        publication_year=2024, cited_by_count=10,
        concepts=[{"id": f"https://openalex.org/{ai_concept}", "display_name": "AI"}],
    )
    cls = classify(work, anchor_set={}, taxonomy=AI_CONCEPT_IDS,
                   thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.REJECT


def test_concept_reject_too_old_year():
    ai_concept = next(iter(AI_CONCEPT_IDS))
    work = _work(
        publication_year=2015, cited_by_count=1000,
        concepts=[{"id": f"https://openalex.org/{ai_concept}", "display_name": "AI"}],
    )
    cls = classify(work, anchor_set={}, taxonomy=AI_CONCEPT_IDS,
                   thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.REJECT


def test_anchor_wins_over_concept():
    """When both rules pass, ANCHOR is the recorded classification."""
    ai_concept = next(iter(AI_CONCEPT_IDS))
    work = _work(
        id="https://openalex.org/W42",
        publication_year=2024, cited_by_count=100,
        concepts=[{"id": f"https://openalex.org/{ai_concept}", "display_name": "AI"}],
    )
    cls = classify(work, anchor_set={"W42": 5}, taxonomy=AI_CONCEPT_IDS,
                   thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.ANCHOR_INJECT


def test_concept_reject_when_no_ai_concept():
    work = _work(
        publication_year=2024, cited_by_count=1000,
        concepts=[{"id": "https://openalex.org/C0000000", "display_name": "Other"}],
    )
    cls = classify(work, anchor_set={}, taxonomy=AI_CONCEPT_IDS,
                   thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.REJECT
