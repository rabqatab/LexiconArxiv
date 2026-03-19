"""Notable paper scoring for LexiconArxiv.

Computes a composite notable_score for each paper based on citation count,
pagerank, recency, and venue tier. Papers are scrolled from Qdrant with
optional filters and returned sorted by score descending.
"""

from __future__ import annotations

import logging
from datetime import datetime

from qdrant_client.http import models

from src.core.storage.base import QdrantStorage

logger = logging.getLogger(__name__)

# Tier boost mapping: tier value -> boost score
TIER_BOOST: dict[int | None, float] = {
    0: 1.0,
    1: 0.7,
    2: 0.4,
    None: 0.3,
}

CURRENT_YEAR = datetime.now().year
RECENCY_BASE_YEAR = 2019


def _recency_boost(year: int | None) -> float:
    """Compute recency boost for a paper year, clamped to [0, 1]."""
    if year is None:
        return 0.0
    raw = (year - RECENCY_BASE_YEAR) / (CURRENT_YEAR - RECENCY_BASE_YEAR)
    return max(0.0, min(1.0, raw))


def _tier_boost(tier: int | None) -> float:
    """Look up the tier boost value."""
    return TIER_BOOST.get(tier, TIER_BOOST[None])


def get_notable_papers(
    storage: QdrantStorage,
    limit: int = 50,
    year_min: int | None = None,
    year_max: int | None = None,
    tiers: list[int] | None = None,
    weights: tuple[float, float, float, float] = (0.3, 0.3, 0.2, 0.2),
) -> list[dict]:
    """Score and rank papers by notability.

    Scrolls through non-stub papers in Qdrant, computes a composite
    notable_score for each, and returns the top N papers sorted by score.

    The formula is:
        notable_score = w1 * norm(citation_count)
                      + w2 * norm(pagerank)
                      + w3 * recency_boost(year)
                      + w4 * tier_boost(tier)

    Where norm(x) = x / max(x) across all papers in the result set.

    Args:
        storage: QdrantStorage instance.
        limit: Number of top papers to return.
        year_min: Optional minimum year filter (inclusive).
        year_max: Optional maximum year filter (inclusive).
        tiers: Optional list of tier values to include.
        weights: Tuple of (w1, w2, w3, w4) weights for the four components.

    Returns:
        List of dicts with paper payload and notable_score, sorted descending.
    """
    w1, w2, w3, w4 = weights

    # Build Qdrant filter
    must_not_conditions: list = [
        models.FieldCondition(
            key="is_stub",
            match=models.MatchValue(value=True),
        ),
    ]

    must_conditions: list = []

    if year_min is not None:
        must_conditions.append(
            models.FieldCondition(
                key="year",
                range=models.Range(gte=year_min),
            )
        )
    if year_max is not None:
        must_conditions.append(
            models.FieldCondition(
                key="year",
                range=models.Range(lte=year_max),
            )
        )
    if tiers is not None:
        must_conditions.append(
            models.FieldCondition(
                key="tier",
                match=models.MatchAny(any=tiers),
            )
        )

    scroll_filter = models.Filter(
        must=must_conditions if must_conditions else None,
        must_not=must_not_conditions,
    )

    # Scroll all matching papers
    papers_raw: list[dict] = []
    offset = None

    while True:
        results, offset = storage.client.scroll(
            collection_name=storage.collection_name,
            scroll_filter=scroll_filter,
            limit=1000,
            offset=offset,
            with_payload=[
                "title", "citation_count", "pagerank", "year", "tier",
                "venue", "doi", "authors",
            ],
        )

        for point in results:
            payload = point.payload or {}
            papers_raw.append({
                "point_id": str(point.id),
                "title": payload.get("title"),
                "citation_count": payload.get("citation_count") or 0,
                "pagerank": payload.get("pagerank") or 0.0,
                "year": payload.get("year"),
                "tier": payload.get("tier"),
                "venue": payload.get("venue"),
                "doi": payload.get("doi"),
                "authors": payload.get("authors"),
            })

        if offset is None:
            break

    if not papers_raw:
        return []

    # Compute max values for normalization
    max_citations = max(p["citation_count"] for p in papers_raw) or 1
    max_pagerank = max(p["pagerank"] for p in papers_raw) or 1.0

    # Score each paper
    for paper in papers_raw:
        norm_citations = paper["citation_count"] / max_citations
        norm_pagerank = paper["pagerank"] / max_pagerank
        recency = _recency_boost(paper["year"])
        tier = _tier_boost(paper["tier"])

        paper["notable_score"] = (
            w1 * norm_citations
            + w2 * norm_pagerank
            + w3 * recency
            + w4 * tier
        )

    # Sort by score descending and return top N
    papers_raw.sort(key=lambda p: p["notable_score"], reverse=True)
    return papers_raw[:limit]
