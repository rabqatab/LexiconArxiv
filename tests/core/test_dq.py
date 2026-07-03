from unittest.mock import MagicMock
from src.core.pipeline import dq


def _storage_with_counts(counts):
    """counts: list of ints returned by successive client.count(...).count calls."""
    storage = MagicMock()
    storage.collection_name = "c"
    results = [MagicMock(count=n) for n in counts]
    storage.client.count.side_effect = results
    return storage


# --- doi_papers_have_refs ---

def test_doi_papers_have_refs_pass():
    # total_doi=100, missing_refs=10 -> with_refs=90 -> 90% >= 80% threshold -> pass
    storage = _storage_with_counts([100, 10])
    r = dq.doi_papers_have_refs(storage)
    assert r["passed"] is True
    assert r["metadata"]["doi_papers"] == 100
    assert r["metadata"]["with_refs"] == 90


def test_doi_papers_have_refs_warn_below_threshold():
    storage = _storage_with_counts([100, 50])  # 50% < 80%
    r = dq.doi_papers_have_refs(storage)
    assert r["passed"] is False


def test_doi_papers_have_refs_zero_denominator_passes():
    storage = _storage_with_counts([0, 0])
    r = dq.doi_papers_have_refs(storage)
    assert r["passed"] is True  # nothing to check


# --- real_papers_have_titles ---

def test_real_papers_have_titles_pass():
    storage = _storage_with_counts([0])  # 0 missing titles
    r = dq.real_papers_have_titles(storage)
    assert r["passed"] is True
    assert r["metadata"]["missing_titles"] == 0


def test_real_papers_have_titles_warn():
    storage = _storage_with_counts([5])
    r = dq.real_papers_have_titles(storage)
    assert r["passed"] is False
    assert r["metadata"]["missing_titles"] == 5


# --- graph_metrics_stored ---

def test_graph_metrics_stored_pass():
    storage = _storage_with_counts([424000])
    r = dq.graph_metrics_stored(storage)
    assert r["passed"] is True
    assert r["metadata"]["papers_with_pagerank"] == 424000


def test_graph_metrics_stored_warn_when_zero():
    storage = _storage_with_counts([0])
    r = dq.graph_metrics_stored(storage)
    assert r["passed"] is False


# --- abstract_coverage ---

def test_abstract_coverage_pass():
    # total real papers via count_real_papers(), then _count for missing abstracts
    storage = _storage_with_counts([10])  # missing abstracts = 10
    storage.count_real_papers.return_value = 100  # total = 100 -> 90% >= 80%
    r = dq.abstract_coverage(storage)
    assert r["passed"] is True
    assert r["metadata"]["real_papers"] == 100
    assert r["metadata"]["with_abstract"] == 90


def test_abstract_coverage_warn_below_threshold():
    storage = _storage_with_counts([50])  # missing = 50 out of 100 -> 50% < 80%
    storage.count_real_papers.return_value = 100
    r = dq.abstract_coverage(storage)
    assert r["passed"] is False


def test_abstract_coverage_zero_denominator_passes():
    storage = _storage_with_counts([0])  # missing = 0
    storage.count_real_papers.return_value = 0  # total = 0 -> guard -> passed
    r = dq.abstract_coverage(storage)
    assert r["passed"] is True


# --- embedding_coverage_complete ---

def test_embedding_coverage_complete_pass():
    storage = _storage_with_counts([0])  # 0 embeddable papers missing vector
    r = dq.embedding_coverage_complete(storage)
    assert r["passed"] is True
    assert r["metadata"]["embeddable_missing_vector"] == 0


def test_embedding_coverage_complete_warn():
    storage = _storage_with_counts([3])  # 3 papers have abstract but no vector
    r = dq.embedding_coverage_complete(storage)
    assert r["passed"] is False
    assert r["metadata"]["embeddable_missing_vector"] == 3


# --- cluster_coverage ---

def test_cluster_coverage_pass():
    # clustered=1000, noise=100 -> noise_ratio=10% <= 40%
    storage = _storage_with_counts([1000, 100])
    r = dq.cluster_coverage(storage)
    assert r["passed"] is True
    assert r["metadata"]["clustered"] == 1000
    assert r["metadata"]["noise"] == 100


