"""Enrichment pipelines for adding metadata to papers.

This package contains enrichers for:
- OpenAlex (openalex.py) - Citation and abstract enrichment via DOI/title lookup
- Semantic Scholar (semantic_scholar.py) - Fallback citation enrichment
- PDF (pdf.py) - Reference extraction from PDFs via GROBID
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
from src.core.enrichment.pdf import (
    PDFReferenceExtractor,
    PDFExtractionProgress,
)

__all__ = [
    # OpenAlex enricher
    "PaperEnricher",
    "EnrichmentProgress",
    "EnrichmentType",
    # Semantic Scholar enricher
    "SemanticScholarEnricher",
    "S2EnrichmentProgress",
    # PDF extractor
    "PDFReferenceExtractor",
    "PDFExtractionProgress",
]
