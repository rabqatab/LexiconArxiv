"""Request and response models for on-demand search expansion."""

from pydantic import BaseModel, Field


class ExpandRequest(BaseModel):
    """On-demand expansion request."""

    query: str = Field(..., min_length=1, max_length=500)
    sources: str = Field(default="both", pattern="^(arxiv|openalex|both)$")
    limit: int = Field(default=20, ge=1, le=50)


class ConnectedPaper(BaseModel):
    """A core paper connected to an expanded result."""

    id: str
    title: str
    relation: str  # "cites" or "cited_by"


class ExpandedResultItem(BaseModel):
    """A single result from on-demand expansion."""

    title: str
    authors: list[str] = Field(default_factory=list)
    source: str  # "arxiv" or "openalex"
    arxiv_id: str | None = None
    doi: str | None = None
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    connection: str  # "core", "connected", "external"
    connected_papers: list[ConnectedPaper] = Field(default_factory=list)


class ExpansionStats(BaseModel):
    """Stats about the expansion operation."""

    arxiv_fetched: int = 0
    openalex_fetched: int = 0
    deduplicated: int = 0
    connected: int = 0
    external: int = 0


class ExpandResponse(BaseModel):
    """On-demand expansion response."""

    expanded_results: list[ExpandedResultItem]
    expansion_stats: ExpansionStats
    query_time_ms: int
    cached: bool = False
