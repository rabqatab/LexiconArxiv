"""Data-quality metric functions for Dagster asset-checks.

Each returns {"passed": bool, "metadata": dict}. Pure reads over Qdrant via
client.count(). Thresholds are CALIBRATION constants (warn-only phase) — tune
after observing real values, before any flip to blocking ERROR (Phase 3b).

Deferred to Phase 3b (documented reasons):
- new_paper_count_sane: needs a persisted rolling baseline across runs; a
  single point-in-time count cannot judge "sane" without history.
- no_dangling_graph_nodes: no post-hoc Qdrant query available; requires
  build_cited_by to persist its build-time skipped_missing count.
"""

from qdrant_client import models

from src.core.storage import QdrantStorage
from src.core.constants import STRUCTURED_VECTOR_NAME

# CALIBRATION thresholds (warn-only)
MIN_DOI_REFS_RATIO = 0.80
MIN_ABSTRACT_COVERAGE = 0.80
MAX_CLUSTER_NOISE_RATIO = 0.40
# Labeling-gap early warning: allow a small buffer for the freshly-collected
# papers that haven't had a chance to be labeled yet (incremental cycle runs
# label-abstracts step). Anything larger indicates a real backlog and should
# be caught before it silently degrades section-vector search on new papers.
# See the 2026-07-04 labeling gap incident that motivated this check.
MAX_UNLABELED_ABSTRACT_BACKLOG = 1000

_STUB = models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))
_EMPTY_ABSTRACT = models.FieldCondition(key="abstract", match=models.MatchValue(value=""))

# "No real abstract" = key missing/null (IsEmpty) OR an empty string. Qdrant's
# IsEmpty does NOT match an empty-string value, so both conditions are needed —
# this is the same definition the embedder uses to decide embeddability.
_NO_ABSTRACT = [models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract")),
                _EMPTY_ABSTRACT]


def _count(storage, must=None, must_not=None, should=None) -> int:
    # exact=True: the FILTERED counts these checks use are fast even on the
    # multi-million-point collection. Approximate (exact=False) counts are
    # badly wrong for IsEmpty/HasVector filters (observed ~50% error — e.g.
    # real-papers-with-abstract reported 85,095 vs the true 165,954), which
    # made every coverage metric meaningless. Only an UNFILTERED full count of
    # the whole 3.6M collection would risk a timeout, and no check does that.
    # A Filter with `should` requires at least one should-condition to match
    # (OR semantics), combined with any must / must_not.
    flt = models.Filter(must=must, must_not=must_not, should=should)
    return storage.client.count(
        collection_name=storage.collection_name, count_filter=flt, exact=True,
    ).count


def doi_papers_have_refs(storage: QdrantStorage | None = None) -> dict:
    """Of non-stub papers WITH a DOI, what fraction have referenced_works."""
    storage = storage or QdrantStorage()
    no_doi = models.IsEmptyCondition(is_empty=models.PayloadField(key="doi"))
    total_doi = _count(storage, must_not=[_STUB, no_doi])
    missing_refs = _count(
        storage,
        must=[models.IsEmptyCondition(is_empty=models.PayloadField(key="referenced_works"))],
        must_not=[_STUB, no_doi],
    )
    with_refs = total_doi - missing_refs
    ratio = (with_refs / total_doi) if total_doi else 1.0
    return {
        "passed": ratio >= MIN_DOI_REFS_RATIO,
        "metadata": {"doi_papers": total_doi, "with_refs": with_refs,
                     "ratio": round(ratio, 4)},
    }


def abstract_coverage(storage: QdrantStorage | None = None) -> dict:
    """Fraction of non-stub papers with a non-empty abstract."""
    storage = storage or QdrantStorage()
    total = storage.count_real_papers()
    # missing = non-stub AND (abstract null/missing OR empty-string)
    missing = _count(storage, must_not=[_STUB], should=_NO_ABSTRACT)
    with_abs = total - missing
    ratio = (with_abs / total) if total else 1.0
    return {
        "passed": ratio >= MIN_ABSTRACT_COVERAGE,
        "metadata": {"real_papers": total, "with_abstract": with_abs,
                     "ratio": round(ratio, 4)},
    }


