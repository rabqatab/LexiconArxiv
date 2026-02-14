"""Regex patterns for acronym extraction from paper titles and abstracts.

Extracts model names, method names, and defined acronyms using
common academic writing patterns.
"""

import re
from typing import Pattern

from src.core.keyword.stopwords import is_valid_keyword

# Regex to split CamelCase into word-like segments: "ChatGPT" -> ["Chat", "GPT"]
_CAMELCASE_SPLIT = re.compile(r'[A-Z](?:[a-z]+|[A-Z]*(?=[A-Z][a-z]|\b))')

# Common English words that appear as CamelCase segments in dirty/scraped data.
# Only words >= 3 chars to avoid matching single letters.
_COMMON_CAMELCASE_SEGMENTS = {
    "add", "alert", "alerts", "bind", "binder", "cancel", "check",
    "cite", "citation", "clear", "click", "close", "conference", "copy",
    "create", "data", "delete", "display", "download", "downloads",
    "edit", "end", "error", "event", "export", "file", "filter", "find",
    "form", "get", "help", "hide", "home", "import", "info", "input",
    "item", "join", "key", "link", "list", "listing", "load", "log",
    "manage", "may", "menu", "mode", "month", "move", "name", "new",
    "next", "node", "note", "open", "output", "page", "pages", "panel",
    "path", "post", "press", "print", "read", "remove", "reset", "run",
    "save", "search", "select", "send", "set", "share", "show", "sign",
    "site", "sort", "start", "state", "stop", "submit", "tab", "text",
    "toggle", "update", "upload", "url", "user", "value", "view", "write",
    "www",
}

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

# Pattern: CamelCase names (e.g., "ChatGPT", "FastText", "DeepSeek", "PyTorch")
TITLE_CAMELCASE_PATTERN: Pattern = re.compile(r'\b([A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)+)\b')


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

# Pattern: "dubbed/termed X" (e.g., "...dubbed ChatGPT...")
ABSTRACT_DUBBED_PATTERN: Pattern = re.compile(
    r'(?:dubbed|termed)\s+([A-Z][A-Za-z0-9\-]+)'
)

# Pattern: "known as/referred to as X" (e.g., "...known as BERT...")
ABSTRACT_KNOWN_AS_PATTERN: Pattern = re.compile(
    r'(?:known\s+as|referred\s+to\s+as)\s+([A-Z][A-Za-z0-9\-]+)'
)

# Pattern: Defined acronym in parentheses (e.g., "...Retrieval-Augmented Generation (RAG)...")
ABSTRACT_DEFINED_PATTERN: Pattern = re.compile(r'\(([A-Z]{2,8})\)')

# Pattern: Model names with version numbers (e.g., "GPT-4", "BERT-large", "T5-base")
ABSTRACT_MODEL_VERSION_PATTERN: Pattern = re.compile(
    r'\b([A-Z][A-Za-z]*-(?:small|base|large|xl|xxl|\d+(?:\.\d+)?[bB]?))\b'
)

# Pattern: ", the Name," or ", the Name." (e.g., "...architecture, the Transformer, based...")
ABSTRACT_THE_NAME_PATTERN: Pattern = re.compile(
    r',\s+the\s+([A-Z][A-Za-z0-9\-]+)(?:,|\.\s)'
)

# Pattern: CamelCase names in abstract (e.g., "ChatGPT", "FastText", "DeepSeek")
ABSTRACT_CAMELCASE_PATTERN: Pattern = re.compile(r'\b([A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)+)\b')

# Pattern: Inline all-caps acronym in abstract (same as title)
ABSTRACT_INLINE_PATTERN: Pattern = re.compile(r'\b([A-Z]{2,10}(?:s)?)\b')


def _is_valid_camelcase(name: str) -> bool:
    """Check if a CamelCase match is likely a real name vs concatenated words.

    Rejects matches where ALL segments are common English words (e.g.,
    "ConferenceMay", "BinderSave" from dirty HTML data), while keeping
    real names like "ChatGPT", "PyTorch", "DeepSeek".
    """
    segments = _CAMELCASE_SPLIT.findall(name)
    if not segments:
        return False
    # If every segment (lowered) is a common word, it's likely an artifact
    return not all(seg.lower() in _COMMON_CAMELCASE_SEGMENTS for seg in segments)


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

    # Find CamelCase names (e.g., ChatGPT, FastText)
    camelcase_matches = TITLE_CAMELCASE_PATTERN.findall(title)
    acronyms.extend(m for m in camelcase_matches if _is_valid_camelcase(m))

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

    # Find "dubbed/termed X" names
    dubbed_matches = ABSTRACT_DUBBED_PATTERN.findall(abstract)
    acronyms.extend(dubbed_matches)

    # Find "known as/referred to as X" names
    known_as_matches = ABSTRACT_KNOWN_AS_PATTERN.findall(abstract)
    acronyms.extend(known_as_matches)

    # Find defined acronyms in parentheses
    defined_matches = ABSTRACT_DEFINED_PATTERN.findall(abstract)
    acronyms.extend(defined_matches)

    # Find model names with versions
    model_matches = ABSTRACT_MODEL_VERSION_PATTERN.findall(abstract)
    acronyms.extend(model_matches)

    # Find ", the Name," pattern (e.g., "the Transformer")
    the_name_matches = ABSTRACT_THE_NAME_PATTERN.findall(abstract)
    acronyms.extend(the_name_matches)

    # Find CamelCase names (e.g., ChatGPT, FastText)
    camelcase_matches = ABSTRACT_CAMELCASE_PATTERN.findall(abstract)
    acronyms.extend(m for m in camelcase_matches if _is_valid_camelcase(m))

    # Find inline all-caps acronyms (including plural forms like LLMs)
    inline_matches = ABSTRACT_INLINE_PATTERN.findall(abstract)
    acronyms.extend(inline_matches)

    # Validate and deduplicate
    return _deduplicate_keywords(acronyms)


def _deduplicate_keywords(keywords: list[str]) -> list[str]:
    """Validate and deduplicate keywords while preserving original case.

    Also performs plural normalization: when a keyword has an all-uppercase
    body with a trailing lowercase 's' (e.g., "LLMs"), the singular form
    ("LLM") is emitted as an additional keyword.

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

        # Plural normalization: "LLMs" -> also emit "LLM"
        if kw.endswith('s') and len(kw) > 2 and kw[:-1].isupper():
            singular = kw[:-1]
            singular_lower = singular.lower()
            if singular_lower not in seen and is_valid_keyword(singular):
                seen.add(singular_lower)
                result.append(singular)

    return result
