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
        # vLLM backend for high-throughput bootstrap labeling — 100× the
        # Ollama serial throughput via continuous batching. Same granite
        # family as the Ollama default so quality risk is minimized;
        # requires re-eval before production per the migration design.
        # See docs/design/vllm-labeling-migration.md.
        vllm_model: str = "ibm-granite/granite-4.1-8b",
        vllm_base_url: str = "http://localhost:8000",
        vllm_max_concurrent: int = 64,
        vllm_timeout: float = 180.0,
    ):
        self.llm_backend = llm_backend
        self.ollama_model = ollama_model
        self.ollama_timeout = ollama_timeout
        self.vllm_model = vllm_model
        self.vllm_base_url = vllm_base_url
        self.vllm_max_concurrent = vllm_max_concurrent
        self.vllm_timeout = vllm_timeout

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
            elif self.llm_backend == "vllm":
                from src.core.labeling.vllm import VLLMAbstractLabeler
                self._llm_labeler = VLLMAbstractLabeler(
                    model=self.vllm_model,
                    base_url=self.vllm_base_url,
                    max_concurrent=self.vllm_max_concurrent,
                    timeout=self.vllm_timeout,
                )
            else:
                logger.warning(
                    f"Unsupported LLM backend '{self.llm_backend}' "
                    f"(supported: 'ollama', 'vllm')"
                )
                return None

            logger.info(f"Abstract labeler initialized ({self.llm_backend})")
        except Exception as e:
            logger.warning(f"Failed to initialize abstract labeler: {e}")
            return None

        return self._llm_labeler

    async def label_abstract(
        self, title: str, abstract: str,
        max_sentences_to_label: int = 25,
    ) -> tuple[dict | None, str]:
        """Label an abstract's sentences into rhetorical roles.

        1. Split abstract into sentences with pysbd
        2. Send first ``max_sentences_to_label`` numbered sentences to LLM
           (2026-07-06 discovery: real corpus abstracts have p90=25647 chars
           / ~50 sentences; sending everything blows past vLLM's
           max_model_len and drops generation throughput to ~460 papers/hr.
           Truncating to the first 25 sentences keeps the labeling prompt
           short enough for vLLM's continuous batching to actually help.
           Trade-off: role labels for sentences beyond N are not
           produced. Full-abstract embedding vectors (abstract-qwen3-8b
           and the structured-abstract fallback) still see the whole
           text, so semantic search remains unaffected — only the
           section-* vectors are biased toward the abstract's opening.)
        3. LLM returns index → labels mapping
        4. Map indices back to verbatim sentences

        Args:
            title: Paper title.
            abstract: Paper abstract.
            max_sentences_to_label: Cap on how many sentences we send to
                the LLM. Defaults to 25. Set to ``None`` to disable
                truncation (matches the pre-2026-07-06 behaviour).

        Returns:
            Tuple of (structure_dict, source) where source is
            "ollama" / "vllm" / "none".
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

        # Step 1b: Cap for LLM only. Downstream vectorization still sees
        # the full abstract via the storage payload.
        if max_sentences_to_label is not None:
            llm_sentences = sentences[:max_sentences_to_label]
        else:
            llm_sentences = sentences

        # Step 2: Format numbered sentences for LLM
        numbered = format_numbered_sentences(llm_sentences)

        # Step 3: LLM classifies by index (truncated abstract passed for context)
        # Provide the LLM the same slice it will be scoring against so the
        # sentence indices match the "abstract" context it sees.
        llm_context = " ".join(llm_sentences)
        labels = await labeler.label_sentences(title, llm_context, numbered, len(llm_sentences))
        if labels is None:
            return None, "none"

        # Step 4: Map indices back to verbatim sentences from the SAME
        # slice we sent to the LLM (or the full list when truncation off).
        structure = build_abstract_structure(llm_sentences, labels)
        return structure.to_dict(), self.llm_backend

    async def close(self) -> None:
        """Clean up LLM resources."""
        if self._llm_labeler:
            await self._llm_labeler.close()
            self._llm_labeler = None
