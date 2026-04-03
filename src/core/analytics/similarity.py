"""Precompute typed semantic similarity edges between papers."""

import logging
import time

from qdrant_client import models

from src.core.constants import SECTION_VECTOR_PREFIX, STRUCTURED_VECTOR_NAME
from src.core.storage.base import QdrantStorage

logger = logging.getLogger(__name__)

# Edge types: (name, source_vector, target_vector)
EDGE_TYPES = {
    "same_method": (f"{SECTION_VECTOR_PREFIX}method", f"{SECTION_VECTOR_PREFIX}method"),
    "same_task": (f"{SECTION_VECTOR_PREFIX}task", f"{SECTION_VECTOR_PREFIX}task"),
    "same_result": (f"{SECTION_VECTOR_PREFIX}result", f"{SECTION_VECTOR_PREFIX}result"),
    "method_transfer": (f"{SECTION_VECTOR_PREFIX}method", f"{SECTION_VECTOR_PREFIX}result"),
    "overall": (STRUCTURED_VECTOR_NAME, STRUCTURED_VECTOR_NAME),
}


def compute_similarity_for_paper(
    storage: QdrantStorage,
    paper_id: str,
    paper_vectors: dict[str, list[float]],
    k: int = 10,
    edge_types: dict | None = None,
) -> dict[str, list[dict]]:
    """Find top-K similar papers per edge type for a single paper.

    Uses query_batch_points to send all edge type queries in one HTTP call.
    """
    types = edge_types or EDGE_TYPES

    # Build all queries for this paper
    query_requests = []
    edge_names = []

    for edge_name, (source_vec_name, target_vec_name) in types.items():
        query_vector = paper_vectors.get(source_vec_name)
        if not query_vector or len(query_vector) == 0:
            continue

        query_requests.append(
            models.QueryRequest(
                query=query_vector,
                using=target_vec_name,
                filter=models.Filter(
                    must_not=[
                        models.FieldCondition(
                            key="is_stub", match=models.MatchValue(value=True)
                        ),
                        models.HasIdCondition(has_id=[paper_id]),
                    ]
                ),
                limit=k,
                with_payload=models.PayloadSelectorInclude(
                    include=["title", "venue", "year"],
                ),
            )
        )
        edge_names.append(edge_name)

    if not query_requests:
        return {}

    # Single batch call for all edge types
    try:
        batch_results = storage.client.query_batch_points(
            collection_name=storage.collection_name,
            requests=query_requests,
        )
    except Exception as e:
        logger.warning(f"Batch similarity search failed for {paper_id}: {e}")
        return {}

    results = {}
    for edge_name, search_result in zip(edge_names, batch_results):
        points = search_result.points if hasattr(search_result, 'points') else []
        results[edge_name] = [
            {
                "id": str(p.id),
                "score": round(p.score, 4),
                "title": (p.payload or {}).get("title", ""),
                "venue": (p.payload or {}).get("venue"),
                "year": (p.payload or {}).get("year"),
            }
            for p in points
        ]

    return results


def _compute_batch_similarities(
    storage: QdrantStorage,
    papers: list,
    k: int,
    types: dict,
) -> list[dict]:
    """Compute similarities for a batch of papers in one mega batch call.

    Sends all queries for all papers in the batch as a single HTTP request.
    E.g., 50 papers × 5 edge types = 250 queries in one call.
    """
    query_requests = []
    query_map = []  # (paper_index, edge_name)

    for i, point in enumerate(papers):
        paper_id = str(point.id)
        vectors = point.vector if isinstance(point.vector, dict) else {}
        if not vectors:
            continue

        for edge_name, (source_vec_name, target_vec_name) in types.items():
            query_vector = vectors.get(source_vec_name)
            if not query_vector or len(query_vector) == 0:
                continue

            query_requests.append(
                models.QueryRequest(
                    query=query_vector,
                    using=target_vec_name,
                    filter=models.Filter(
                        must_not=[
                            models.FieldCondition(
                                key="is_stub", match=models.MatchValue(value=True)
                            ),
                            models.HasIdCondition(has_id=[paper_id]),
                        ]
                    ),
                    limit=k,
                    with_payload=models.PayloadSelectorInclude(
                        include=["title", "venue", "year"],
                    ),
                )
            )
            query_map.append((i, edge_name))

    if not query_requests:
        return [{} for _ in papers]

    # Single mega batch call
    try:
        batch_results = storage.client.query_batch_points(
            collection_name=storage.collection_name,
            requests=query_requests,
        )
    except Exception as e:
        logger.error(f"Mega batch similarity failed: {e}")
        return [{} for _ in papers]

    # Distribute results back to per-paper dicts
    paper_similarities = [{} for _ in papers]
    for (paper_idx, edge_name), search_result in zip(query_map, batch_results):
        points = search_result.points if hasattr(search_result, 'points') else []
        paper_similarities[paper_idx][edge_name] = [
            {
                "id": str(p.id),
                "score": round(p.score, 4),
                "title": (p.payload or {}).get("title", ""),
                "venue": (p.payload or {}).get("venue"),
                "year": (p.payload or {}).get("year"),
            }
            for p in points
        ]

    return paper_similarities


def compute_similarity_batch(
    storage: QdrantStorage,
    k: int = 10,
    batch_size: int = 20,
    limit: int | None = None,
    edge_types: dict | None = None,
) -> dict:
    """Compute similarity for all papers using batched Qdrant queries.

    Sends batch_size × 5 queries per HTTP call via query_batch_points.
    """
    start = time.time()
    types = edge_types or EDGE_TYPES

    source_vectors = list(set(src for src, _ in types.values()))

    processed = 0
    updated = 0
    offset = None

    while True:
        results, next_offset = storage.client.scroll(
            collection_name=storage.collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.HasVectorCondition(has_vector=STRUCTURED_VECTOR_NAME),
                ],
                must_not=[
                    models.FieldCondition(
                        key="is_stub", match=models.MatchValue(value=True)
                    ),
                ],
            ),
            limit=batch_size,
            offset=offset,
            with_payload=["title"],
            with_vectors=source_vectors,
        )

        if not results:
            break

        # Compute all similarities for the batch in one call
        batch_similarities = _compute_batch_similarities(storage, results, k, types)

        # Store results
        for point, similar in zip(results, batch_similarities):
            if similar:
                storage.client.set_payload(
                    collection_name=storage.collection_name,
                    payload={"similar_papers": similar},
                    points=[str(point.id)],
                )
                updated += 1
            processed += 1

        if processed % 1000 == 0:
            elapsed = time.time() - start
            rate = processed / elapsed if elapsed > 0 else 0
            logger.info(f"Processed {processed:,} papers ({updated:,} updated, {rate:.0f} papers/min)...")

        if limit and processed >= limit:
            break
        if next_offset is None:
            break
        offset = next_offset

    elapsed = time.time() - start
    logger.info(f"Similarity computation complete: {processed:,} papers, {updated:,} updated in {elapsed:.1f}s")

    return {
        "processed": processed,
        "updated": updated,
        "elapsed_seconds": round(elapsed, 1),
        "edge_types": list(types.keys()),
        "k": k,
    }