def embedding_coverage_complete(storage: QdrantStorage | None = None) -> dict:
    """Of non-stub papers WITH an abstract, all should have the dense vector."""
    storage = storage or QdrantStorage()
    # non-stub, has a REAL abstract (not null/missing, not ""), but missing the
    # structured-abstract vector. Empty-string abstracts are not embeddable, so
    # they must be excluded (Qdrant IsEmpty alone does not exclude "").
    missing_vec = _count(
        storage,
        must_not=[
            _STUB,
            models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract")),
            _EMPTY_ABSTRACT,
            models.HasVectorCondition(has_vector=STRUCTURED_VECTOR_NAME),
        ],
    )
    return {
        "passed": missing_vec == 0,
        "metadata": {"embeddable_missing_vector": missing_vec},
    }


def graph_metrics_stored(storage: QdrantStorage | None = None) -> dict:
    """Papers with a pagerank payload (graph metrics were stored)."""
    storage = storage or QdrantStorage()
    with_pr = _count(
        storage,
        must_not=[models.IsNullCondition(is_null=models.PayloadField(key="pagerank"))],
    )
    return {"passed": with_pr > 0, "metadata": {"papers_with_pagerank": with_pr}}


def cluster_coverage(storage: QdrantStorage | None = None) -> dict:
    """Clustered-paper count and noise fraction (cluster_id == -1)."""
    storage = storage or QdrantStorage()
    clustered = _count(
        storage,
        must_not=[models.IsNullCondition(is_null=models.PayloadField(key="cluster_id"))],
    )
    noise = _count(
        storage,
        must=[models.FieldCondition(key="cluster_id", match=models.MatchValue(value=-1))],
    )
    noise_ratio = (noise / clustered) if clustered else 0.0
    return {
        "passed": clustered > 0 and noise_ratio <= MAX_CLUSTER_NOISE_RATIO,
        "metadata": {"clustered": clustered, "noise": noise,
                     "noise_ratio": round(noise_ratio, 4)},
    }


def real_papers_have_titles(storage: QdrantStorage | None = None) -> dict:
    """Non-stub papers with a null/empty title (should be zero)."""
    storage = storage or QdrantStorage()
    missing = _count(
        storage,
        must=[models.IsEmptyCondition(is_empty=models.PayloadField(key="title"))],
        must_not=[_STUB],
    )
    return {"passed": missing == 0, "metadata": {"missing_titles": missing}}


def abstract_labeling_gap(storage: QdrantStorage | None = None) -> dict:
    """Real papers with a non-empty abstract but empty abstract_structure.

    Early-warning signal for the 2026-07-04 labeling gap: P2/P3 promoted
    ~3M real papers into the corpus without running label-abstracts, which
    silently degraded section-vector search (default multi-vector query
    collapses to 1/3 dense signals when section-* vectors are missing).

    WARN (not blocking) — this fires when the labeling backlog exceeds
    MAX_UNLABELED_ABSTRACT_BACKLOG. Fix: run `docs/runbooks/post-bootstrap-catchup.md`
    step 1 (labeling). Reuses reader.count_papers_for_abstract_labeling so
    the filter definition stays in sync with the labeling stage itself.
    """
    storage = storage or QdrantStorage()
    backlog = storage.count_papers_for_abstract_labeling(skip_existing=True)
    return {
        "passed": backlog <= MAX_UNLABELED_ABSTRACT_BACKLOG,
        "metadata": {
            "unlabeled_with_abstract": backlog,
            "threshold": MAX_UNLABELED_ABSTRACT_BACKLOG,
            "fix": "docs/runbooks/post-bootstrap-catchup.md#step-1--labeling-vllm",
        },
    }


def source_not_silently_zero(storage: QdrantStorage | None = None) -> dict:
    """No known source has a zero count in the corpus (a collector broke silently)."""
    storage = storage or QdrantStorage()
    by_source = storage.get_data_quality_stats().get("by_source", {})
    zero = sorted(name for name, n in by_source.items() if n == 0)
    return {
        "passed": len(zero) == 0,
        "metadata": {"sources": len(by_source), "zero_sources": len(zero),
                     "zero_source_names": ", ".join(zero) or "none"},
    }
