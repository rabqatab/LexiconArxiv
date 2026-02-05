"""Stopword list and validation for keyword extraction.

Filters out common words, section headers, and generic terms
that don't contribute to paper identification or search.
"""

# Common English words that may match acronym patterns
COMMON_WORDS = {
    "IT", "IS", "OR", "AN", "AS", "AT", "BE", "BY", "DO", "GO",
    "IF", "IN", "NO", "OF", "ON", "SO", "TO", "UP", "WE", "US",
    "HE", "ME", "MY", "OK", "AM", "IM",
    # Additional common words that appear in all-caps titles
    "THE", "FOR", "AND", "WITH", "FROM", "THAT", "THIS", "HAVE",
    "ARE", "NOT", "BUT", "CAN", "ALL", "HAS", "ITS", "OUR",
    "NEW", "ONE", "TWO", "VIA", "HOW", "WHY", "WHAT", "WHEN",
    "USING", "BASED", "LEARNING", "NEURAL", "NETWORK", "NETWORKS",
    "DEEP", "DATA", "LANGUAGE", "NATURAL", "MACHINE", "MODELS",
    "MULTI", "TRAINING", "EFFICIENT", "TOWARDS", "BEYOND",
    "SIMPLE", "BETTER", "MORE", "LESS", "LARGE", "SMALL",
    # More common title words
    "ECONOMIC", "BLENDED", "SEARCH", "STRATEGY", "OPTIMIZATION",
    "HYPERPARAMETER", "THROUGH", "OVER", "INTO", "UNDER",
    "HIGH", "LOW", "FAST", "SLOW", "ROBUST", "SCALABLE",
    "ADAPTIVE", "DYNAMIC", "STATIC", "ONLINE", "OFFLINE",
}

# Section headers and structural terms
SECTION_HEADERS = {
    "INTRODUCTION", "CONCLUSION", "ABSTRACT", "RESULTS",
    "METHOD", "METHODS", "DISCUSSION", "REFERENCES",
    "BACKGROUND", "EXPERIMENT", "EXPERIMENTS", "EVALUATION",
    "RELATED", "WORK", "FUTURE", "ACKNOWLEDGMENTS",
    "APPENDIX", "SUPPLEMENT", "SUPPLEMENTARY",
}

# Generic academic terms
GENERIC_TERMS = {
    "PAPER", "STUDY", "WORK", "APPROACH", "SYSTEM",
    "MODEL", "FRAMEWORK", "ANALYSIS", "RESEARCH",
    "SURVEY", "REVIEW", "BENCHMARK", "DATASET",
    "TASK", "PROBLEM", "SOLUTION", "APPLICATION",
    "TECHNIQUE", "ALGORITHM", "PERFORMANCE", "EFFICIENCY",
}

# Roman numerals and numbering
NUMBERING = {
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV",
}

# Combined stopwords set
STOPWORDS = COMMON_WORDS | SECTION_HEADERS | GENERIC_TERMS | NUMBERING


def is_valid_keyword(keyword: str, min_length: int = 2, max_length: int = 15) -> bool:
    """Check if a keyword passes validation rules.

    Args:
        keyword: The keyword to validate.
        min_length: Minimum character length (default: 2).
        max_length: Maximum character length (default: 15).

    Returns:
        True if the keyword is valid, False otherwise.
    """
    if not keyword:
        return False

    # Length check
    if len(keyword) < min_length or len(keyword) > max_length:
        return False

    # Stopword check (case-insensitive)
    if keyword.upper() in STOPWORDS:
        return False

    # Must contain at least one letter
    if not any(c.isalpha() for c in keyword):
        return False

    # Valid character check: allow letters, numbers, hyphens
    for c in keyword:
        if not (c.isalnum() or c == '-'):
            return False

    return True
