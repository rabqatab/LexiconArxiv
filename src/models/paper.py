"""Data models for papers collected from various sources."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceType(str, Enum):
    """Source types for paper data."""

    OPENALEX = "openalex"
    ARXIV = "arxiv"
    ACL = "acl"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    DBLP = "dblp"
    OPENREVIEW = "openreview"
    ACM = "acm"
    AAAI = "aaai"


class PaperType(str, Enum):
    """Classification of paper types."""

    METHOD = "method"
    DATASET = "dataset"
    BENCHMARK = "benchmark"
    SURVEY = "survey"
    ANALYSIS = "analysis"
    APPLICATION = "application"
    POSITION = "position"
    DEMO = "demo"
    OTHER = "other"


class Author(BaseModel):
    """Author information."""

    name: str
    affiliation: str | None = None
    orcid: str | None = None
    openalex_id: str | None = None

    def __str__(self) -> str:
        return self.name


class RawPaper(BaseModel):
    """Raw paper data collected from a source.

    This represents a single paper record from one source before deduplication.
    """

    # Source information
    source: SourceType
    source_id: str

    # Core metadata
    title: str
    abstract: str | None = None
    authors: list[Author] = Field(default_factory=list)
    year: int | None = None
    month: int | None = None

    # Identifiers
    doi: str | None = None
    arxiv_id: str | None = None
    acl_id: str | None = None
    openalex_id: str | None = None

    # Venue
    venue: str | None = None
    venue_type: str | None = None  # conference, journal, workshop, preprint

    # Classification
    paper_type: PaperType = PaperType.OTHER
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    # URLs
    pdf_url: str | None = None
    abstract_url: str | None = None
    code_url: str | None = None

    # Metrics
    citation_count: int = 0

    # Core corpus fields
    tier: int | None = None  # 0 = Tier 0 venue, 1 = Tier 1 venue
    is_core: bool = False  # Whether this is part of the core corpus
    referenced_works: list[str] = Field(default_factory=list)  # OpenAlex IDs of cited papers

    # Raw data for debugging/reprocessing
    raw_data: dict[str, Any] | None = None

    # Timestamps
    published_date: datetime | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(use_enum_values=True)

    @property
    def primary_id(self) -> str:
        """Return the primary identifier for this paper."""
        return self.doi or self.arxiv_id or self.acl_id or self.source_id

    @property
    def title_normalized(self) -> str:
        """Return normalized title for deduplication."""
        import re

        title = self.title.lower()
        title = re.sub(r"[^\w\s]", "", title)
        title = " ".join(title.split())
        return title

    def __str__(self) -> str:
        return f"{self.title} ({self.year})"
