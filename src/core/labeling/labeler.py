"""Main abstract labeling class using LLM backends.

LLM-only pipeline: split abstract with pysbd, classify sentences by index
via Ollama, map labels back to verbatim sentences.
"""

import logging
import re
from typing import TYPE_CHECKING

import pysbd

if TYPE_CHECKING:
    from src.core.labeling.llm_base import BaseAbstractLabeler

from src.core.labeling.llm_base import (
    build_abstract_structure,
    format_numbered_sentences,
)

logger = logging.getLogger(__name__)

_segmenter = pysbd.Segmenter(language="en", clean=False)


class AbstractLabeler:
    """LLM-based abstract sentence labeler for academic papers.

    Splits abstracts into sentences deterministically using pysbd,
    then sends numbered sentences to the LLM which returns only
    index-based label assignments. Sentences are guaranteed verbatim.

    Example:
        >>> labeler = AbstractLabeler(llm_backend="ollama")
        >>> structure, source = await labeler.label_abstract(
        ...     title="Attention Is All You Need",
        ...     abstract="We propose a new simple network architecture..."
        ... )
        >>> print(structure)
        {'task': [...], 'domain': [...], ...}
    """

    def __init__(
        self,
        llm_backend: str = "ollama",
        # Selected by the 2026-06-19 labeling LLM benchmark (100% schema-reliable,
        # 4.7s/abstract, 0.912 agreement). Documented fallback: gemma4:e4b (more
        # accurate at 0.942 but ~4x slower). See docs/reference/labeling-llm-comparison.md.
        ollama_model: str = "granite4.1:8b",
        ollama_timeout: float = 180.0,
    ):
        self.llm_backend = llm_backend
        self.ollama_model = ollama_model
        self.ollama_timeout = ollama_timeout

        self._llm_labeler: "BaseAbstractLabeler | None" = None

    def _ensure_llm_labeler(self) -> "BaseAbstractLabeler | None":
        """Lazy-create LLM labeler on first use."""
        if self._llm_labeler is not None:
            return self._llm_labeler

        try:
            if self.llm_backend == "ollama":
                from src.core.labeling.ollama import OllamaAbstractLabeler
                self._llm_labeler = OllamaAbstractLabeler(
                    model=self.ollama_model, timeout=self.ollama_timeout
                )
            else:
                logger.warning(
                    f"Unsupported LLM backend '{self.llm_backend}' (only 'ollama' is supported)"
                )
                return None

            logger.info(f"Abstract labeler initialized ({self.llm_backend})")
        except Exception as e:
            logger.warning(f"Failed to initialize abstract labeler: {e}")
            return None

        return self._llm_labeler

    async def label_abstract(
        self, title: str, abstract: str
    ) -> tuple[dict | None, str]:
        """Label an abstract's sentences into rhetorical roles.

        1. Split abstract into sentences with pysbd
        2. Send numbered sentences to LLM
        3. LLM returns index → labels mapping
        4. Map indices back to verbatim sentences

        Args:
            title: Paper title.
            abstract: Paper abstract.

        Returns:
            Tuple of (structure_dict, source) where source is
            "ollama" or "none".
        """
        labeler = self._ensure_llm_labeler()
        if labeler is None:
            return None, "none"

        # Step 1: Normalize and split into sentences
        clean = abstract.replace("\\n", " ")
        clean = re.sub(r"\s+", " ", clean).strip()
        sentences = [s.strip() for s in _segmenter.segment(clean) if s.strip()]
        if not sentences:
            return None, "none"

        # Step 2: Format numbered sentences for LLM
        numbered = format_numbered_sentences(sentences)

        # Step 3: LLM classifies by index (full abstract passed for context)
        labels = await labeler.label_sentences(title, clean, numbered, len(sentences))
        if labels is None:
            return None, "none"

        # Step 4: Map indices back to verbatim sentences
        structure = build_abstract_structure(sentences, labels)
        return structure.to_dict(), self.llm_backend

    async def close(self) -> None:
        """Clean up LLM resources."""
        if self._llm_labeler:
            await self._llm_labeler.close()
            self._llm_labeler = None
