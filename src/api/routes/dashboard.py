"""Data health monitoring dashboard API routes."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from src.api.dependencies import get_services

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dashboard"])

_cache = {"data": None, "timestamp": 0}
CACHE_TTL = 300  # 5 minutes

PIPELINE_STATUS_FILE = Path("data/core/pipeline_status.json")


def _read_pipeline_status() -> dict:
    """Read the pipeline status file written by run_incremental_pipeline.sh."""
    try:
        if PIPELINE_STATUS_FILE.exists():
            data = json.loads(PIPELINE_STATUS_FILE.read_text())
            return {
                "status": data.get("status", "unknown"),
                "finished_at": data.get("finished_at"),
                "duration_seconds": data.get("duration_seconds"),
            }
    except Exception as e:
        logger.warning(f"Failed to read pipeline status: {e}")
    return {"status": "unknown", "finished_at": None, "duration_seconds": None}


@router.get("/dashboard")
async def get_dashboard(refresh: bool = False):
    """Get comprehensive data health metrics."""
    now = time.time()
    if not refresh and _cache["data"] and (now - _cache["timestamp"]) < CACHE_TTL:
        return _cache["data"]

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

    # Data validation warnings
    warnings = []

    current_year = datetime.now().year
    for year in [current_year, current_year - 1]:
        year_count = year_counts.get(str(year), 0)
        if year_count == 0:
            warnings.append(f"No papers found for year {year}")
        elif year_count < 1000:
            warnings.append(f"Only {year_count} papers for {year} (expected 10K+)")

    if core > 0:
        if with_abstract < core * 0.9:
            warnings.append(f"Abstract coverage below 90% ({pct(with_abstract, core)}%)")
        if with_keywords < core * 0.7:
            warnings.append(f"Keyword coverage below 70% ({pct(with_keywords, core)}%)")
        if with_dense_vec < core * 0.5:
            warnings.append(f"Embedding coverage below 50% ({pct(with_dense_vec, core)}%)")

    result = {
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
        "pipeline": _read_pipeline_status(),
        "warnings": warnings,
    }

    _cache["data"] = result
    _cache["timestamp"] = time.time()

    return result


_gaps_cache = {"data": None, "timestamp": 0}


@router.get("/corpus-gaps")
async def get_corpus_gaps(limit: int = 100, refresh: bool = False):
    """Corpus gaps: the most-cited papers the corpus references but doesn't hold.

    Returns top enriched stubs by internal citation count plus a venue tally
    over that set. Cheap (server-side order_by on the cited_by_count_internal
    index); cached 5 min.
    """
    now = time.time()
    if not refresh and _gaps_cache["data"] and (now - _gaps_cache["timestamp"]) < CACHE_TTL:
        return _gaps_cache["data"]
    storage = get_services().storage
    data = storage.get_corpus_gaps(limit=limit)
    _gaps_cache["data"] = data
    _gaps_cache["timestamp"] = time.time()
    return data
