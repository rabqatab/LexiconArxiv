"""Main abstract labeling class using LLM backends.

LLM-only pipeline: classify abstract sentences into rhetorical roles
via Gemini or Ollama.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.labeling.llm_base import BaseAbstractLabeler

logger = logging.getLogger(__name__)


class AbstractLabeler:
    """LLM-based abstract sentence labeler for academic papers.

    Classifies each sentence in an abstract into rhetorical roles
    (task, domain, background, approach, method, result, contribution)
    using Gemini or Ollama.

    Example:
        >>> labeler = AbstractLabeler(llm_backend="gemini")
        >>> structure, source = await labeler.label_abstract(
        ...     title="Attention Is All You Need",
        ...     abstract="We propose a new simple network architecture..."
        ... )
        >>> print(structure)
        {'task': [...], 'domain': [...], ...}
    """

    def __init__(
        self,
        llm_backend: str = "gemini",
        ollama_model: str = "llama3.1:8b",
        gemini_model: str = "gemini-2.0-flash",
        ollama_timeout: float = 180.0,
    ):
        self.llm_backend = llm_backend
        self.ollama_model = ollama_model
        self.gemini_model = gemini_model
        self.ollama_timeout = ollama_timeout

        self._llm_labeler: "BaseAbstractLabeler | None" = None

    def _ensure_llm_labeler(self) -> "BaseAbstractLabeler | None":
        """Lazy-create LLM labeler on first use."""
        if self._llm_labeler is not None:
            return self._llm_labeler

        try:
            if self.llm_backend == "gemini":
                from src.core.labeling.gemini import GeminiAbstractLabeler
                self._llm_labeler = GeminiAbstractLabeler(model=self.gemini_model)
            elif self.llm_backend == "ollama":
                from src.core.labeling.ollama import OllamaAbstractLabeler
                self._llm_labeler = OllamaAbstractLabeler(
                    model=self.ollama_model, timeout=self.ollama_timeout
                )
            else:
                logger.warning(f"Unknown LLM backend: {self.llm_backend}")
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

        Args:
            title: Paper title.
            abstract: Paper abstract.

        Returns:
            Tuple of (structure_dict, source) where source is
            "gemini", "ollama", or "none".
        """
        labeler = self._ensure_llm_labeler()
        if labeler is None:
            return None, "none"

        result = await labeler.label_abstract(title, abstract)
        if result:
            return result.to_dict(), self.llm_backend

        return None, "none"

    async def close(self) -> None:
        """Clean up LLM resources."""
        if self._llm_labeler:
            await self._llm_labeler.close()
            self._llm_labeler = None
