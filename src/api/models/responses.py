"""Pydantic response models for the Graph API.

These models define D3.js-compatible JSON structures for graph visualization.
"""

from pydantic import BaseModel, Field


class NodeData(BaseModel):
    """Node data for D3.js visualization."""

    id: str = Field(..., description="Qdrant point ID")
    title: str = Field("", description="Paper title")
    year: int | None = Field(None, description="Publication year")
    venue: str = Field("", description="Publication venue")
    authors: list[str] = Field(default_factory=list, description="Author names")
    citation_count: int = Field(0, description="Global citation count")
    doi: str | None = Field(None, description="Paper DOI")
    is_center: bool = Field(False, description="Whether this is the center paper of the subgraph")


class LinkData(BaseModel):
    """Edge data for D3.js visualization."""

    source: str = Field(..., description="Citing paper ID")
    target: str = Field(..., description="Cited paper ID")


class SubgraphStats(BaseModel):
    """Statistics about the subgraph."""

    num_nodes: int = Field(..., description="Number of nodes in subgraph")
    num_edges: int = Field(..., description="Number of edges in subgraph")
    density: float = Field(..., description="Graph density (edges / possible edges)")
    center_paper_id: str = Field(..., description="The center paper ID")
    hops: int = Field(..., description="Number of hops from center")
    direction: str = Field(..., description="Direction of traversal (both/citing/cited)")


class SubgraphResponse(BaseModel):
    """Response for subgraph endpoint - D3.js node-link format."""

    nodes: list[NodeData] = Field(..., description="Graph nodes")
    links: list[LinkData] = Field(..., description="Graph edges")
    stats: SubgraphStats = Field(..., description="Subgraph statistics")


class PaperResponse(BaseModel):
    """Full paper details response."""

    id: str = Field(..., description="Qdrant point ID")
    source_id: str | None = Field(None, description="Original source identifier")
    openalex_id: str | None = Field(None, description="OpenAlex work ID")
    title: str = Field("", description="Paper title")
    abstract: str = Field("", description="Paper abstract")
    venue: str = Field("", description="Publication venue")
    venue_type: str | None = Field(None, description="Type of venue")
    tier: int | None = Field(None, description="Venue tier")
    is_core: bool = Field(False, description="Whether in core corpus")
    year: int | None = Field(None, description="Publication year")
    doi: str | None = Field(None, description="Paper DOI")
    citation_count: int = Field(0, description="Global citation count")
    authors: list[str] = Field(default_factory=list, description="Author names")
    categories: list[str] = Field(default_factory=list, description="Paper categories")
    pdf_url: str | None = Field(None, description="PDF URL")
    keywords: list[str] = Field(default_factory=list, description="Extracted keywords")
    # Citation graph fields
    resolved_references: list[str] = Field(
        default_factory=list, description="Qdrant IDs of cited papers"
    )
    cited_by: list[str] = Field(default_factory=list, description="Qdrant IDs of citing papers")
    in_corpus_citation_count: int = Field(
        0, description="Number of corpus papers citing this paper"
    )
    reference_count: int = Field(0, description="Number of resolved references")


class GraphStatsResponse(BaseModel):
    """Overall graph statistics response."""

    total_papers: int = Field(..., description="Total papers in corpus")
    total_real_papers: int = Field(..., description="Non-stub papers")
    total_stub_papers: int = Field(..., description="External reference stubs")
    papers_with_refs: int = Field(..., description="Papers with resolved references")
    papers_with_resolved_refs: int = Field(..., description="Papers with resolved_references field")
    total_raw_refs: int = Field(..., description="Total raw reference count")
    total_resolved_refs: int = Field(..., description="Total resolved edges")
    resolution_coverage: float = Field(..., description="Percentage of refs resolved")
    papers_with_graph_metrics: int = Field(..., description="Papers with PageRank computed")
    # Index stats (if available)
    index_num_papers: int | None = Field(None, description="Papers in citation index")
    index_num_edges: int | None = Field(None, description="Edges in citation index")
    index_memory_mb: float | None = Field(None, description="Index memory usage in MB")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service status")
    index_built: bool = Field(..., description="Whether citation index is built")
    storage_connected: bool = Field(..., description="Whether Qdrant is accessible")
