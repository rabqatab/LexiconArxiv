"""Keyword trend analysis for LexiconArxiv.

Scrolls papers with keywords_structured payloads to compute per-keyword
frequency time-series and growth rates, enabling identification of rising
research topics.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from qdrant_client.http import models

from src.core.storage.base import QdrantStorage

logger = logging.getLogger(__name__)

CURRENT_YEAR = datetime.now().year

# keywords_structured categories
KEYWORD_CATEGORIES = [
    "task", "method", "model", "domain", "dataset",
    "contribution_type", "modality",
]


def compute_keyword_trends(
    storage: QdrantStorage,
    category: str | None = None,
    min_count: int = 5,
) -> list[dict]:
    """Compute keyword frequency time-series and growth rates.

    Scrolls papers with keywords_structured, counts each keyword per year,
    and computes growth_rate = count_recent / count_older where recent is
    the last 2 years and older is the 2 years before that.

    Args:
        storage: QdrantStorage instance.
        category: Optional category to restrict to (e.g. "task", "method").
                  None means aggregate across all categories.
        min_count: Minimum total paper count for a keyword to be included.

    Returns:
        List of dicts with keyword, category, yearly_counts, total_count,
        count_recent, count_older, and growth_rate, sorted by growth_rate
        descending.
    """
    # Scroll all non-stub papers with keywords_structured
    must_not_conditions: list = [
        models.FieldCondition(
            key="is_stub",
            match=models.MatchValue(value=True),
        ),
    ]

    scroll_filter = models.Filter(
        must_not=must_not_conditions,
    )

    # keyword -> year -> count
    keyword_year_counts: dict[tuple[str, str], dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    offset = None
    while True:
        results, offset = storage.client.scroll(
            collection_name=storage.collection_name,
            scroll_filter=scroll_filter,
            limit=1000,
            offset=offset,
            with_payload=["year", "keywords_structured"],
        )

        for point in results:
            payload = point.payload or {}
            year = payload.get("year")
            ks = payload.get("keywords_structured")
            if not year or not ks or not isinstance(ks, dict):
                continue

            categories_to_scan = [category] if category else KEYWORD_CATEGORIES
            for cat in categories_to_scan:
                keywords = ks.get(cat, [])
                if not isinstance(keywords, list):
                    continue
                for kw in keywords:
                    if isinstance(kw, str) and kw.strip():
                        keyword_year_counts[(kw.strip().lower(), cat)][year] += 1

        if offset is None:
            break

    # Define recent and older year ranges
    recent_years = {CURRENT_YEAR, CURRENT_YEAR - 1}
    older_years = {CURRENT_YEAR - 2, CURRENT_YEAR - 3}

    results_list: list[dict] = []
    for (keyword, cat), yearly_counts in keyword_year_counts.items():
        total_count = sum(yearly_counts.values())
        if total_count < min_count:
            continue

        count_recent = sum(
            cnt for yr, cnt in yearly_counts.items() if yr in recent_years
        )
        count_older = sum(
            cnt for yr, cnt in yearly_counts.items() if yr in older_years
        )

        # Growth rate: recent / older (avoid division by zero)
        if count_older > 0:
            growth_rate = count_recent / count_older
        elif count_recent > 0:
            growth_rate = float("inf")
        else:
            growth_rate = 0.0

        results_list.append({
            "keyword": keyword,
            "category": cat,
            "yearly_counts": dict(sorted(yearly_counts.items())),
            "total_count": total_count,
            "count_recent": count_recent,
            "count_older": count_older,
            "growth_rate": growth_rate,
        })

    results_list.sort(key=lambda r: r["growth_rate"], reverse=True)
    return results_list


def get_rising_keywords(
    storage: QdrantStorage,
    top_k: int = 20,
    category: str | None = None,
    min_count: int = 10,
) -> list[dict]:
    """Get top-K fastest growing keywords.

    Args:
        storage: QdrantStorage instance.
        top_k: Number of top keywords to return.
        category: Optional category to restrict to.
        min_count: Minimum total paper count for a keyword to be included.

    Returns:
        List of top-K keyword dicts sorted by growth_rate descending.
    """
    all_trends = compute_keyword_trends(
        storage=storage,
        category=category,
        min_count=min_count,
    )
    return all_trends[:top_k]
