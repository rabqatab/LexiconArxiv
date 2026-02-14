"""Main keyword extraction class combining regex, KeyBERT, and LLM approaches.

LLM-first extraction pipeline:
1. LLM: Extract keywords via Gemini or Ollama (primary, always attempted)
2. Fallback: Regex + KeyBERT only when LLM is unavailable or produces nothing
3. Judge: Validate keywords via LLM judge (optional)
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

    from src.core.keyword.judge import KeywordJudge
    from src.core.keyword.llm_base import BaseLLMExtractor

logger = logging.getLogger(__name__)


class KeywordExtractor:
    """LLM-first keyword extractor for academic papers.

    Primary: LLM-based keyword extraction via Gemini or Ollama (always attempted)
    Fallback: Regex + KeyBERT only when LLM produces nothing
    Optional: LLM judge validation of extracted keywords

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
        embedding_model: str = "all-MiniLM-L6-v2",
        use_llm: bool = False,
        llm_backend: str = "gemini",
        use_judge: bool = False,
        judge_backend: str | None = None,
        ollama_model: str = "llama3.1:8b",
        gemini_model: str = "gemini-2.0-flash",
        ollama_timeout: float = 180.0,
    ):
        """Initialize keyword extractor.

        Args:
            use_keybert: Whether to use KeyBERT for semantic extraction.
            keybert_top_n: Maximum keywords to extract via KeyBERT.
            keybert_diversity: MMR diversity parameter (0-1).
            keybert_min_score: Minimum score threshold for KeyBERT keywords.
            min_keyword_length: Minimum keyword character length.
            max_keyword_length: Maximum keyword character length.
            embedding_model: Sentence-transformers model for KeyBERT.
            use_llm: Whether to use LLM for keyword extraction.
            llm_backend: LLM backend to use ("gemini" or "ollama").
            use_judge: Whether to use LLM judge for keyword validation.
            judge_backend: Judge backend ("gemini" or "ollama"). Defaults to llm_backend.
            ollama_model: Ollama model name.
            gemini_model: Gemini model name.
            ollama_timeout: Ollama request timeout in seconds.
        """
        self.use_keybert = use_keybert
        self.keybert_top_n = keybert_top_n
        self.keybert_diversity = keybert_diversity
        self.keybert_min_score = keybert_min_score
        self.min_keyword_length = min_keyword_length
        self.max_keyword_length = max_keyword_length
        self.embedding_model = embedding_model

        self.use_llm = use_llm
        self.llm_backend = llm_backend
        self.use_judge = use_judge
        self.judge_backend = judge_backend or llm_backend
        self.ollama_model = ollama_model
        self.gemini_model = gemini_model
        self.ollama_timeout = ollama_timeout

        self._kw_model: "KeyBERT | None" = None
        self._keybert_initialized = False
        self._llm_extractor: "BaseLLMExtractor | None" = None
        self._judge: "KeywordJudge | None" = None

    def _ensure_keybert(self) -> "KeyBERT | None":
        """Lazy-load KeyBERT model on first use."""
        if not self.use_keybert:
            return None

        if not self._keybert_initialized:
            try:
                from keybert import KeyBERT
                self._kw_model = KeyBERT(model=self.embedding_model)
                logger.info(
                    f"KeyBERT model loaded (embedding: {self.embedding_model})"
                )
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

    def _ensure_llm_extractor(self) -> "BaseLLMExtractor | None":
        """Lazy-create LLM extractor on first use."""
        if self._llm_extractor is not None:
            return self._llm_extractor

        try:
            if self.llm_backend == "gemini":
                from src.core.keyword.gemini import GeminiKeywordExtractor
                self._llm_extractor = GeminiKeywordExtractor(model=self.gemini_model)
            elif self.llm_backend == "ollama":
                from src.core.keyword.ollama import OllamaKeywordExtractor
                self._llm_extractor = OllamaKeywordExtractor(
                    model=self.ollama_model, timeout=self.ollama_timeout
                )
            else:
                logger.warning(f"Unknown LLM backend: {self.llm_backend}")
                return None

            logger.info(f"LLM extractor initialized ({self.llm_backend})")
        except Exception as e:
            logger.warning(f"Failed to initialize LLM extractor: {e}")
            return None

        return self._llm_extractor

    def _ensure_judge(self) -> "KeywordJudge | None":
        """Lazy-create keyword judge on first use."""
        if self._judge is not None:
            return self._judge

        try:
            from src.core.keyword.judge import KeywordJudge

            if self.judge_backend == "gemini":
                from src.core.keyword.gemini import GeminiJudge
                backend = GeminiJudge(model=self.gemini_model)
            elif self.judge_backend == "ollama":
                from src.core.keyword.ollama import OllamaJudge
                backend = OllamaJudge(
                    model=self.ollama_model, timeout=self.ollama_timeout
                )
            else:
                logger.warning(f"Unknown judge backend: {self.judge_backend}")
                return None

            self._judge = KeywordJudge(backend=backend)
            logger.info(f"Keyword judge initialized ({self.judge_backend})")
        except Exception as e:
            logger.warning(f"Failed to initialize judge: {e}")
            return None

        return self._judge

    def extract(self, title: str, abstract: str | None = None) -> list[str]:
        """Extract keywords from title and abstract (sync, regex + KeyBERT only).

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

    async def extract_pipeline(
        self, title: str, abstract: str | None = None
    ) -> list[str]:
        """Extract keywords using the LLM-first async pipeline.

        LLM (primary) -> fallback: regex + KeyBERT -> normalize -> Judge

        Args:
            title: Paper title.
            abstract: Paper abstract (optional).

        Returns:
            List of unique, validated keywords.
        """
        keywords, _, _ = await self.extract_pipeline_with_source(title, abstract)
        return keywords

    async def extract_pipeline_with_source(
        self, title: str, abstract: str | None = None
    ) -> tuple[list[str], str, dict[str, list[str]] | None]:
        """Extract keywords using the LLM-first pipeline, with source tracking.

        Primary: LLM extraction (always attempted, even without abstract).
        Fallback: Regex + KeyBERT only when LLM produced nothing.

        Args:
            title: Paper title.
            abstract: Paper abstract (optional).

        Returns:
            Tuple of (keywords, pipe-delimited source string, structured_categories).
            structured_categories is a dict with keys task/method/model/domain/dataset,
            or None if LLM extraction was not used or failed.
        """
        sources: list[str] = []
        keywords: list[str] = []
        structured: dict[str, list[str]] | None = None

        # Primary: LLM extraction (always attempted)
        if self.use_llm:
            llm_extractor = self._ensure_llm_extractor()
            if llm_extractor:
                from src.core.keyword.llm_base import BaseLLMExtractor

                result = await llm_extractor.extract_keywords(title, abstract)
                if result:
                    keywords.extend(BaseLLMExtractor._flatten_extraction(result))
                    structured = result.to_dict()
                    sources.append(self.llm_backend)

        # Fallback: regex + KeyBERT (only if LLM produced nothing)
        if not keywords:
            regex_kws = self.extract_regex_only(title, abstract)
            if regex_kws:
                keywords.extend(regex_kws)
                sources.append("regex")

            if self.use_keybert and abstract:
                keybert_kws = self._extract_keybert(abstract)
                if keybert_kws:
                    keywords.extend(keybert_kws)
                    sources.append("keybert")

        # Normalize before judge
        keywords = self._normalize_keywords(keywords)

        # Judge
        if self.use_judge and keywords:
            judge = self._ensure_judge()
            if judge:
                keywords = await judge.filter_keywords(title, abstract, keywords)
                sources.append("judge")

        source = "|".join(sources) if sources else "none"
        return keywords, source, structured

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

    async def close(self) -> None:
        """Clean up LLM and judge resources."""
        if self._llm_extractor:
            await self._llm_extractor.close()
            self._llm_extractor = None
        if self._judge:
            await self._judge.close()
            self._judge = None
