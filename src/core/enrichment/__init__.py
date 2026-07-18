"""Enrichment pipelines for adding metadata to papers.

This package contains enrichers for:
- Base (base.py) - Base classes and mixins for API fetching
- OpenAlex (openalex.py) - Citation and abstract enrichment via DOI/title lookup
- Semantic Scholar (semantic_scholar.py) - Fallback citation enrichment
- CrossRef (crossref.py) - Citation enrichment for ACM/Springer papers
- PDF (pdf.py) - Reference extraction from PDFs via GROBID
- Stub (stub.py) - Metadata enrichment for stub papers (external references)
- Code Repos (code_repos.py) - GitHub code repository URL enrichment via PWC/HuggingFace
- GROBID Code Repos (grobid_code_repos.py) - GitHub URL extraction from paper PDFs via GROBID
- GitHub Search (github_search.py) - Code repository search via GitHub API
"""

from src.core.enrichment.base import (
    BaseEnricher,
    CrossRefMixin,
    OpenAlexMixin,
)
from src.core.enrichment.openalex import (
    PaperEnricher,
    EnrichmentProgress,
    EnrichmentType,
)
from src.core.enrichment.semantic_scholar import (
    SemanticScholarEnricher,
    S2EnrichmentProgress,
)
from src.core.enrichment.crossref import (
    CrossRefEnricher,
    CrossRefEnrichmentProgress,
)
from src.core.enrichment.pdf import (
    PDFReferenceExtractor,
    PDFExtractionProgress,
)
from src.core.enrichment.stub import (
    StubEnricher,
    StubEnrichmentProgress,
)
from src.core.enrichment.code_repos import (
    CodeRepoEnricher,
    CodeRepoEnrichmentProgress,
)
from src.core.enrichment.grobid_code_repos import (
    GrobidCodeRepoExtractor,
    GrobidCodeRepoProgress,
)
from src.core.enrichment.github_search import (
    GitHubSearchEnricher,
    GitHubSearchProgress,
)
from src.core.enrichment.unpaywall import (
    UnpaywallEnricher,
    UnpaywallProgress,
)

__all__ = [
    # Base classes
    "BaseEnricher",
    "OpenAlexMixin",
    "CrossRefMixin",
    # OpenAlex enricher
    "PaperEnricher",
    "EnrichmentProgress",
    "EnrichmentType",
    # Semantic Scholar enricher
    "SemanticScholarEnricher",
    "S2EnrichmentProgress",
    # CrossRef enricher
    "CrossRefEnricher",
    "CrossRefEnrichmentProgress",
    # PDF extractor
    "PDFReferenceExtractor",
    "PDFExtractionProgress",
    # Stub enricher
    "StubEnricher",
    "StubEnrichmentProgress",
    # Code repo enricher
    "CodeRepoEnricher",
    "CodeRepoEnrichmentProgress",
    # GROBID code repo extractor
    "GrobidCodeRepoExtractor",
    "GrobidCodeRepoProgress",
    # GitHub search enricher
    "GitHubSearchEnricher",
    "GitHubSearchProgress",
    # Unpaywall OA-PDF enricher
    "UnpaywallEnricher",
    "UnpaywallProgress",
]
