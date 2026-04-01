"""Research topic workflow: combines search + notable ranking + trends.

Orchestrates hybrid search, notable-paper scoring, and keyword trend
extraction into a single research assistant response.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from datetime import datetime

from src.core.analytics.notable import TIER_BOOST, _recency_boost, _tier_boost
from src.core.search.config import RetrievalConfig
from src.core.search.service import SearchService
from src.core.storage.base import QdrantStorage

logger = logging.getLogger(__name__)

CURRENT_YEAR = datetime.now().year


async def research_topic(
    query: str,
    search_service: SearchService,
    storage: QdrantStorage,
    limit: int = 20,
    year_min: int | None = None,
    config: RetrievalConfig | None = None,
) -> dict:
    """Research a topic: find notable papers + extract trends.

    Runs hybrid search with over-fetching, computes a combined
    relevance x notability score for re-ranking, extracts keyword
    trends from the result set, and summarizes the research landscape.

    Args:
        query: Natural language research topic or question.
        search_service: Initialized SearchService instance.
        storage: QdrantStorage instance.
        limit: Number of top papers to return (after re-ranking).
        year_min: Optional minimum publication year filter.

    Returns:
        Dict with keys: query, papers, trends, summary, query_time_ms.
    """
    start = time.time()

    # ------------------------------------------------------------------
    # 1. Search -- over-fetch for re-ranking
    # ------------------------------------------------------------------
    # Use quality config for research queries unless caller overrides
    cfg = config or RetrievalConfig.quality()
    search_results = await search_service.search(
        query=query,
        year_min=year_min,
        limit=50,
        config=cfg,
    )

    items = search_results.get("results", [])

    if not items:
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "query": query,
            "papers": [],
            "trends": [],
            "summary": {
                "total_found": 0,
                "year_range": [],
                "top_venues": [],
                "top_authors": [],
            },
            "query_time_ms": elapsed_ms,
        }

    # ------------------------------------------------------------------
    # 2. Score -- compute relevance, notable, and combined scores
    # ------------------------------------------------------------------
    # Normalize search scores to 0-1
    max_search_score = max(item.get("score", 0.0) for item in items) or 1.0

    # Collect raw citation and pagerank values for normalization
    max_citations = max(item.get("citation_count", 0) for item in items) or 1
    max_pagerank = max(item.get("pagerank", 0.0) or 0.0 for item in items) or 1.0

    scored_papers = []
    for item in items:
        relevance_score = item.get("score", 0.0) / max_search_score

        citation_count = item.get("citation_count", 0)
        pagerank = item.get("pagerank", 0.0) or 0.0
        year = item.get("year")
        tier = item.get("tier")

        norm_citations = citation_count / max_citations
        norm_pagerank = pagerank / max_pagerank
        recency = _recency_boost(year)
        tier_b = _tier_boost(tier)

        notable_score = (
            0.3 * norm_citations
            + 0.3 * norm_pagerank
            + 0.2 * recency
            + 0.2 * tier_b
        )

        combined_score = 0.6 * relevance_score + 0.4 * notable_score

        scored_papers.append({
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "authors": item.get("authors", []),
            "venue": item.get("venue"),
            "year": year,
            "tier": tier,
            "abstract": item.get("abstract"),
            "citation_count": citation_count,
            "pagerank": item.get("pagerank"),
            "keywords": item.get("keywords", []),
            "code_url": item.get("code_url"),
            "pdf_url": item.get("pdf_url"),
            "relevance_score": round(relevance_score, 4),
            "notable_score": round(notable_score, 4),
            "combined_score": round(combined_score, 4),
        })

    # ------------------------------------------------------------------
    # 3. Re-rank by combined_score, take top `limit`
    # ------------------------------------------------------------------
    scored_papers.sort(key=lambda p: p["combined_score"], reverse=True)
    top_papers = scored_papers[:limit]

    # ------------------------------------------------------------------
    # 4. Extract trends -- keyword counts by year from result set
    # ------------------------------------------------------------------
    keyword_year_counts: dict[str, dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for paper in scored_papers:
        year = paper.get("year")
        if not year:
            continue
        for kw in paper.get("keywords", []):
            if isinstance(kw, str) and kw.strip():
                keyword_year_counts[kw.strip().lower()][year] += 1

    recent_years = {CURRENT_YEAR, CURRENT_YEAR - 1}
    older_years = {CURRENT_YEAR - 2, CURRENT_YEAR - 3}

    trends = []
    for keyword, yearly_counts in keyword_year_counts.items():
        total_count = sum(yearly_counts.values())
        if total_count < 2:
            continue

        count_recent = sum(
            cnt for yr, cnt in yearly_counts.items() if yr in recent_years
        )
        count_older = sum(
            cnt for yr, cnt in yearly_counts.items() if yr in older_years
        )

        if count_older > 0:
            growth_rate = count_recent / count_older
        elif count_recent > 0:
            growth_rate = float("inf")
        else:
            growth_rate = 0.0

        trends.append({
            "keyword": keyword,
            "counts_by_year": dict(sorted(yearly_counts.items())),
            "growth_rate": growth_rate if growth_rate != float("inf") else 99.0,
        })

    trends.sort(key=lambda t: t["growth_rate"], reverse=True)
    trends = trends[:20]

    # ------------------------------------------------------------------
    # 5. Summarize -- top venues, top authors, year range
    # ------------------------------------------------------------------
    venue_counter: Counter[str] = Counter()
    author_counter: Counter[str] = Counter()
    years: list[int] = []

    for paper in top_papers:
        venue = paper.get("venue")
        if venue:
            venue_counter[venue] += 1
        for author in paper.get("authors", []):
            if isinstance(author, str) and author.strip():
                author_counter[author.strip()] += 1
        year = paper.get("year")
        if year:
            years.append(year)

    year_range = [min(years), max(years)] if years else []
    top_venues = [
        {"venue": v, "count": c}
        for v, c in venue_counter.most_common(10)
    ]
    top_authors = [
        {"author": a, "count": c}
        for a, c in author_counter.most_common(10)
    ]

    elapsed_ms = int((time.time() - start) * 1000)

    return {
        "query": query,
        "papers": top_papers,
        "trends": trends,
        "summary": {
            "total_found": search_results.get("total", len(items)),
            "year_range": year_range,
            "top_venues": top_venues,
            "top_authors": top_authors,
        },
        "query_time_ms": elapsed_ms,
    }
