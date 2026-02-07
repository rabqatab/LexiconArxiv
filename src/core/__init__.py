"""Core corpus collection module for LexiconArxiv.

Subpackages:
- crawler/     - Data source collectors (OpenAlex, ACL, DBLP, OpenReview, ACM, AAAI)
- enrichment/  - Enrichment pipelines (OpenAlex, Semantic Scholar, PDF)
- resolution/  - Reference resolution (normalizer, resolver)

Core modules:
- storage.py       - Qdrant vector database layer
- checkpoint.py    - Checkpoint management for resumable operations
- config.py        - Venue configurations
- deduplication.py - Cross-source deduplication
"""

from src.core.config import VENUES, VenueConfig, get_tier_venues, get_venue_by_name
from src.core.constants import (
    OPENALEX_BASE_URL,
    CROSSREF_BASE_URL,
    S2_BASE_URL,
    get_openalex_email,
    get_openalex_api_key,
    get_crossref_email,
    get_s2_api_key,
    get_qdrant_url,
    get_qdrant_collection,
)
from src.core.storage import QdrantStorage
from src.core.checkpoint import CheckpointManager
from src.core.deduplication import Deduplicator

# Import from crawler subpackage
from src.core.crawler import (
    CoreCorpusCollector,
    ACLAnthologyCollector,
    DBLPCollector,
    OpenReviewCollector,
    ACMOpenCollector,  # Alias for DBLPCollector (backward compat)
    AAOJSCollector,
    ACL_VENUES,
    DBLP_VENUES,
    OPENREVIEW_VENUES,
    ACM_VENUES,
    AAAI_VENUES,
    get_acl_venues,
    get_dblp_venues,
    get_openreview_venues,
    get_acm_venues,
    get_aaai_venues,
)

# Backward compatibility alias
ACM_OPEN_VENUES = ACM_VENUES
get_acm_open_venues = get_acm_venues

# Import from enrichment subpackage
from src.core.enrichment import (
    PaperEnricher,
    EnrichmentProgress,
    EnrichmentType,
    SemanticScholarEnricher,
    PDFReferenceExtractor,
)

# Import from resolution subpackage
from src.core.resolution import (
    IdentifierNormalizer,
    IdentifierType,
    ReferenceResolver,
    ResolutionProgress,
)

__all__ = [
    # API Constants
    "OPENALEX_BASE_URL",
    "CROSSREF_BASE_URL",
    "S2_BASE_URL",
    "get_openalex_email",
    "get_openalex_api_key",
    "get_crossref_email",
    "get_s2_api_key",
    "get_qdrant_url",
    "get_qdrant_collection",
    # Config
    "VENUES",
    "VenueConfig",
    "get_tier_venues",
    "get_venue_by_name",
    # Storage
    "QdrantStorage",
    "CheckpointManager",
    # Deduplication
    "Deduplicator",
    # Collectors
    "CoreCorpusCollector",
    "ACLAnthologyCollector",
    "DBLPCollector",
    "OpenReviewCollector",
    "ACMOpenCollector",
    "AAOJSCollector",
    # Venue configs
    "ACL_VENUES",
    "DBLP_VENUES",
    "OPENREVIEW_VENUES",
    "ACM_VENUES",
    "ACM_OPEN_VENUES",  # Backward compat alias
    "AAAI_VENUES",
    "get_acl_venues",
    "get_dblp_venues",
    "get_openreview_venues",
    "get_acm_venues",
    "get_acm_open_venues",  # Backward compat alias
    "get_aaai_venues",
    # Enrichment
    "PaperEnricher",
    "EnrichmentProgress",
    "EnrichmentType",
    "SemanticScholarEnricher",
    "PDFReferenceExtractor",
    # Resolution
    "IdentifierNormalizer",
    "IdentifierType",
    "ReferenceResolver",
    "ResolutionProgress",
]
