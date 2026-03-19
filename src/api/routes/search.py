"""Search API routes."""

import logging

from fastapi import APIRouter, HTTPException

from src.api.dependencies import get_services
from src.api.models.on_demand import (
    ExpandRequest,
    ExpandResponse,
    ExpandedResultItem,
    ExpansionStats,
    ConnectedPaper,
)
from src.api.models.search import (
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    PaperDetailResponse,
    CorpusStatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search_papers(request: SearchRequest):
    """Hybrid search over the paper corpus."""
    services = get_services()
    search = services.search_service

    filters = request.filters
    results = await search.search(
        query=request.query,
        venues=filters.venues if filters else None,
        year_min=filters.year_min if filters else None,
        year_max=filters.year_max if filters else None,
        tiers=filters.tiers if filters else None,
        limit=request.limit,
        offset=request.offset,
    )

    return SearchResponse(
        results=[SearchResultItem(**r) for r in results["results"]],
        total=results["total"],
        query_time_ms=results["query_time_ms"],
        search_mode=results["search_mode"],
        on_demand_available=results["on_demand_available"],
    )


@router.post("/search/expand", response_model=ExpandResponse)
async def expand_search(request: ExpandRequest):
    """Expand search to arXiv and OpenAlex."""
    services = get_services()
    search = services.search_service

    results = await search.expand_search(
        query=request.query,
        sources=request.sources,
        limit=request.limit,
    )

    if "error" in results:
        raise HTTPException(status_code=503, detail=results["error"])

    return ExpandResponse(
        expanded_results=[
            ExpandedResultItem(
                **{k: v for k, v in r.items() if k != "connected_papers" and k != "pdf_url"},
                connected_papers=[ConnectedPaper(**cp) for cp in r.get("connected_papers", [])],
            )
            for r in results["expanded_results"]
        ],
        expansion_stats=ExpansionStats(**results["expansion_stats"]),
        query_time_ms=results["query_time_ms"],
        cached=results.get("cached", False),
    )


@router.get("/paper/{paper_id}", response_model=PaperDetailResponse)
async def get_paper(paper_id: str):
    """Get full paper detail."""
    services = get_services()
    search = services.search_service

    paper = await search.get_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    return PaperDetailResponse(**paper)


@router.get("/stats", response_model=CorpusStatsResponse)
async def get_corpus_stats():
    """Get corpus statistics."""
    services = get_services()
    storage = services.storage

    try:
        from qdrant_client import models
        total = storage.client.count(storage.collection_name).count
        stubs = storage.client.count(
            storage.collection_name,
            count_filter=models.Filter(must=[
                models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))
            ]),
        ).count
        with_abstracts = storage.client.count(
            storage.collection_name,
            count_filter=models.Filter(
                must_not=[
                    models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
                    models.IsNullCondition(is_null=models.PayloadField(key="abstract")),
                    models.FieldCondition(key="abstract", match=models.MatchValue(value="")),
                ],
            ),
        ).count
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get corpus stats")

    return CorpusStatsResponse(
        total_papers=total - stubs,
        total_stubs=stubs,
        papers_with_abstracts=with_abstracts,
        papers_with_keywords=0,
        papers_with_vectors=0,
    )
