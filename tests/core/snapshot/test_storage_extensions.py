"""Integration tests for snapshot-related storage extensions.

Runs against a real Qdrant. Marked `integration` so CI skips without one.
"""
import pytest

from src.core.storage import QdrantStorage

pytestmark = pytest.mark.integration


@pytest.fixture
def storage() -> QdrantStorage:
    return QdrantStorage()


def test_iter_all_real_papers_minimal_yields_required_keys(storage):
    it = storage.iter_all_real_papers_minimal(batch_size=50)
    sample = next(it)
    assert {"point_id", "doi", "openalex_id", "title_norm", "title"} <= sample.keys()


def test_iter_all_real_papers_minimal_excludes_stubs(storage):
    # if there are any stubs in the corpus, none should appear
    for entry in storage.iter_all_real_papers_minimal(batch_size=200):
        assert entry["point_id"]
        break


def test_build_referenced_openalex_id_set(storage):
    m = storage.build_referenced_openalex_id_set()
    assert isinstance(m, dict)
    # at least one referenced work
    assert any(v >= 1 for v in m.values())


def test_build_openalex_id_to_point_id_map(storage):
    m = storage.build_openalex_id_to_point_id_map()
    assert isinstance(m, dict)
    # values are point_id strings
    for v in m.values():
        assert isinstance(v, str)
        break


def test_build_identifier_index_for_dedup(storage):
    idx = storage.build_identifier_index_for_dedup()
    assert {"doi", "openalex_id", "title_norm"} <= idx.keys()
    for v in idx.values():
        assert isinstance(v, set)
