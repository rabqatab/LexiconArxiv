"""Trends API routes."""

import logging

from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import get_services
from src.api.models.trends import (
    NotablePaperItem,
    NotableResponse,
    KeywordTrendItem,
    KeywordTrendPoint,
    KeywordTrendsResponse,
    RisingKeywordItem,
    RisingResponse,
    TopicCluster,
    TopicsResponse,
    TopicPapersResponse,
    TrendMapPoint,
    TrendMapResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trends", tags=["trends"])


@router.get("/notable", response_model=NotableResponse)
async def get_notable_papers(
    limit: int = Query(default=50, ge=1, le=200),
    year_min: int | None = None,
    year_max: int | None = None,
    tiers: str | None = Query(default=None, description="Comma-separated tier IDs, e.g. 0,1"),
):
    """Get top papers ranked by notable score."""
    from src.core.analytics.notable import get_notable_papers as _get_notable

    services = get_services()
    tier_list = [int(t) for t in tiers.split(",")] if tiers else None

    papers = _get_notable(
        storage=services.storage,
        limit=limit,
        year_min=year_min,
        year_max=year_max,
        tiers=tier_list,
    )

    return NotableResponse(
        papers=[
            NotablePaperItem(
                id=p["point_id"],
                title=p.get("title", ""),
                authors=p.get("authors") or [],
                venue=p.get("venue"),
                year=p.get("year"),
                tier=p.get("tier"),
                citation_count=p.get("citation_count", 0),
                pagerank=p.get("pagerank"),
                notable_score=p.get("notable_score", 0.0),
            )
            for p in papers
        ],
        total=len(papers),
    )


@router.get("/keywords", response_model=KeywordTrendsResponse)
async def get_keyword_trends(
    category: str | None = Query(default=None, description="Filter by category (task, method, model, domain, dataset)"),
    min_count: int = Query(default=5, ge=1),
):
    """Get keyword frequency time-series."""
    from src.core.analytics.keyword_trends import compute_keyword_trends

    services = get_services()
    trends = compute_keyword_trends(
        storage=services.storage,
        category=category,
        min_count=min_count,
    )

    categories = sorted(set(t["category"] for t in trends))

    return KeywordTrendsResponse(
        trends=[
            KeywordTrendItem(
                keyword=t["keyword"],
                category=t["category"],
                counts=[KeywordTrendPoint(year=y, count=c) for y, c in sorted(t["yearly_counts"].items())],
                growth_rate=t["growth_rate"],
                total_papers=t["total_count"],
            )
            for t in trends
        ],
        categories=categories,
    )


@router.get("/rising", response_model=RisingResponse)
async def get_rising_keywords(
    top_k: int = Query(default=20, ge=1, le=100),
    category: str | None = None,
    min_count: int = Query(default=10, ge=1),
):
    """Get fastest-growing keywords."""
    from src.core.analytics.keyword_trends import get_rising_keywords as _get_rising

    services = get_services()
    rising = _get_rising(
        storage=services.storage,
        top_k=top_k,
        category=category,
        min_count=min_count,
    )

    return RisingResponse(
        rising=[
            RisingKeywordItem(
                keyword=r["keyword"],
                category=r["category"],
                growth_rate=r["growth_rate"],
                recent_count=r["count_recent"],
                total_count=r["total_count"],
            )
            for r in rising
        ]
    )


@router.get("/topics", response_model=TopicsResponse)
async def get_topics():
    """Get discovered topic clusters (requires clustering to have been computed)."""
    from qdrant_client import models

    services = get_services()
    storage = services.storage

    # Check if clustering has been done by looking for cluster_id field
    try:
        sample = storage.client.scroll(
            storage.collection_name,
            scroll_filter=models.Filter(must_not=[
                models.IsNullCondition(is_null=models.PayloadField(key="cluster_id")),
            ]),
            limit=1,
            with_payload=["cluster_id"],
        )
        if not sample[0]:
            raise HTTPException(status_code=404, detail="No clustering data. Run compute-topics first.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="No clustering data available")

    # Get all unique cluster IDs and counts
    # Scroll and aggregate (for moderate-sized collections this is fast)
    cluster_counts = {}
    cluster_keywords = {}
    offset = None

    while True:
        results, next_offset = storage.client.scroll(
            storage.collection_name,
            scroll_filter=models.Filter(must_not=[
                models.IsNullCondition(is_null=models.PayloadField(key="cluster_id")),
            ]),
            limit=1000,
            offset=offset,
            with_payload=["cluster_id", "keywords", "year"],
        )
        if not results:
            break
        for point in results:
            cid = point.payload.get("cluster_id")
            if cid is None:
                continue
            cluster_counts[cid] = cluster_counts.get(cid, 0) + 1
            if cid not in cluster_keywords:
                cluster_keywords[cid] = []
            cluster_keywords[cid].extend(point.payload.get("keywords", [])[:5])
        if next_offset is None:
            break
        offset = next_offset

    noise = cluster_counts.pop(-1, 0)
    topics = []
    for cid in sorted(cluster_counts.keys()):
        from collections import Counter
        kw_counter = Counter(cluster_keywords.get(cid, []))
        top_kw = [kw for kw, _ in kw_counter.most_common(5)]
        label = ", ".join(top_kw[:3]) if top_kw else f"Cluster {cid}"
        topics.append(TopicCluster(
            cluster_id=cid,
            label=label,
            size=cluster_counts[cid],
            top_keywords=top_kw,
        ))

    total = sum(cluster_counts.values())

    return TopicsResponse(topics=topics, total_papers=total, noise_papers=noise)


@router.get("/map", response_model=TrendMapResponse)
async def get_trend_map(
    limit: int = Query(default=5000, ge=100, le=50000),
):
    """Get 2D UMAP coordinates for topic map visualization."""
    from qdrant_client import models

    services = get_services()
    storage = services.storage

    points_data = []
    offset = None

    while len(points_data) < limit:
        results, next_offset = storage.client.scroll(
            storage.collection_name,
            scroll_filter=models.Filter(must_not=[
                models.IsNullCondition(is_null=models.PayloadField(key="umap_x")),
            ]),
            limit=min(1000, limit - len(points_data)),
            offset=offset,
            with_payload=["title", "umap_x", "umap_y", "cluster_id", "year", "venue"],
        )
        if not results:
            break
        for point in results:
            p = point.payload or {}
            points_data.append(TrendMapPoint(
                id=str(point.id),
                title=p.get("title", ""),
                x=p.get("umap_x", 0),
                y=p.get("umap_y", 0),
                cluster_id=p.get("cluster_id", -1),
                year=p.get("year"),
                venue=p.get("venue"),
            ))
        if next_offset is None:
            break
        offset = next_offset

    # Also return cluster summaries
    # (reuse topics endpoint logic or return empty if no clusters)
    return TrendMapResponse(points=points_data, clusters=[])
