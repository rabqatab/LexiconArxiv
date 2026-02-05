"""Regex patterns for acronym extraction from paper titles and abstracts.

Extracts model names, method names, and defined acronyms using
common academic writing patterns.
"""

import re
from typing import Pattern

from src.core.keyword.stopwords import is_valid_keyword

# =============================================================================
# Title Patterns
# =============================================================================

# Pattern: "ACRONYM: Description" (e.g., "BERT: Pre-training of...")
TITLE_COLON_PATTERN: Pattern = re.compile(r'^([A-Z][A-Za-z0-9\-]{1,10}):\s')

# Pattern: "ACRONYM - Description" (e.g., "ColBERT - Efficient...")
TITLE_DASH_PATTERN: Pattern = re.compile(r'^([A-Z][A-Za-z0-9]{1,10})\s*[-–—]\s')

# Pattern: "Description (ACRONYM)" at end (e.g., "...Understanding (BERT)")
TITLE_PAREN_END_PATTERN: Pattern = re.compile(r'\(([A-Z][A-Za-z0-9\-]{1,10})\)\s*$')

# Pattern: Inline all-caps acronym (e.g., "BERT-based Models")
# Requires 2+ uppercase letters, may include numbers/hyphens
TITLE_INLINE_PATTERN: Pattern = re.compile(r'\b([A-Z]{2,10}(?:-[A-Z0-9]+)?)\b')


# =============================================================================
# Abstract Patterns
# =============================================================================

# Pattern: "We propose/introduce/present X" (e.g., "We introduce HyDE, a method...")
# Requires the name to start with uppercase and be followed by comma or space+article
ABSTRACT_PROPOSE_PATTERN: Pattern = re.compile(
    r'(?:introduce|propose|present)\s+([A-Z][A-Za-z0-9\-]+)(?:,|\s+(?:a|an|the|for|to|which|that)\b)'
)

# Pattern: "called X" (e.g., "...method called BERT...")
# Requires uppercase start
ABSTRACT_CALLED_PATTERN: Pattern = re.compile(
    r'called\s+([A-Z][A-Za-z0-9]+)'
)

# Pattern: "named X" (e.g., "...model named GPT-4...")
# Requires uppercase start
ABSTRACT_NAMED_PATTERN: Pattern = re.compile(
    r'named\s+([A-Z][A-Za-z0-9\-]+)'
)

# Pattern: Defined acronym in parentheses (e.g., "...Retrieval-Augmented Generation (RAG)...")
ABSTRACT_DEFINED_PATTERN: Pattern = re.compile(r'\(([A-Z]{2,8})\)')

# Pattern: Model names with version numbers (e.g., "GPT-4", "BERT-large", "T5-base")
ABSTRACT_MODEL_VERSION_PATTERN: Pattern = re.compile(
    r'\b([A-Z][A-Za-z]*-(?:small|base|large|xl|xxl|\d+(?:\.\d+)?[bB]?))\b'
)

# Pattern: Inline all-caps acronym in abstract (same as title)
ABSTRACT_INLINE_PATTERN: Pattern = re.compile(r'\b([A-Z]{2,10}(?:s)?)\b')


def extract_title_acronyms(title: str) -> list[str]:
    """Extract acronyms from paper title.

    Uses multiple patterns to identify:
    - Prefix acronyms (BERT: ...)
    - Dash-separated (ColBERT - ...)
    - Suffix acronyms (... (BERT))
    - Inline acronyms (BERT-based...)

    Args:
        title: Paper title string.

    Returns:
        List of extracted acronyms (validated and deduplicated).
    """
    if not title:
        return []

    acronyms: list[str] = []

    # Try prefix patterns (colon and dash)
    colon_match = TITLE_COLON_PATTERN.match(title)
    if colon_match:
        acronyms.append(colon_match.group(1))

    dash_match = TITLE_DASH_PATTERN.match(title)
    if dash_match:
        acronyms.append(dash_match.group(1))

    # Try suffix pattern (parentheses at end)
    paren_match = TITLE_PAREN_END_PATTERN.search(title)
    if paren_match:
        acronyms.append(paren_match.group(1))

    # Find inline all-caps acronyms
    inline_matches = TITLE_INLINE_PATTERN.findall(title)
    acronyms.extend(inline_matches)

    # Validate and deduplicate
    return _deduplicate_keywords(acronyms)


def extract_abstract_acronyms(abstract: str) -> list[str]:
    """Extract acronyms and model names from paper abstract.

    Uses patterns to identify:
    - Proposed/introduced method names
    - Defined acronyms in parentheses
    - Model names with versions
    - Inline all-caps acronyms

    Args:
        abstract: Paper abstract string.

    Returns:
        List of extracted acronyms (validated and deduplicated).
    """
    if not abstract:
        return []

    acronyms: list[str] = []

    # Find proposed/introduced names
    propose_matches = ABSTRACT_PROPOSE_PATTERN.findall(abstract)
    acronyms.extend(propose_matches)

    # Find "called X" names
    called_matches = ABSTRACT_CALLED_PATTERN.findall(abstract)
    acronyms.extend(called_matches)

    # Find "named X" names
    named_matches = ABSTRACT_NAMED_PATTERN.findall(abstract)
    acronyms.extend(named_matches)

    # Find defined acronyms in parentheses
    defined_matches = ABSTRACT_DEFINED_PATTERN.findall(abstract)
    acronyms.extend(defined_matches)

    # Find model names with versions
    model_matches = ABSTRACT_MODEL_VERSION_PATTERN.findall(abstract)
    acronyms.extend(model_matches)

    # Find inline all-caps acronyms (including plural forms like LLMs)
    inline_matches = ABSTRACT_INLINE_PATTERN.findall(abstract)
    acronyms.extend(inline_matches)

    # Validate and deduplicate
    return _deduplicate_keywords(acronyms)


def _deduplicate_keywords(keywords: list[str]) -> list[str]:
    """Validate and deduplicate keywords while preserving original case.

    Args:
        keywords: List of keyword candidates.

    Returns:
        Validated, deduplicated list of keywords.
    """
    seen: set[str] = set()
    result: list[str] = []

    for kw in keywords:
        kw = kw.strip()
        if not is_valid_keyword(kw):
            continue

        # Case-insensitive deduplication
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            result.append(kw)

    return result
