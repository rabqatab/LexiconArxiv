"""Graph API endpoints for citation graph exploration.

Provides endpoints for:
- Subgraph exploration around papers
- Paper details lookup
- Graph statistics
- Health checks
"""

import logging
from typing import Literal

import networkx as nx
from fastapi import APIRouter, HTTPException, Query

from src.api.dependencies import get_services
from src.api.models.responses import (
    GraphStatsResponse,
    HealthResponse,
    LinkData,
    NodeData,
    PaperResponse,
    SubgraphResponse,
    SubgraphStats,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check API health and service status."""
    services = get_services()
    return HealthResponse(
        status="healthy",
        index_built=services.is_index_built,
        storage_connected=services.is_storage_connected(),
    )


@router.get("/stats", response_model=GraphStatsResponse)
async def get_graph_stats() -> GraphStatsResponse:
    """Get overall citation graph statistics.

    Returns statistics about the full citation graph including:
    - Total papers (real and stub)
    - Reference resolution coverage
    - Citation index metrics
    """
    services = get_services()

    # Get stats from storage
    try:
        stats = services.storage.get_citation_graph_stats()
    except Exception as e:
        logger.error(f"Failed to get citation graph stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve graph statistics")

    # Get counts
    try:
        real_papers = services.storage.count_real_papers()
        stub_papers = services.storage.count_stubs()
    except Exception:
        real_papers = stats.get("total_papers", 0)
        stub_papers = 0

    # Get index stats if available
    index_stats = None
    if services.is_index_built:
        index_stats = services.index.get_stats()

    return GraphStatsResponse(
        total_papers=stats.get("total_papers", 0),
        total_real_papers=real_papers,
        total_stub_papers=stub_papers,
        papers_with_refs=stats.get("papers_with_refs", 0),
        papers_with_resolved_refs=stats.get("papers_with_resolved_refs", 0),
        total_raw_refs=stats.get("total_raw_refs", 0),
        total_resolved_refs=stats.get("total_resolved_refs", 0),
        resolution_coverage=stats.get("resolution_coverage", 0.0),
        papers_with_graph_metrics=stats.get("papers_with_graph_metrics", 0),
        index_num_papers=index_stats.get("num_papers") if index_stats else None,
        index_num_edges=index_stats.get("num_edges") if index_stats else None,
        index_memory_mb=index_stats.get("estimated_memory_mb") if index_stats else None,
    )


@router.get("/paper/{paper_id}", response_model=PaperResponse)
async def get_paper(paper_id: str) -> PaperResponse:
    """Get detailed information about a specific paper.

    Args:
        paper_id: The Qdrant point ID of the paper.

    Returns:
        Full paper details including citation graph fields.
    """
    services = get_services()

    # Get paper from storage
    paper = services.storage.get_paper_by_id(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id}")

    # Calculate in-corpus citation count
    cited_by = paper.get("cited_by", [])
    resolved_refs = paper.get("resolved_references", [])

    return PaperResponse(
        id=paper_id,
        source_id=paper.get("source_id"),
        openalex_id=paper.get("openalex_id"),
        title=paper.get("title", ""),
        abstract=paper.get("abstract", ""),
        venue=paper.get("venue", ""),
        venue_type=paper.get("venue_type"),
        tier=paper.get("tier"),
        is_core=paper.get("is_core", False),
        year=paper.get("year"),
        doi=paper.get("doi"),
        citation_count=paper.get("citation_count", 0),
        authors=paper.get("authors", []),
        categories=paper.get("categories", []),
        pdf_url=paper.get("pdf_url"),
        keywords=paper.get("keywords", []),
        resolved_references=resolved_refs,
        cited_by=cited_by,
        in_corpus_citation_count=len(cited_by),
        reference_count=len(resolved_refs),
    )


@router.get("/subgraph/{paper_id}", response_model=SubgraphResponse)
async def get_subgraph(
    paper_id: str,
    hops: int = Query(default=1, ge=1, le=3, description="Number of hops from center paper"),
    direction: Literal["both", "citing", "cited"] = Query(
        default="both",
        description="Direction to traverse: both, citing (papers that cite), cited (papers cited)",
    ),
) -> SubgraphResponse:
    """Get an N-hop subgraph around a paper.

    Returns a D3.js-compatible node-link graph containing all papers
    within N hops of the specified center paper.

    Args:
        paper_id: The Qdrant point ID of the center paper.
        hops: Number of hops to traverse (1-3). Default 1.
        direction: Edge direction to follow:
            - "both": Follow both incoming and outgoing citations
            - "citing": Only papers that cite the center
            - "cited": Only papers that the center cites

    Returns:
        SubgraphResponse with nodes, links, and statistics.
    """
    services = get_services()

    # Verify paper exists
    paper = services.storage.get_paper_by_id(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id}")

    # Check if index is built
    if not services.is_index_built:
        raise HTTPException(
            status_code=503,
            detail="Citation index not ready. Please wait for server initialization.",
        )

    # Build subgraph using the existing builder
    try:
        G = services.builder.build_subgraph(
            center_paper_id=paper_id,
            hops=hops,
            direction=direction,
            include_metadata=True,
        )
    except Exception as e:
        logger.error(f"Failed to build subgraph: {e}")
        raise HTTPException(status_code=500, detail="Failed to build subgraph")

    # Convert NetworkX graph to D3.js format
    nodes: list[NodeData] = []
    for node_id in G.nodes():
        attrs = G.nodes[node_id]
        nodes.append(
            NodeData(
                id=node_id,
                title=attrs.get("title", ""),
                year=attrs.get("year"),
                venue=attrs.get("venue", ""),
                authors=attrs.get("authors", []),
                citation_count=attrs.get("citation_count", 0),
                doi=attrs.get("doi"),
                is_center=attrs.get("is_center", False),
            )
        )

    links: list[LinkData] = []
    for source, target in G.edges():
        links.append(LinkData(source=source, target=target))

    # Calculate statistics
    num_nodes = G.number_of_nodes()
    num_edges = G.number_of_edges()
    density = nx.density(G) if num_nodes > 1 else 0.0

    stats = SubgraphStats(
        num_nodes=num_nodes,
        num_edges=num_edges,
        density=round(density, 6),
        center_paper_id=paper_id,
        hops=hops,
        direction=direction,
    )

    return SubgraphResponse(nodes=nodes, links=links, stats=stats)
