"""Search API routes."""

import logging

from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import get_services
from src.api.models.on_demand import (
    ExpandRequest,
    ExpandResponse,
    ExpandedResultItem,
    ExpansionStats,
    ConnectedPaper,
)
from src.api.models.search import (
    PipelineInfo,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SuggestResponse,
    PaperDetailResponse,
    CorpusStatsResponse,
    ResearchRequest,
    ResearchPaperItem,
    ResearchResponse,
    RetrievalOptions,
    TopicTrend,
)
from src.core.search.config import RetrievalConfig
from src.core.search.research import research_topic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["search"])


def _build_retrieval_config(opts: RetrievalOptions | None) -> RetrievalConfig | None:
    """Translate API-level RetrievalOptions into a RetrievalConfig.

    Returns *None* (use default) when no overrides are provided.
    """
    if opts is None:
        return None
    cfg = RetrievalConfig()
    for field_name in (
        "query_intent", "hyde", "rag_fusion", "multi_vector",
        "reranker", "citation_boost", "mmr_diversity",
    ):
        val = getattr(opts, field_name, None)
        if val is not None:
            setattr(cfg, field_name, val)
    return cfg


@router.post("/search", response_model=SearchResponse)
async def search_papers(request: SearchRequest):
    """Hybrid search over the paper corpus."""
    services = get_services()
    search = services.search_service

    filters = request.filters
    cfg = _build_retrieval_config(request.retrieval)

    results = await search.search(
        query=request.query,
        venues=filters.venues if filters else None,
        year_min=filters.year_min if filters else None,
        year_max=filters.year_max if filters else None,
        tiers=filters.tiers if filters else None,
        section=request.section,
        limit=request.limit,
        offset=request.offset,
        config=cfg,
    )

    pipeline_raw = results.get("pipeline")
    pipeline = PipelineInfo(**pipeline_raw) if pipeline_raw else None

    return SearchResponse(
        results=[SearchResultItem(**r) for r in results["results"]],
        total=results["total"],
        query_time_ms=results["query_time_ms"],
        search_mode=results["search_mode"],
        on_demand_available=results["on_demand_available"],
        pipeline=pipeline,
    )


@router.post("/research", response_model=ResearchResponse)
async def research_topic_endpoint(request: ResearchRequest):
    """Research a topic: returns notable papers + trends + summary."""
    services = get_services()
    search = services.search_service
    storage = services.storage

    result = await research_topic(
        query=request.query,
        search_service=search,
        storage=storage,
        limit=request.limit,
        year_min=request.year_min,
        exclude_types=request.exclude_types,
    )

    # Convert trend counts_by_year keys to strings for the Pydantic model
    trends = []
    for t in result.get("trends", []):
        counts_by_year = {str(k): v for k, v in t.get("counts_by_year", {}).items()}
        trends.append(TopicTrend(
            keyword=t["keyword"],
            counts_by_year=counts_by_year,
            growth_rate=t.get("growth_rate", 0.0),
        ))

    return ResearchResponse(
        query=result["query"],
        papers=[ResearchPaperItem(**p) for p in result["papers"]],
        trends=trends,
        summary=result["summary"],
        query_time_ms=result["query_time_ms"],
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


@router.get("/search/suggest", response_model=SuggestResponse)
async def suggest_keywords(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Autocomplete keyword suggestions."""
    services = get_services()
    suggestions = services.suggestor.suggest(q, limit)
    return SuggestResponse(suggestions=suggestions)


@router.get("/paper/{paper_id}", response_model=PaperDetailResponse)
async def get_paper(paper_id: str):
    """Get full paper detail."""
    services = get_services()
    search = services.search_service

    paper = await search.get_paper(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    return PaperDetailResponse(**paper)


@router.get("/paper/{paper_id}/similar")
async def get_similar_papers(paper_id: str, edge_type: str | None = None):
    """Get precomputed similar papers for a given paper."""
    services = get_services()
    storage = services.storage

    try:
        points = storage.client.retrieve(
            collection_name=storage.collection_name,
            ids=[paper_id],
            with_payload=["title", "similar_papers"],
        )
        if not points:
            raise HTTPException(status_code=404, detail="Paper not found")

        similar = points[0].payload.get("similar_papers", {})
        title = points[0].payload.get("title", "")

        if edge_type and edge_type in similar:
            similar = {edge_type: similar[edge_type]}
        elif edge_type:
            similar = {}

        return {
            "paper_id": paper_id,
            "title": title,
            "similar_papers": similar,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
