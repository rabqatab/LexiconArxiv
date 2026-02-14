"""Centralized constants for API endpoints, URLs, and configuration.

This module consolidates API-related constants to avoid duplication
across crawler, enrichment, and resolution modules.
"""

import os

# =============================================================================
# API Base URLs
# =============================================================================

# OpenAlex API
OPENALEX_BASE_URL = "https://api.openalex.org"

# CrossRef API
CROSSREF_BASE_URL = "https://api.crossref.org"

# Semantic Scholar API
S2_BASE_URL = "https://api.semanticscholar.org/graph/v1"

# AAAI OJS
AAAI_OJS_BASE_URL = "https://ojs.aaai.org"

# ACM Digital Library
ACM_DL_BASE_URL = "https://dl.acm.org"


# =============================================================================
# Environment Variable Names
# =============================================================================

# OpenAlex
OPENALEX_EMAIL_ENV = "OPENALEX_EMAIL"
OPENALEX_API_KEY_ENV = "OPENALEX_API_KEY"

# CrossRef
CROSSREF_EMAIL_ENV = "CROSSREF_EMAIL"

# Semantic Scholar
S2_API_KEY_ENV = "S2_API_KEY"
SEMANTIC_SCHOLAR_API_KEY_ENV = "SEMANTIC_SCHOLAR_API_KEY"

# Qdrant
QDRANT_URL_ENV = "QDRANT_URL"
QDRANT_COLLECTION_ENV = "QDRANT_COLLECTION"

# Gemini
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GOOGLE_API_KEY_ENV = "GOOGLE_API_KEY"

# Ollama
OLLAMA_BASE_URL_ENV = "OLLAMA_BASE_URL"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


# =============================================================================
# Helper Functions
# =============================================================================


def get_openalex_email() -> str | None:
    """Get OpenAlex email from environment."""
    return os.getenv(OPENALEX_EMAIL_ENV)


def get_openalex_api_key() -> str | None:
    """Get OpenAlex API key from environment."""
    return os.getenv(OPENALEX_API_KEY_ENV)


def get_crossref_email() -> str | None:
    """Get CrossRef email from environment."""
    return os.getenv(CROSSREF_EMAIL_ENV)


def get_s2_api_key() -> str | None:
    """Get Semantic Scholar API key from environment.
    
    Checks both S2_API_KEY and SEMANTIC_SCHOLAR_API_KEY.
    """
    return os.getenv(S2_API_KEY_ENV) or os.getenv(SEMANTIC_SCHOLAR_API_KEY_ENV)


def get_qdrant_url() -> str:
    """Get Qdrant URL from environment with default."""
    return os.getenv(QDRANT_URL_ENV, "http://localhost:6333")


def get_qdrant_collection() -> str:
    """Get Qdrant collection name from environment with default."""
    return os.getenv(QDRANT_COLLECTION_ENV, "lexicon_arxiv")


def get_gemini_api_key() -> str | None:
    """Get Gemini API key from environment.

    Checks both GEMINI_API_KEY and GOOGLE_API_KEY.
    """
    return os.getenv(GEMINI_API_KEY_ENV) or os.getenv(GOOGLE_API_KEY_ENV)


def get_ollama_base_url() -> str:
    """Get Ollama base URL from environment with default."""
    return os.getenv(OLLAMA_BASE_URL_ENV, DEFAULT_OLLAMA_BASE_URL)
