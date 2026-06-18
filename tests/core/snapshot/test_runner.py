import gzip
import json
from unittest.mock import MagicMock, patch
from src.core.snapshot import runner
from src.core.storage.reader import PaperReader


def test_iter_enrichment_candidates_yields_fields(monkeypatch):
    # Two scroll pages then empty; each point has payload we care about
    # NOTE: stored author field is `authors: list[str]` (name strings), not `authorships`
    pt = MagicMock()
    pt.id = "p1"
    pt.payload = {"doi": "10.1/x", "title": "A Title", "year": 2020,
                  "authors": ["Jane Doe"],
                  "abstract": "", "referenced_works": []}
    storage = MagicMock()
    storage.client.scroll.side_effect = [([pt], "off1"), ([], None)]
    storage.collection_name = "c"

    rows = list(PaperReader.iter_enrichment_candidates(storage, batch_size=10))
    assert rows[0]["point_id"] == "p1"
    assert rows[0]["doi"] == "10.1/x"
    assert rows[0]["title"] == "A Title"
    assert rows[0]["missing_abstract"] is True
    assert rows[0]["missing_refs"] is True


def test_batch_apply_snapshot_enrichment_sets_payload_and_provenance():
    from src.core.storage.writer import BatchWriter
    storage = MagicMock()
    storage.collection_name = "c"
    updates = [("p1", {"abstract": "hi"}), ("p2", {"referenced_works": ["W1"]})]
    n = BatchWriter.batch_apply_snapshot_enrichment(storage, updates)
    assert n == 2
    # each call set_payload with the field + provenance
    calls = storage.client.set_payload.call_args_list
    assert any("abstract" in c.kwargs["payload"] for c in calls)
    assert all(c.kwargs["payload"].get("openalex_snapshot_enriched") is True for c in calls)


def test_qdrantstorage_exposes_snapshot_methods():
    # Regression: the QdrantStorage facade must delegate the new methods, else the
    # CLI (which uses a real QdrantStorage) AttributeErrors at runtime.
    from src.core.storage import QdrantStorage
    assert hasattr(QdrantStorage, "iter_enrichment_candidates")
    assert hasattr(QdrantStorage, "batch_apply_snapshot_enrichment")


def _write_gz(tmp_path, works):
    f = tmp_path / "updated_date=2020-01-01"
    f.mkdir(parents=True)
    gz = f / "0000_part_00.gz"
    with gzip.open(gz, "wt", encoding="utf-8") as fh:
        for w in works:
            fh.write(json.dumps(w) + "\n")
    return tmp_path


def test_runner_matches_and_writes(tmp_path):
    works = [
        {"doi": "https://doi.org/10.1/x", "title": "x", "publication_year": 2019,
         "abstract_inverted_index": {"Hello": [0]}, "referenced_works": []},
        {"doi": None, "title": "Graph Models", "publication_year": 2021,
         "authorships": [{"author": {"display_name": "A Lee"}}],
         "abstract_inverted_index": {"Refs": [0]}, "referenced_works": ["W9"]},
    ]
    snap = _write_gz(tmp_path, works)
    candidates = [
        {"point_id": "d1", "doi": "10.1/x", "title": "x", "year": 2019,
         "first_author": "smith", "missing_abstract": True, "missing_refs": False},
        {"point_id": "t1", "doi": None, "title": "Graph Models", "year": 2021,
         "first_author": "lee", "missing_abstract": True, "missing_refs": True},
    ]
    storage = MagicMock()
    storage.collection_name = "c"
    storage.iter_enrichment_candidates.return_value = iter(candidates)
    storage.batch_apply_snapshot_enrichment.return_value = 2

    result = runner.run_snapshot_enrichment(
        storage=storage, snapshot_dir=str(snap), dry_run=False, batch_size=10,
    )
    assert result["doi_matches"] == 1
    assert result["title_matches"] == 1
    assert result["applied"] >= 1
    assert storage.batch_apply_snapshot_enrichment.called


def test_runner_dry_run_writes_nothing(tmp_path):
    snap = _write_gz(tmp_path, [
        {"doi": "https://doi.org/10.1/x", "title": "x", "publication_year": 2019,
         "abstract_inverted_index": {"Hi": [0]}, "referenced_works": []}])
    storage = MagicMock()
    storage.collection_name = "c"
    storage.iter_enrichment_candidates.return_value = iter([
        {"point_id": "d1", "doi": "10.1/x", "title": "x", "year": 2019,
         "first_author": "smith", "missing_abstract": True, "missing_refs": False}])
    result = runner.run_snapshot_enrichment(storage=storage, snapshot_dir=str(snap), dry_run=True)
    assert result["doi_matches"] == 1
    assert not storage.batch_apply_snapshot_enrichment.called
