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

# Unpaywall API (free OA PDF resolution by DOI; email required, no key)
UNPAYWALL_BASE_URL = "https://api.unpaywall.org/v2"


# =============================================================================
# Environment Variable Names
# =============================================================================

# OpenAlex
OPENALEX_EMAIL_ENV = "OPENALEX_EMAIL"
OPENALEX_API_KEY_ENV = "OPENALEX_API_KEY"
OPENALEX_API_KEYS_ENV = "OPENALEX_API_KEYS"

# CrossRef
CROSSREF_EMAIL_ENV = "CROSSREF_EMAIL"

# Semantic Scholar
S2_API_KEY_ENV = "S2_API_KEY"
S2_API_KEYS_ENV = "S2_API_KEYS"
SEMANTIC_SCHOLAR_API_KEY_ENV = "SEMANTIC_SCHOLAR_API_KEY"

# Qdrant
QDRANT_URL_ENV = "QDRANT_URL"
QDRANT_COLLECTION_ENV = "QDRANT_COLLECTION"

# GitHub API
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"

# Ollama
OLLAMA_BASE_URL_ENV = "OLLAMA_BASE_URL"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

# Embedding model
DEFAULT_EMBEDDING_MODEL = "qwen3-embedding:8b"
EMBEDDING_VECTOR_NAME = "abstract-qwen3-8b"
EMBEDDING_VECTOR_SIZE = 1024
EMBEDDING_FULL_SIZE = 4096  # Ollama returns full dim, truncate client-side

# Section-level embedding vectors
SECTION_ROLES = ["task", "domain", "background", "approach", "method", "result", "contribution"]
SECTION_VECTOR_PREFIX = "section-"
STRUCTURED_VECTOR_NAME = "structured-abstract"

# All dense vector names (for collection creation)
ALL_DENSE_VECTORS = (
    [EMBEDDING_VECTOR_NAME, STRUCTURED_VECTOR_NAME]
    + [f"{SECTION_VECTOR_PREFIX}{role}" for role in SECTION_ROLES]
)


# =============================================================================
# Helper Functions
# =============================================================================


def get_openalex_email() -> str | None:
    """Get OpenAlex email from environment."""
    return os.getenv(OPENALEX_EMAIL_ENV)


def get_openalex_api_key() -> str | None:
    """Get OpenAlex API key from environment."""
    return os.getenv(OPENALEX_API_KEY_ENV)


def get_openalex_api_keys() -> list[str]:
    """Get OpenAlex API keys from environment.

    Reads OPENALEX_API_KEYS (comma-separated) first, falls back to
    OPENALEX_API_KEY (also split on commas for convenience).

    Returns:
        List of API key strings (may be empty).
    """
    multi = os.getenv(OPENALEX_API_KEYS_ENV)
    if multi:
        keys = [k.strip() for k in multi.split(",") if k.strip()]
        if keys:
            return keys
    single = os.getenv(OPENALEX_API_KEY_ENV)
    if single and single.strip():
        # Also split on commas in case user put multiple keys in the singular var
        keys = [k.strip() for k in single.split(",") if k.strip()]
        if keys:
            return keys
    return []


def get_crossref_email() -> str | None:
    """Get CrossRef email from environment."""
    return os.getenv(CROSSREF_EMAIL_ENV)


def get_unpaywall_email() -> str | None:
    """Get the polite-pool email for Unpaywall (required by their API).

    Falls back to the CrossRef/OpenAlex email since any valid contact address
    is accepted — avoids forcing a separate env var.
    """
    return (
        os.getenv("UNPAYWALL_EMAIL")
        or os.getenv(CROSSREF_EMAIL_ENV)
        or os.getenv(OPENALEX_EMAIL_ENV)
    )


def get_s2_api_key() -> str | None:
    """Get Semantic Scholar API key from environment.

    Checks both S2_API_KEY and SEMANTIC_SCHOLAR_API_KEY.
    """
    return os.getenv(S2_API_KEY_ENV) or os.getenv(SEMANTIC_SCHOLAR_API_KEY_ENV)


def get_s2_api_keys() -> list[str]:
    """Get S2 API keys from environment.

    Reads S2_API_KEYS (comma-separated) first, falls back to S2_API_KEY (single).

    Returns:
        List of API key strings (may be empty).
    """
    multi = os.getenv(S2_API_KEYS_ENV)
    if multi:
        keys = [k.strip() for k in multi.split(",") if k.strip()]
        if keys:
            return keys
    single = get_s2_api_key()
    if single:
        return [single]
    return []


def get_qdrant_url() -> str:
    """Get Qdrant URL from environment with default."""
    return os.getenv(QDRANT_URL_ENV, "http://localhost:6333")


def get_qdrant_collection() -> str:
    """Get Qdrant collection name from environment with default."""
    return os.getenv(QDRANT_COLLECTION_ENV, "lexicon_arxiv")


def get_github_token() -> str | None:
    """Get GitHub API token from environment."""
    return os.getenv(GITHUB_TOKEN_ENV)


def get_ollama_base_url() -> str:
    """Get Ollama base URL from environment with default."""
    return os.getenv(OLLAMA_BASE_URL_ENV, DEFAULT_OLLAMA_BASE_URL)
