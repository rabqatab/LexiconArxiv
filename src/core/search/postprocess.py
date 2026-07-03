"""Post-processing: citation boost and MMR diversity."""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


def apply_citation_boost(
    results: list[dict],
    alpha: float = 0.6,
    beta: float = 0.2,
    gamma: float = 0.2,
) -> list[dict]:
    """Re-score results using a weighted combination of retrieval score,
    log-scaled citation count, and PageRank.

    Args:
        results: Search result dicts (must contain ``score`` or
            ``reranker_score``, ``citation_count``, ``pagerank``).
        alpha: Weight for the retrieval / reranker score.
        beta: Weight for normalized citation count.
        gamma: Weight for normalized PageRank.

    Returns:
        The same list, sorted descending by the new ``score``.
    """
    if not results:
        return results

    # `.get(k, 0)` returns None when the payload has `k: None` (not missing).
    # P2 promotion writes some payloads with citation_count=None (source
    # snapshot lacked the value). Use `... or 0` to normalize both missing
    # and None to 0. Fixed 2026-07-03 — search endpoints were failing with
    # 'unsupported operand type(s) for +: int and NoneType'.
    max_citations = (
        max((math.log(1 + (r.get("citation_count") or 0)) for r in results), default=1)
        or 1
    )
    max_pagerank = max((r.get("pagerank") or 0 for r in results), default=1) or 1

    for r in results:
        retrieval = r.get("reranker_score") or r.get("score") or 0
        citations_norm = math.log(1 + (r.get("citation_count") or 0)) / max_citations
        pagerank_norm = (r.get("pagerank") or 0) / max_pagerank

        r["score"] = alpha * retrieval + beta * citations_norm + gamma * pagerank_norm

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def apply_mmr(
    results: list[dict],
    lambda_param: float = 0.7,
    limit: int = 20,
) -> list[dict]:
    """Maximal Marginal Relevance for result diversification.

    Uses keyword overlap as a lightweight similarity proxy so we don't need
    to fetch embedding vectors from Qdrant.

    Args:
        results: Pre-scored result dicts (``score`` must already be set).
        lambda_param: Trade-off between relevance (1.0) and diversity (0.0).
        limit: Maximum number of results to return.

    Returns:
        A diversified subset of *results* of length <= *limit*.
    """
    if len(results) <= limit:
        return results

    selected: list[int] = [0]  # Start with the top result
    remaining = list(range(1, len(results)))

    while len(selected) < limit and remaining:
        best_idx: int | None = None
        best_mmr = -float("inf")

        for idx in remaining:
            relevance = results[idx].get("score", 0)

            # Max similarity to already-selected results (keyword overlap)
            kw_i = set(k.lower() for k in results[idx].get("keywords", []))
            max_sim = 0.0
            for s_idx in selected:
                kw_s = set(k.lower() for k in results[s_idx].get("keywords", []))
                if kw_i and kw_s:
                    overlap = len(kw_i & kw_s) / max(len(kw_i | kw_s), 1)
                    max_sim = max(max_sim, overlap)

            mmr = lambda_param * relevance - (1 - lambda_param) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx

        if best_idx is not None:
            selected.append(best_idx)
            remaining.remove(best_idx)

    return [results[i] for i in selected]
