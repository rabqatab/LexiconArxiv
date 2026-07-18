"""Batch-write conversions (Wave 1e): each batch_update_* must emit ONE
batch_update_points call with wait=False, not N per-point set_payload calls.
"""

import pytest

from src.core.storage.writer import BatchWriter


class RecordingClient:
    """Captures batch_update_points / set_payload calls for assertions."""

    def __init__(self):
        self.batch_calls = []   # list of (operations, wait)
        self.set_payload_calls = 0

    def batch_update_points(self, collection_name, update_operations, wait=True):
        self.batch_calls.append((update_operations, wait))

    def set_payload(self, collection_name, payload, points):
        self.set_payload_calls += 1


def _writer():
    return BatchWriter(RecordingClient(), "test")


def _ops(client):
    assert len(client.batch_calls) == 1, "must be exactly one batched HTTP call"
    ops, wait = client.batch_calls[0]
    assert wait is False, "batched writes use wait=False (async ack)"
    return ops


def _payload(op):
    return op.set_payload.payload


# --- one representative call per converted function: one batch call, right count ---

def test_referenced_works():
    w = _writer()
    n = w.batch_update_referenced_works([("A", ["r1"]), ("B", ["r2"])])
    ops = _ops(w.client)
    assert n == 2 and len(ops) == 2
    assert _payload(ops[0])["referenced_works"] == ["r1"]
    assert "enriched_at" in _payload(ops[0])
    assert w.client.set_payload_calls == 0


def test_abstracts():
    w = _writer()
    w.batch_update_abstracts([("A", "abs")])
    assert _payload(_ops(w.client)[0])["abstract"] == "abs"


def test_papers_with_doi_and_refs():
    w = _writer()
    w.batch_update_papers_with_doi_and_refs([("A", "10.1/x", ["r"])])
    p = _payload(_ops(w.client)[0])
    assert p["doi"] == "10.1/x" and p["referenced_works"] == ["r"]


def test_referenced_works_normalized():
    w = _writer()
    w.batch_update_referenced_works_normalized([("A", ["r"])])
    assert _payload(_ops(w.client)[0]) == {"referenced_works": ["r"]}


def test_resolved_references():
    w = _writer()
    w.batch_update_resolved_references([("A", ["pid1", "pid2"])])
    assert _payload(_ops(w.client)[0]) == {"resolved_references": ["pid1", "pid2"]}


def test_graph_metrics():
    w = _writer()
    w.batch_update_graph_metrics([("A", {"pagerank": 0.5})])
    assert _payload(_ops(w.client)[0]) == {"pagerank": 0.5}


def test_keywords():
    w = _writer()
    w.batch_update_keywords([("A", ["k1", "k2"])])
    assert _payload(_ops(w.client)[0]) == {"keywords": ["k1", "k2"]}


def test_keywords_with_source_3_and_4_tuple():
    w = _writer()
    w.batch_update_keywords_with_source([
        ("A", ["k"], "llm"),
        ("B", ["k"], "llm", {"topic": ["k"]}),
    ])
    ops = _ops(w.client)
    assert len(ops) == 2
    assert "keywords_structured" not in _payload(ops[0])           # 3-tuple → no structured
    assert _payload(ops[1])["keywords_structured"] == {"topic": ["k"]}


def test_code_repos_optional_url():
    w = _writer()
    w.batch_update_code_repos([("A", [{"url": "x"}], "x"), ("B", [], None)])
    ops = _ops(w.client)
    assert _payload(ops[0])["code_url"] == "x"
    assert "code_url" not in _payload(ops[1])                      # no best_url → key absent


def test_field_fill_skips_empty_and_stamps_provenance():
    w = _writer()
    n = w.batch_apply_field_fill([("A", {"year": 2020}), ("B", {})])  # B empty → skipped
    ops = _ops(w.client)
    assert n == 1 and len(ops) == 1
    assert _payload(ops[0])["year"] == 2020
    assert "snapshot_filled_at" in _payload(ops[0])


@pytest.mark.parametrize("fn", [
    "batch_update_referenced_works", "batch_update_abstracts",
    "batch_update_papers_with_doi_and_refs", "batch_update_referenced_works_normalized",
    "batch_update_resolved_references", "batch_update_graph_metrics",
    "batch_update_keywords", "batch_update_keywords_with_source",
    "batch_update_code_repos", "batch_apply_field_fill",
])
def test_empty_updates_no_http(fn):
    w = _writer()
    assert getattr(w, fn)([]) == 0
    assert len(w.client.batch_calls) == 0    # empty input → zero HTTP calls
