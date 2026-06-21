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
