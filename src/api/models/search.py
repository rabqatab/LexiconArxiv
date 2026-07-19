"""Request and response models for the search API."""

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    """Optional filters for search queries."""

    venues: list[str] | None = Field(None, description="Filter by venue names")
    year_min: int | None = Field(None, description="Minimum publication year")
    year_max: int | None = Field(None, description="Maximum publication year")
    tiers: list[int] | None = Field(None, description="Filter by venue tiers")


class RetrievalOptions(BaseModel):
    """Optional retrieval pipeline configuration.

    Any field left as *None* uses the pipeline default.
    """

    query_intent: bool | None = Field(None, description="Auto-detect target section from query")
    hyde: bool | None = Field(None, description="Generate hypothetical document embedding")
    rag_fusion: bool | None = Field(None, description="Generate multi-query variants")
    multi_vector: bool | None = Field(None, description="Search across multiple dense vectors")
    reranker: bool | None = Field(None, description="Apply cross-encoder reranking")
    citation_boost: bool | None = Field(None, description="Boost results by citations + PageRank")
    mmr_diversity: bool | None = Field(None, description="Apply MMR diversification")


class PipelineInfo(BaseModel):
    """Metadata about which pipeline stages were applied."""

    stages_applied: list[str] = Field(default_factory=list)
    query_analysis: dict | None = None
    vectors_searched: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """Search request body."""

    query: str = Field(..., min_length=1, max_length=500, description="Search query string")
    filters: SearchFilters | None = Field(None, description="Optional search filters")
    section: str | None = Field(None, description="Target a specific paper section (task, method, result, approach, background, domain, contribution). Uses section-specific vector for more precise matching.")
    limit: int = Field(default=20, ge=1, le=100, description="Number of results to return")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    retrieval: RetrievalOptions | None = Field(None, description="Optional retrieval pipeline overrides")


class SearchResultItem(BaseModel):
    """A single search result."""

    id: str = Field(..., description="Qdrant point ID")
    title: str = Field(..., description="Paper title")
    abstract: str | None = Field(None, description="Paper abstract")
    authors: list[str] = Field(default_factory=list, description="Author names")
    venue: str | None = Field(None, description="Publication venue")
    year: int | None = Field(None, description="Publication year")
    tier: int | None = Field(None, description="Venue tier")
    doi: str | None = Field(None, description="Paper DOI")
    citation_count: int = Field(0, description="Global citation count")
    pagerank: float | None = Field(None, description="PageRank score")
    keywords: list[str] = Field(default_factory=list, description="Extracted keywords")
    abstract_structure: dict | None = Field(None, description="Structured abstract sections")
    code_url: str | None = Field(None, description="Code repository URL")
    pdf_url: str | None = Field(None, description="PDF URL")
    score: float = Field(0.0, description="Search relevance score")


class SearchResponse(BaseModel):
    """Search response."""

    results: list[SearchResultItem] = Field(..., description="Search result items")
    total: int = Field(..., description="Total number of matching results")
    query_time_ms: int = Field(..., description="Query execution time in milliseconds")
    search_mode: str = Field(..., description="Search mode used: 'hybrid' or 'bm25_only'")
    on_demand_available: bool = Field(
        False, description="Whether on-demand vector search is available"
    )
    pipeline: PipelineInfo | None = Field(
        None, description="Retrieval pipeline metadata"
    )


class PaperDetailResponse(BaseModel):
    """Full paper detail with citation context."""

    id: str = Field(..., description="Qdrant point ID")
    title: str = Field(..., description="Paper title")
    abstract: str | None = Field(None, description="Paper abstract")
    authors: list[str] = Field(default_factory=list, description="Author names")
    venue: str | None = Field(None, description="Publication venue")
    year: int | None = Field(None, description="Publication year")
    tier: int | None = Field(None, description="Venue tier")
    doi: str | None = Field(None, description="Paper DOI")
    arxiv_id: str | None = Field(None, description="ArXiv identifier")
    citation_count: int = Field(0, description="Global citation count")
    pagerank: float | None = Field(None, description="PageRank score")
    keywords: list[str] = Field(default_factory=list, description="Extracted keywords")
    keywords_structured: dict | None = Field(
        None, description="Structured keyword taxonomy"
    )
    abstract_structure: dict | None = Field(
        None, description="Structured abstract sections"
    )
    code_repositories: list[dict] = Field(
        default_factory=list, description="Code repository metadata"
    )
    code_url: str | None = Field(None, description="Primary code repository URL")
    pdf_url: str | None = Field(None, description="PDF URL")
    is_core: bool = Field(False, description="Whether in core corpus")
    is_stub: bool = Field(False, description="Whether this is an external reference stub")
    reference_count: int = Field(0, description="Number of resolved references")
    cited_by_count: int = Field(0, description="Number of papers citing this paper")


class SuggestResponse(BaseModel):
    """Autocomplete suggestion response."""

    suggestions: list[str] = Field(..., description="Autocomplete suggestions")


class CorpusStatsResponse(BaseModel):
    """Corpus statistics."""

    total_papers: int = Field(..., description="Total papers in corpus")
    total_stubs: int = Field(..., description="Total external reference stubs")
    papers_with_abstracts: int = Field(..., description="Papers with abstracts")
    papers_with_keywords: int = Field(..., description="Papers with extracted keywords")
    papers_with_vectors: int = Field(..., description="Papers with embedding vectors")
    venues: dict[str, int] = Field(
        default_factory=dict, description="Paper count per venue"
    )


# ---------------------------------------------------------------------------
# Research topic models
# ---------------------------------------------------------------------------


class ResearchRequest(BaseModel):
    """Research topic request body."""

    query: str = Field(..., min_length=1, max_length=500, description="Research topic or question")
    limit: int = Field(default=20, ge=1, le=50, description="Number of papers to return")
    year_min: int | None = Field(None, description="Minimum publication year")
    exclude_types: list[str] | None = Field(
        None,
        description=(
            "Paper types to exclude from results. "
            "Supported types: 'benchmark', 'dataset', 'survey'. "
            "Papers whose title contains related keywords will be filtered out."
        ),
    )


class ResearchPaperItem(BaseModel):
    """A paper in the research topic response, with combined scoring."""

    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    tier: int | None = None
    abstract: str | None = None
    citation_count: int = 0
    pagerank: float | None = None
    keywords: list[str] = Field(default_factory=list)
    code_url: str | None = None
    pdf_url: str | None = None
    relevance_score: float = 0.0
    notable_score: float = 0.0
    combined_score: float = 0.0


class TopicTrend(BaseModel):
    """A trending keyword within the research topic."""

    keyword: str
    counts_by_year: dict[str, int] = Field(default_factory=dict)
    growth_rate: float = 0.0


class ResearchResponse(BaseModel):
    """Full research topic response."""

    query: str
    papers: list[ResearchPaperItem]
    trends: list[TopicTrend]
    summary: dict
    query_time_ms: int


class ZoteroPushRequest(BaseModel):
    """Push corpus papers (by point ID) to the configured Zotero library."""

    paper_ids: list[str] = Field(..., description="Qdrant point IDs to push (max 50)")
