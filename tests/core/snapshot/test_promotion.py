import pytest

from src.core.snapshot.promotion import Decision, evaluate


def test_evaluate_promote_when_title_and_abstract():
    stub = {"title": None, "year": None, "authors": []}
    fields = {"title": "X", "abstract": "..."}
    assert evaluate(stub, fields) is Decision.PROMOTE


def test_evaluate_promote_when_title_year_and_author():
    stub = {"title": None, "year": None, "authors": []}
    fields = {"title": "X", "year": 2024, "authors": [{"display_name": "A"}]}
    assert evaluate(stub, fields) is Decision.PROMOTE


def test_evaluate_enrich_keep_stub_when_partial():
    stub = {"title": None, "year": None, "authors": []}
    fields = {"year": 2024}   # title still missing
    assert evaluate(stub, fields) is Decision.ENRICH_KEEP_STUB


def test_evaluate_skip_when_nothing_gained():
    stub = {"title": "Existing", "year": 2024, "authors": [{"display_name": "X"}]}
    fields = {}    # extractor returned nothing
    assert evaluate(stub, fields) is Decision.SKIP


def test_evaluate_skip_when_only_fields_already_on_stub():
    stub = {"title": "Existing", "year": 2024, "authors": [{"display_name": "X"}]}
    fields = {"title": "Existing", "year": 2024}
    assert evaluate(stub, fields) is Decision.SKIP


# ---------------------------------------------------------------------------
# Task 2: promote_one transaction wrapper
# ---------------------------------------------------------------------------
import pytest
from pathlib import Path

from src.core.snapshot.promotion import promote_one, PromotionError
from src.core.snapshot import embedding_queue


def test_promote_one_promotes_and_queues(mock_storage, tmp_path):
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    stub = next(s for s in mock_storage.iter_stubs_for_resolution()
                if s["point_id"] == "stub-doi-001")
    fields = {
        "title": "Stub DOI Match",
        "doi": "10.1000/stub-doi-001",
        "year": 2024,
        "authors": [{"display_name": "Alice"}],
        "abstract": "abstract text",
    }
    result = promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
    assert result is Decision.PROMOTE
    p = mock_storage.get_payload("stub-doi-001")
    assert p["is_stub"] is False
    assert p["cited_by"] == ["real-005", "real-006"]
    assert p["cited_by_count"] == 2
    assert p["promoted_from_stub"] is True
    queued = list(embedding_queue.drain(root=tmp_path))
    assert queued == [("stub-doi-001", "promotion")]


def test_promote_one_no_abstract_does_not_queue(mock_storage, tmp_path):
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    stub = next(s for s in mock_storage.iter_stubs_for_resolution()
                if s["point_id"] == "stub-doi-002")
    fields = {"title": "X", "year": 2024, "authors": [{"display_name": "Y"}]}  # no abstract
    result = promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
    assert result is Decision.PROMOTE
    queued = list(embedding_queue.drain(root=tmp_path))
    assert queued == []


def test_promote_one_merges_when_real_dup_exists(mock_storage, tmp_path):
    """If a real paper already exists with the same DOI, merge the stub into it."""
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    # Plant a real paper with the same DOI as stub-doi-001
    mock_storage.set_payload("real-existing", {
        "is_stub": False,
        "doi": "10.1000/stub-doi-001",
        "cited_by": ["real-007"],
        "cited_by_count": 1,
    })
    stub = next(s for s in mock_storage.iter_stubs_for_resolution()
                if s["point_id"] == "stub-doi-001")
    fields = {"title": "Stub DOI Match", "doi": "10.1000/stub-doi-001",
              "year": 2024, "authors": [{"display_name": "Alice"}], "abstract": "x"}
    result = promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
    assert result is Decision.MERGED_INTO_EXISTING
    real = mock_storage.get_payload("real-existing")
    assert set(real["cited_by"]) == {"real-005", "real-006", "real-007"}
    assert mock_storage.get_payload("stub-doi-001") is None  # stub deleted


def test_promote_one_idempotent_on_already_promoted(mock_storage, tmp_path):
    """Re-running promote_one on an already-promoted point is safe."""
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    stub = next(s for s in mock_storage.iter_stubs_for_resolution()
                if s["point_id"] == "stub-doi-001")
    fields = {"title": "Stub DOI Match", "doi": "10.1000/stub-doi-001",
              "year": 2024, "authors": [{"display_name": "Alice"}], "abstract": "x"}
    promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
    # second run
    p_before = dict(mock_storage.get_payload("stub-doi-001"))
    promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
    p_after = mock_storage.get_payload("stub-doi-001")
    # cited_by must not duplicate
    assert p_after["cited_by"] == p_before["cited_by"]


def test_promote_one_skips_merge_when_allow_merge_false(mock_storage, tmp_path):
    """When allow_merge=False, promote_one must NOT call merge_stub_into_real."""
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    # Plant a real paper with the same DOI as stub-doi-001
    mock_storage.set_payload("real-existing", {
        "is_stub": False,
        "doi": "10.1000/stub-doi-001",
        "cited_by": ["real-007"],
        "cited_by_count": 1,
    })
    stub = next(s for s in mock_storage.iter_stubs_for_resolution()
                if s["point_id"] == "stub-doi-001")
    original_cited_by = list(stub.get("cited_by") or [])
    fields = {"title": "Stub DOI Match", "doi": "10.1000/stub-doi-001",
              "year": 2024, "authors": [{"display_name": "Alice"}], "abstract": "x"}

    result = promote_one(mock_storage, stub, fields,
                         embedding_queue_root=tmp_path, allow_merge=False)

    assert result is Decision.MERGED_INTO_EXISTING
    # Real paper's cited_by must NOT have been mutated (merge did not happen)
    real = mock_storage.get_payload("real-existing")
    assert real["cited_by"] == ["real-007"], "cited_by on real paper was mutated despite allow_merge=False"
    # Stub must still exist (was not deleted)
    assert mock_storage.get_payload("stub-doi-001") is not None, "stub was deleted despite allow_merge=False"


def test_cited_by_invariant_after_many_promotions(mock_storage, tmp_path):
    """Run 5 promotions, then assert no promoted point lost its cited_by."""
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    promoted: dict[str, list[str]] = {}
    for stub in list(mock_storage.iter_stubs_for_resolution()):
        if stub["identifier_type"] in ("doi", "openalex"):
            promoted[stub["point_id"]] = list(stub["cited_by"])
            fields = {"title": "T", "year": 2024, "authors": [{"display_name": "A"}], "abstract": "x"}
            try:
                promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
            except PromotionError:
                continue
    # Invariant: no promoted point ended up with cited_by==[] when it started non-empty
    for pid, original in promoted.items():
        pl = mock_storage.get_payload(pid)
        if pl is None:
            continue  # merged
        if pl.get("promoted_from_stub") is True and original:
            assert pl["cited_by"], f"{pid} lost cited_by; was {original}"
