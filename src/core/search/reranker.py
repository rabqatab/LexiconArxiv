"""Cross-encoder reranking using Qwen3-Reranker via sentence-transformers."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

RERANKER_MODEL = "tomaarsen/Qwen3-Reranker-0.6B-seq-cls"


class Reranker:
    """Lazy-loaded cross-encoder reranker."""

    def __init__(self, model_name: str = RERANKER_MODEL):
        self._model_name = model_name
        self._model = None  # CrossEncoder instance, loaded on demand

    def load(self) -> None:
        """Load the model (call once at startup)."""
        from sentence_transformers import CrossEncoder

        logger.info("Loading reranker: %s ...", self._model_name)
        self._model = CrossEncoder(self._model_name, trust_remote_code=True)
        logger.info("Reranker loaded")

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def rerank(
        self,
        query: str,
        results: list[dict],
        top_k: int = 20,
    ) -> list[dict]:
        """Rerank results using cross-encoder scores.

        Args:
            query: Original user query.
            results: List of result dicts (must contain ``title`` and
                optionally ``abstract``).
            top_k: How many results to keep after reranking.

        Returns:
            Re-sorted list trimmed to *top_k*.
        """
        if not self._model or not results:
            return results[:top_k]

        # Build (query, document) pairs
        pairs = []
        for r in results:
            doc = f"{r.get('title', '')}. {r.get('abstract', '') or ''}"
            pairs.append((query, doc))

        # Score all pairs
        scores = self._model.predict(pairs)

        # Attach scores and re-sort
        for r, score in zip(results, scores):
            r["reranker_score"] = float(score)

        results.sort(key=lambda x: x.get("reranker_score", 0), reverse=True)
        return results[:top_k]
