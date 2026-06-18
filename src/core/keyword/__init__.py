"""Keyword extraction module for Core Corpus papers.

Provides multi-phase keyword extraction:
1. Regex-based acronym extraction from title/abstract
2. KeyBERT-based semantic keyword extraction from abstract
3. LLM-based extraction via Ollama (optional)
4. LLM judge validation (optional)
"""

from src.core.keyword.extractor import KeywordExtractor
from src.core.keyword.llm_base import ExtractedKeywords, JudgeResult
from src.core.keyword.patterns import (
    extract_title_acronyms,
    extract_abstract_acronyms,
)
from src.core.keyword.stopwords import STOPWORDS, is_valid_keyword

__all__ = [
    "KeywordExtractor",
    "ExtractedKeywords",
    "JudgeResult",
    "extract_title_acronyms",
    "extract_abstract_acronyms",
    "STOPWORDS",
    "is_valid_keyword",
]
