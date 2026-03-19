"""Request and response models for trends API."""

from pydantic import BaseModel, Field


class NotablePaperItem(BaseModel):
    """A paper ranked by notable score."""

    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    tier: int | None = None
    citation_count: int = 0
    pagerank: float | None = None
    notable_score: float = 0.0
    keywords: list[str] = Field(default_factory=list)


class NotableResponse(BaseModel):
    """Notable papers response."""

    papers: list[NotablePaperItem]
    total: int


class KeywordTrendPoint(BaseModel):
    """A single data point in a keyword time-series."""

    year: int
    count: int


class KeywordTrendItem(BaseModel):
    """A keyword with its time-series data and growth rate."""

    keyword: str
    category: str  # task, method, model, domain, dataset, etc.
    counts: list[KeywordTrendPoint]
    growth_rate: float  # ratio of recent vs older counts
    total_papers: int


class KeywordTrendsResponse(BaseModel):
    """Keyword trends response."""

    trends: list[KeywordTrendItem]
    categories: list[str]


class RisingKeywordItem(BaseModel):
    """A rising keyword with growth stats."""

    keyword: str
    category: str
    growth_rate: float
    recent_count: int  # papers in last 2 years
    total_count: int


class RisingResponse(BaseModel):
    """Rising keywords response."""

    rising: list[RisingKeywordItem]


class TopicCluster(BaseModel):
    """A discovered topic cluster."""

    cluster_id: int
    label: str  # Auto-generated from top keywords
    size: int
    top_keywords: list[str] = Field(default_factory=list)
    year_distribution: dict[str, int] = Field(default_factory=dict)


class TopicsResponse(BaseModel):
    """Topic clusters response."""

    topics: list[TopicCluster]
    total_papers: int
    noise_papers: int  # Papers not in any cluster


class TopicPapersResponse(BaseModel):
    """Papers in a specific topic cluster."""

    cluster_id: int
    label: str
    papers: list[NotablePaperItem]
    total: int


class TrendMapPoint(BaseModel):
    """A point on the 2D topic map."""

    id: str
    title: str
    x: float  # UMAP dimension 1
    y: float  # UMAP dimension 2
    cluster_id: int  # -1 for noise
    year: int | None = None
    venue: str | None = None


class TrendMapResponse(BaseModel):
    """2D topic map response."""

    points: list[TrendMapPoint]
    clusters: list[TopicCluster]
