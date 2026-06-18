from unittest.mock import MagicMock
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
    assert all(c.kwargs["payload"].get("enrichment_source") == "openalex_snapshot" for c in calls)
