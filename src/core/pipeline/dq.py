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

_STUB = models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))


def _count(storage, must=None, must_not=None) -> int:
    # exact=False: approximate count. exact=True times out on the multi-million
    # point collection (esp. under concurrent writes), and warn-only coverage
    # checks tolerate approximate counts. Phase 3b ERROR gating may revisit this.
    return storage.client.count(
        collection_name=storage.collection_name,
        count_filter=models.Filter(must=must, must_not=must_not),
        exact=False,
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
    missing = _count(
        storage,
        must=[models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract"))],
        must_not=[_STUB],
    )
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
    # non-stub, abstract non-empty, but missing the structured-abstract vector
    missing_vec = _count(
        storage,
        must_not=[
            _STUB,
            models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract")),
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
