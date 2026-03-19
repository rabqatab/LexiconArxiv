"""Data health monitoring dashboard API routes."""

import logging

from fastapi import APIRouter

from src.api.dependencies import get_services

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
async def get_dashboard():
    """Get comprehensive data health metrics."""
    storage = get_services().storage
    client = storage.client
    collection = storage.collection_name

    from qdrant_client import models

    # Helper for safe count
    def count(filter_obj=None):
        try:
            return client.count(collection, count_filter=filter_obj).count
        except Exception:
            return -1

    total = count()

    # Core vs stubs
    stubs = count(models.Filter(must=[
        models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))
    ]))
    core = total - stubs

    # Enrichment rates (non-stub papers)
    non_stub_filter = models.Filter(must_not=[
        models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))
    ])

    with_abstract = count(models.Filter(
        must_not=[
            models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
            models.IsNullCondition(is_null=models.PayloadField(key="abstract")),
            models.FieldCondition(key="abstract", match=models.MatchValue(value="")),
        ]
    ))

    with_doi = count(models.Filter(
        must_not=[
            models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
            models.IsNullCondition(is_null=models.PayloadField(key="doi")),
        ]
    ))

    with_refs = count(models.Filter(
        must_not=[
            models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
            models.IsEmptyCondition(is_empty=models.PayloadField(key="resolved_references")),
        ]
    ))

    with_keywords = count(models.Filter(
        must_not=[
            models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
            models.IsEmptyCondition(is_empty=models.PayloadField(key="keywords")),
        ]
    ))

    with_abstract_structure = count(models.Filter(
        must_not=[
            models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
            models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract_structure")),
        ]
    ))

    with_dense_vec = count(models.Filter(
        must=[models.HasVectorCondition(has_vector="structured-abstract")],
        must_not=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))],
    ))

    with_similarity = count(models.Filter(
        must_not=[
            models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
            models.IsEmptyCondition(is_empty=models.PayloadField(key="similar_papers")),
        ]
    ))

    with_cluster = count(models.Filter(
        must_not=[
            models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
            models.IsNullCondition(is_null=models.PayloadField(key="cluster_id")),
        ]
    ))

    with_cited_by = count(models.Filter(
        must_not=[
            models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
            models.IsEmptyCondition(is_empty=models.PayloadField(key="cited_by")),
        ]
    ))

    # Year distribution (scroll all non-stub papers)
    year_counts = {}
    offset = None
    for _ in range(200):  # Max 200 scroll pages
        results, next_offset = client.scroll(
            collection, limit=1000, offset=offset,
            scroll_filter=non_stub_filter,
            with_payload=["year"],
        )
        if not results:
            break
        for p in results:
            year = (p.payload or {}).get("year")
            if year:
                year_counts[str(year)] = year_counts.get(str(year), 0) + 1
        if next_offset is None:
            break
        offset = next_offset

    def pct(n, total_n):
        return round(n / total_n * 100, 1) if total_n > 0 else 0

    return {
        "overview": {
            "total_points": total,
            "core_papers": core,
            "stub_papers": stubs,
        },
        "enrichment": {
            "abstracts": {"count": with_abstract, "pct": pct(with_abstract, core)},
            "dois": {"count": with_doi, "pct": pct(with_doi, core)},
            "resolved_references": {"count": with_refs, "pct": pct(with_refs, core)},
            "keywords": {"count": with_keywords, "pct": pct(with_keywords, core)},
            "abstract_structure": {"count": with_abstract_structure, "pct": pct(with_abstract_structure, core)},
            "cited_by": {"count": with_cited_by, "pct": pct(with_cited_by, core)},
        },
        "search_readiness": {
            "dense_vectors": {"count": with_dense_vec, "pct": pct(with_dense_vec, core)},
            "similarity_edges": {"count": with_similarity, "pct": pct(with_similarity, core)},
            "clusters": {"count": with_cluster, "pct": pct(with_cluster, core)},
        },
        "year_distribution": dict(sorted(year_counts.items())),
    }
