"""Reference resolution pipeline for building citation graphs.

This package contains:
- normalizer.py - Identifier classification and normalization (DOI, arXiv, OpenAlex, TITLE)
- resolver.py - 3-step resolution pipeline (normalize, arXiv→DOI, resolve to internal IDs)
"""

from src.core.resolution.normalizer import (
    IdentifierNormalizer,
    IdentifierType,
    NormalizedIdentifier,
)
from src.core.resolution.resolver import (
    ReferenceResolver,
    ResolutionProgress,
)

__all__ = [
    # Normalizer
    "IdentifierNormalizer",
    "IdentifierType",
    "NormalizedIdentifier",
    # Resolver
    "ReferenceResolver",
    "ResolutionProgress",
]