def test_cluster_coverage_warn_high_noise():
    # clustered=100, noise=50 -> noise_ratio=50% > 40%
    storage = _storage_with_counts([100, 50])
    r = dq.cluster_coverage(storage)
    assert r["passed"] is False


def test_cluster_coverage_zero_denominator_passes():
    # clustered=0 -> noise_ratio=0.0, but passed=False because clustered==0
    storage = _storage_with_counts([0, 0])
    r = dq.cluster_coverage(storage)
    assert r["passed"] is False  # clustered > 0 required


# --- Task 2: source_not_silently_zero ---

def test_source_not_silently_zero_pass():
    storage = MagicMock()
    storage.get_data_quality_stats.return_value = {
        "by_source": {"openalex": 100, "acl": 50, "dblp": 30, "openreview": 200, "aaai": 10}}
    r = dq.source_not_silently_zero(storage)
    assert r["passed"] is True
    assert r["metadata"]["zero_sources"] == 0


def test_source_not_silently_zero_warn_on_zero_source():
    storage = MagicMock()
    storage.get_data_quality_stats.return_value = {
        "by_source": {"openalex": 100, "acl": 0, "dblp": 30}}
    r = dq.source_not_silently_zero(storage)
    assert r["passed"] is False
    assert "acl" in r["metadata"]["zero_source_names"]


# --- abstract_labeling_gap (2026-07-04 gap signal, WARN-only) ---
#
# Fake storage models the reader.count_papers_for_abstract_labeling call — the
# check reuses that method so the filter definition stays in sync with the
# labeling stage. The MagicMock returns the count of "real papers with a
# non-empty abstract AND empty abstract_structure" — exactly the population
# that the labeling gap describes.

def test_abstract_labeling_gap_pass_under_threshold():
    # 500 unlabeled papers < 1000 threshold -> OK
    storage = MagicMock()
    storage.count_papers_for_abstract_labeling.return_value = 500
    r = dq.abstract_labeling_gap(storage)
    assert r["passed"] is True
    assert r["metadata"]["unlabeled_with_abstract"] == 500
    assert r["metadata"]["threshold"] == dq.MAX_UNLABELED_ABSTRACT_BACKLOG
    # Reuse guarantee: check invoked the reader's counter method with skip_existing=True
    storage.count_papers_for_abstract_labeling.assert_called_once_with(skip_existing=True)


def test_abstract_labeling_gap_pass_zero_backlog():
    # Clean corpus: nothing unlabeled -> OK
    storage = MagicMock()
    storage.count_papers_for_abstract_labeling.return_value = 0
    r = dq.abstract_labeling_gap(storage)
    assert r["passed"] is True
    assert r["metadata"]["unlabeled_with_abstract"] == 0


def test_abstract_labeling_gap_warn_over_threshold():
    # 2026-07-04-scale backlog: ~3M unlabeled -> WARN
    storage = MagicMock()
    storage.count_papers_for_abstract_labeling.return_value = 3_000_000
    r = dq.abstract_labeling_gap(storage)
    assert r["passed"] is False
    assert r["metadata"]["unlabeled_with_abstract"] == 3_000_000
    # Message points at the runbook so ops knows the fix
    assert "post-bootstrap-catchup" in r["metadata"]["fix"]


def test_abstract_labeling_gap_boundary_at_threshold():
    # Exactly at threshold is still OK (<= comparison, mirrors other checks)
    storage = MagicMock()
    storage.count_papers_for_abstract_labeling.return_value = dq.MAX_UNLABELED_ABSTRACT_BACKLOG
    r = dq.abstract_labeling_gap(storage)
    assert r["passed"] is True


def test_abstract_labeling_gap_boundary_one_over_threshold():
    storage = MagicMock()
    storage.count_papers_for_abstract_labeling.return_value = dq.MAX_UNLABELED_ABSTRACT_BACKLOG + 1
    r = dq.abstract_labeling_gap(storage)
    assert r["passed"] is False
