"""Wave 4c topic gate + A1(a) type gate — keep / delete / no-topic samples."""
from src.core.snapshot.topic_gate import is_keep_topic, is_keep_type
from src.core.snapshot import phase2_stub_resolution, phase3_gap_discovery  # noqa: F401 — gates import


KEEP_WORK_TOPIC = {
    "display_name": "Natural Language Processing",
    "field": {"display_name": "Computer Science"},
    "subfield": {"display_name": "Artificial Intelligence"},
}
LINGUISTICS_TOPIC = {
    "field": {"display_name": "Arts and Humanities"},
    "subfield": {"display_name": "Language and Linguistics"},
}
DELETE_WORK_TOPIC = {
    "display_name": "Cancer-related Molecular Pathways",
    "field": {"display_name": "Biochemistry, Genetics and Molecular Biology"},
    "subfield": {"display_name": "Oncology"},
}


def test_keep_field():
    assert is_keep_topic(KEEP_WORK_TOPIC)


def test_keep_linguistics_subfield():
    assert is_keep_topic(LINGUISTICS_TOPIC)


def test_delete_cross_domain():
    assert not is_keep_topic(DELETE_WORK_TOPIC)


def test_no_topic_rejected():
    assert not is_keep_topic(None)
    assert not is_keep_topic({})
    assert not is_keep_topic({"field": None})
    assert not is_keep_topic("Computer Science")  # malformed shape


def test_keep_type_papers():
    for t in ("article", "preprint", "review", "book-chapter", "dissertation",
              "report", "dataset", "letter"):
        assert is_keep_type({"type": t}), t


def test_keep_type_missing_or_malformed():
    assert is_keep_type({})              # no type -> crawler paper, keep
    assert is_keep_type({"type": None})
    assert is_keep_type({"type": ""})
    assert is_keep_type("not a dict")


def test_drop_type_nonpaper():
    for t in ("book", "paratext", "other", "editorial", "reference-entry",
              "erratum", "standard", "retraction", "peer-review"):
        assert not is_keep_type({"type": t}), t


def test_p3_process_one_rejects_by_type():
    # on-topic (passes topic gate) but type=book -> reject_type
    work = {"id": "https://openalex.org/W998", "primary_topic": KEEP_WORK_TOPIC,
            "type": "book", "referenced_works": [], "concepts": []}
    dedup_idx = {"openalex_id": set(), "doi": set()}
    from src.core.snapshot import phase3_gap_discovery as p3
    from src.core.snapshot.gap_filter import Classification, Thresholds
    orig = p3.classify
    p3.classify = lambda *a, **k: Classification.ANCHOR_INJECT
    try:
        res = p3.process_one(work, dedup_idx, set(), storage=None,
                             thresholds=Thresholds(), now_year=2026, dry_run=True)
    finally:
        p3.classify = orig
    assert res["action"] == "reject_type"


def test_p2_promote_downgraded_by_type(monkeypatch):
    from src.core.snapshot import phase2_stub_resolution as p2
    from src.core.snapshot.promotion import Decision

    stub = {"point_id": "stub-2", "identifier_type": "doi", "identifier": "doi:10.1/y"}
    # on-topic but type=editorial -> promotion downgraded to enrich-keep-stub
    work = {"id": "https://openalex.org/W2", "primary_topic": KEEP_WORK_TOPIC,
            "type": "editorial"}
    monkeypatch.setattr(p2, "match_work_for_stubs", lambda *a, **k: stub)
    monkeypatch.setattr(p2, "extract_full_record", lambda w: {"title": "T", "abstract": "A"})
    monkeypatch.setattr(p2, "evaluate", lambda *a, **k: Decision.PROMOTE)

    applied = []

    class FakeStorage:
        def batch_apply_field_fill(self, updates):
            applied.extend(updates)
            return len(updates)

    res = p2.process_one(work, None, {}, storage=FakeStorage(), dry_run=False)
    assert res["action"] == "enriched"  # NOT promoted


def test_p3_process_one_rejects_by_topic():
    work = {"id": "https://openalex.org/W999", "primary_topic": DELETE_WORK_TOPIC,
            "referenced_works": [], "concepts": []}
    dedup_idx = {"openalex_id": set(), "doi": set()}

    # classify() must say inject for the gate to be the deciding factor —
    # monkeypatch classify to a fixed ANCHOR_INJECT.
    from src.core.snapshot import phase3_gap_discovery as p3
    from src.core.snapshot.gap_filter import Classification, Thresholds
    orig = p3.classify
    p3.classify = lambda *a, **k: Classification.ANCHOR_INJECT
    try:
        res = p3.process_one(work, dedup_idx, set(), storage=None,
                             thresholds=Thresholds(), now_year=2026, dry_run=True)
    finally:
        p3.classify = orig
    assert res["action"] == "reject_topic"


def test_p2_promote_downgraded_to_enrich(monkeypatch):
    from src.core.snapshot import phase2_stub_resolution as p2
    from src.core.snapshot.promotion import Decision

    stub = {"point_id": "stub-1", "identifier_type": "doi", "identifier": "doi:10.1/x"}
    work = {"id": "https://openalex.org/W1", "primary_topic": DELETE_WORK_TOPIC}

    monkeypatch.setattr(p2, "match_work_for_stubs", lambda *a, **k: stub)
    monkeypatch.setattr(p2, "extract_full_record", lambda w: {"title": "T", "abstract": "A"})
    monkeypatch.setattr(p2, "evaluate", lambda *a, **k: Decision.PROMOTE)

    applied = []

    class FakeStorage:
        def batch_apply_field_fill(self, updates):
            applied.extend(updates)
            return len(updates)

    res = p2.process_one(work, None, {}, storage=FakeStorage(), dry_run=False)
    assert res["action"] == "enriched"  # NOT promoted
    assert applied and applied[0][0] == "stub-1"
