"""Main keyword extraction class combining regex and KeyBERT approaches.

Two-phase extraction pipeline:
1. Regex: Extract explicit acronyms from title/abstract
2. KeyBERT: Extract semantic keywords from abstract (optional)
"""

import logging
from typing import TYPE_CHECKING

from src.core.keyword.patterns import (
    extract_title_acronyms,
    extract_abstract_acronyms,
)
from src.core.keyword.stopwords import is_valid_keyword

if TYPE_CHECKING:
    from keybert import KeyBERT

logger = logging.getLogger(__name__)


class KeywordExtractor:
    """Two-phase keyword extractor for academic papers.

    Phase 1: Regex-based acronym extraction from title and abstract
    Phase 2: KeyBERT semantic keyword extraction from abstract (optional)

    Example:
        >>> extractor = KeywordExtractor(use_keybert=True)
        >>> keywords = extractor.extract(
        ...     title="BERT: Pre-training of Deep Bidirectional Transformers",
        ...     abstract="We introduce BERT, a new language representation model..."
        ... )
        >>> print(keywords)
        ['BERT', 'language representation', 'pre-training', 'transformer']
    """

    def __init__(
        self,
        use_keybert: bool = True,
        keybert_top_n: int = 5,
        keybert_diversity: float = 0.7,
        keybert_min_score: float = 0.3,
        min_keyword_length: int = 2,
        max_keyword_length: int = 15,
    ):
        """Initialize keyword extractor.

        Args:
            use_keybert: Whether to use KeyBERT for semantic extraction.
            keybert_top_n: Maximum keywords to extract via KeyBERT.
            keybert_diversity: MMR diversity parameter (0-1).
            keybert_min_score: Minimum score threshold for KeyBERT keywords.
            min_keyword_length: Minimum keyword character length.
            max_keyword_length: Maximum keyword character length.
        """
        self.use_keybert = use_keybert
        self.keybert_top_n = keybert_top_n
        self.keybert_diversity = keybert_diversity
        self.keybert_min_score = keybert_min_score
        self.min_keyword_length = min_keyword_length
        self.max_keyword_length = max_keyword_length

        self._kw_model: "KeyBERT | None" = None
        self._keybert_initialized = False

    def _ensure_keybert(self) -> "KeyBERT | None":
        """Lazy-load KeyBERT model on first use."""
        if not self.use_keybert:
            return None

        if not self._keybert_initialized:
            try:
                from keybert import KeyBERT
                self._kw_model = KeyBERT()
                logger.info("KeyBERT model loaded successfully")
            except ImportError:
                logger.warning(
                    "KeyBERT not installed. Install with: pip install keybert"
                )
                self.use_keybert = False
            except Exception as e:
                logger.warning(f"Failed to load KeyBERT: {e}")
                self.use_keybert = False
            self._keybert_initialized = True

        return self._kw_model

    def extract(self, title: str, abstract: str | None = None) -> list[str]:
        """Extract keywords from title and abstract.

        Phase 1: Regex extraction for acronyms
        Phase 2: KeyBERT extraction for semantic keywords (if enabled)

        Args:
            title: Paper title.
            abstract: Paper abstract (optional).

        Returns:
            List of unique keywords, preserving original case.
        """
        keywords: list[str] = []

        # Phase 1: Regex-based acronym extraction
        keywords.extend(extract_title_acronyms(title))
        if abstract:
            keywords.extend(extract_abstract_acronyms(abstract))

        # Phase 2: KeyBERT semantic extraction
        if self.use_keybert and abstract:
            keybert_keywords = self._extract_keybert(abstract)
            keywords.extend(keybert_keywords)

        # Final deduplication and validation
        return self._normalize_keywords(keywords)

    def extract_regex_only(self, title: str, abstract: str | None = None) -> list[str]:
        """Extract keywords using only regex patterns (no KeyBERT).

        Args:
            title: Paper title.
            abstract: Paper abstract (optional).

        Returns:
            List of acronyms extracted via regex.
        """
        keywords: list[str] = []
        keywords.extend(extract_title_acronyms(title))
        if abstract:
            keywords.extend(extract_abstract_acronyms(abstract))
        return self._normalize_keywords(keywords)

    def _extract_keybert(self, abstract: str) -> list[str]:
        """Extract semantic keywords using KeyBERT.

        Args:
            abstract: Paper abstract text.

        Returns:
            List of keywords above the minimum score threshold.
        """
        kw_model = self._ensure_keybert()
        if kw_model is None:
            return []

        try:
            results = kw_model.extract_keywords(
                abstract,
                keyphrase_ngram_range=(1, 2),
                stop_words='english',
                top_n=self.keybert_top_n,
                use_mmr=True,
                diversity=self.keybert_diversity,
            )

            # Filter by score and validate
            keywords = []
            for keyword, score in results:
                if score >= self.keybert_min_score:
                    # KeyBERT may return phrases; validate each word
                    words = keyword.split()
                    if len(words) <= 2:  # Keep 1-2 word phrases
                        keywords.append(keyword)

            return keywords

        except Exception as e:
            logger.warning(f"KeyBERT extraction failed: {e}")
            return []

    def _normalize_keywords(self, keywords: list[str]) -> list[str]:
        """Normalize and deduplicate keywords.

        Args:
            keywords: List of keyword candidates.

        Returns:
            Deduplicated list with original case preserved.
        """
        seen: set[str] = set()
        result: list[str] = []

        for kw in keywords:
            kw = kw.strip()

            # Basic validation
            if not kw:
                continue
            if len(kw) < self.min_keyword_length:
                continue
            if len(kw) > self.max_keyword_length:
                continue

            # Case-insensitive deduplication
            kw_lower = kw.lower()
            if kw_lower not in seen:
                seen.add(kw_lower)
                result.append(kw)

        return result

    def get_extraction_source(
        self, title: str, abstract: str | None = None
    ) -> str:
        """Determine which extraction methods produced keywords.

        Args:
            title: Paper title.
            abstract: Paper abstract (optional).

        Returns:
            One of: "regex", "keybert", "both", "none"
        """
        has_regex = bool(self.extract_regex_only(title, abstract))

        has_keybert = False
        if self.use_keybert and abstract:
            keybert_kws = self._extract_keybert(abstract)
            has_keybert = bool(keybert_kws)

        if has_regex and has_keybert:
            return "both"
        elif has_regex:
            return "regex"
        elif has_keybert:
            return "keybert"
        else:
            return "none"
