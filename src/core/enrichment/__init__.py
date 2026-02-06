"""Enrichment pipelines for adding metadata to papers.

This package contains enrichers for:
- OpenAlex (openalex.py) - Citation and abstract enrichment via DOI/title lookup
- Semantic Scholar (semantic_scholar.py) - Fallback citation enrichment
- CrossRef (crossref.py) - Citation enrichment for ACM/Springer papers
- PDF (pdf.py) - Reference extraction from PDFs via GROBID
- Stub (stub.py) - Metadata enrichment for stub papers (external references)
"""

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

__all__ = [
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
]
