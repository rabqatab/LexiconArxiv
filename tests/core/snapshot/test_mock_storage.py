import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "corpus" / "seed_papers.json"


def test_seed_and_get(mock_storage):
    mock_storage.seed_from_json(FIXTURE)
    p = mock_storage.get_payload("real-001")
    assert p is not None
    assert p["doi"] == "10.1000/seed-doi-001"


def test_set_payload_merges(mock_storage):
    mock_storage.set_payload("x", {"a": 1, "b": 2})
    mock_storage.set_payload("x", {"b": 99, "c": 3})
    assert mock_storage.get_payload("x") == {"a": 1, "b": 99, "c": 3}


def test_has_vector_default_false(mock_storage):
    mock_storage.set_payload("x", {})
    assert mock_storage.has_vector("x") is False
    mock_storage.vector_set("x")
    assert mock_storage.has_vector("x") is True


def test_count_with_filter(mock_storage):
    mock_storage.seed_from_json(FIXTURE)
    real = mock_storage.count_with_filter(must_not_is_stub=True)
    assert real == 10


def test_mock_iter_real_papers_minimal(mock_storage):
    mock_storage.seed_from_json(FIXTURE)
    out = list(mock_storage.iter_all_real_papers_minimal())
    assert len(out) == 10
    assert "title_norm" in out[0]


def test_mock_build_referenced_anchor(mock_storage):
    mock_storage.seed_from_json(FIXTURE)
    m = mock_storage.build_referenced_openalex_id_set()
    # at least one ref present in seeds; we asserted real-005..010 include W1000000008
    assert m.get("W1000000008", 0) >= 2


def test_mock_batch_apply_field_fill_stamps_provenance(mock_storage):
    mock_storage.set_payload("p", {"a": 1})
    n = mock_storage.batch_apply_field_fill([("p", {"b": 2})])
    assert n == 1
    pl = mock_storage.get_payload("p")
    assert pl["b"] == 2
    assert "snapshot_filled_at" in pl


def test_mock_batch_inject_papers_creates_then_skips_dup(mock_storage):
    out1 = mock_storage.batch_inject_papers([
        {"openalex_id": "W42", "work_fields": {"title": "X", "openalex_id": "W42"}, "injection_path": "anchor"}
    ])
    assert out1[0]["status"] == "created"
    out2 = mock_storage.batch_inject_papers([
        {"openalex_id": "W42", "work_fields": {"title": "X", "openalex_id": "W42"}, "injection_path": "anchor"}
    ])
    assert out2[0]["status"] == "skipped_dup"
