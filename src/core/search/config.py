"""Retrieval pipeline configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetrievalConfig:
    """Toggle each retrieval technique on/off."""

    # Stage 1: Query Analysis
    query_intent: bool = True  # Auto-detect section target
    hyde: bool = False  # Hypothetical document embedding (+500ms)
    rag_fusion: bool = False  # Multi-query variants (+500ms)
    query_decomposition: bool = False  # Split a multi-part query into sub-queries (+500ms)

    # Stage 2: Multi-vector retrieval
    multi_vector: bool = True
    adaptive_rrf: bool = False  # Tilt dense vs BM25 candidate share by query shape

    # Stage 3.5: Neural pseudo-relevance feedback (2-pass)
    neural_prf: bool = False  # Refine query with mean of top-K result vectors (+1 round-trip)
    prf_top_k: int = 5
    multi_vector_names: list[str] = field(
        default_factory=lambda: [
            "structured-abstract",
            "section-method",
            "section-task",
        ]
    )

    # Stage 4: Reranking
    reranker: bool = False
    rerank_top_k: int = 50

    # Stage 5: Post-processing
    citation_boost: bool = True
    citation_alpha: float = 0.6  # retrieval score weight
    citation_beta: float = 0.2  # citation weight
    citation_gamma: float = 0.2  # pagerank weight
    mmr_diversity: bool = False
    mmr_lambda: float = 0.7

    @classmethod
    def fast(cls) -> RetrievalConfig:
        """Fast search: defaults only (query_intent + multi_vector + citation_boost)."""
        return cls()

    @classmethod
    def quality(cls) -> RetrievalConfig:
        """Quality search: adds HyDE, reranker, and MMR diversity."""
        return cls(hyde=True, reranker=True, mmr_diversity=True)

    @classmethod
    def comprehensive(cls) -> RetrievalConfig:
        """Comprehensive search: RAG-Fusion + decomposition + PRF + adaptive RRF
        + reranker + MMR diversity — every recall-boosting stage on."""
        return cls(
            rag_fusion=True,
            query_decomposition=True,
            neural_prf=True,
            adaptive_rrf=True,
            reranker=True,
            mmr_diversity=True,
        )
