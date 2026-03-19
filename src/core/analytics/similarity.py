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

    Args:
        storage: QdrantStorage instance
        paper_id: Point ID of the paper
        paper_vectors: Dict of vector_name -> vector values for this paper
        k: Number of neighbors per edge type
        edge_types: Which edge types to compute (default: all)

    Returns:
        Dict mapping edge_type -> list of {id, score, title, venue, year}
    """
    types = edge_types or EDGE_TYPES
    results = {}

    for edge_name, (source_vec_name, target_vec_name) in types.items():
        query_vector = paper_vectors.get(source_vec_name)
        if not query_vector or len(query_vector) == 0:
            continue

        try:
            search_results = storage.client.query_points(
                collection_name=storage.collection_name,
                query=query_vector,
                using=target_vec_name,
                query_filter=models.Filter(
                    must_not=[
                        models.FieldCondition(
                            key="is_stub", match=models.MatchValue(value=True)
                        ),
                        models.HasIdCondition(has_id=[paper_id]),
                    ]
                ),
                limit=k,
                with_payload=["title", "venue", "year"],
            )
            results[edge_name] = [
                {
                    "id": str(p.id),
                    "score": round(p.score, 4),
                    "title": (p.payload or {}).get("title", ""),
                    "venue": (p.payload or {}).get("venue"),
                    "year": (p.payload or {}).get("year"),
                }
                for p in search_results.points
            ]
        except Exception as e:
            logger.warning(f"Similarity search failed for {paper_id}/{edge_name}: {e}")
            continue

    return results


def compute_similarity_batch(
    storage: QdrantStorage,
    k: int = 10,
    batch_size: int = 50,
    limit: int | None = None,
    edge_types: dict | None = None,
) -> dict:
    """Compute similarity for all papers in batches.

    Returns stats dict.
    """
    start = time.time()
    types = edge_types or EDGE_TYPES

    # Need to know which vectors to fetch
    source_vectors = list(set(src for src, _ in types.values()))

    processed = 0
    updated = 0
    offset = None

    while True:
        # Scroll papers that have the structured-abstract vector
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
            with_payload=["title"],  # Minimal payload during scroll
            with_vectors=source_vectors,
        )

        if not results:
            break

        for point in results:
            paper_id = str(point.id)
            vectors = point.vector if isinstance(point.vector, dict) else {}

            if not vectors:
                continue

            similar = compute_similarity_for_paper(
                storage=storage,
                paper_id=paper_id,
                paper_vectors=vectors,
                k=k,
                edge_types=types,
            )

            if similar:
                storage.client.set_payload(
                    collection_name=storage.collection_name,
                    payload={"similar_papers": similar},
                    points=[paper_id],
                )
                updated += 1

            processed += 1
            if processed % 1000 == 0:
                logger.info(f"Processed {processed:,} papers ({updated:,} with similarity edges)...")

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
