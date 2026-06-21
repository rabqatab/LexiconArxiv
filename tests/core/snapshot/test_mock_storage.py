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
