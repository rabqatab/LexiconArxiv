"""Topic clustering using UMAP + HDBSCAN."""

import logging
import time
from collections import Counter

import numpy as np
from qdrant_client.http import models
from sklearn.cluster import HDBSCAN
from umap import UMAP

from src.core.constants import EMBEDDING_VECTOR_NAME
from src.core.storage.base import QdrantStorage

logger = logging.getLogger(__name__)


def compute_clusters(
    storage: QdrantStorage,
    umap_n_components: int = 50,
    umap_n_neighbors: int = 15,
    hdbscan_min_cluster_size: int = 50,
    hdbscan_min_samples: int = 10,
    batch_size: int = 1000,
) -> dict:
    """Load vectors from Qdrant, run UMAP+HDBSCAN, label clusters.

    Returns dict with cluster assignments, UMAP 2D coordinates, and cluster metadata.
    """
    start = time.time()
    logger.info("Loading vectors from Qdrant...")

    # Scroll all non-stub papers with vectors
    vectors = []
    point_ids = []
    metadata = []  # (year, keywords_structured)
    offset = None

    scroll_filter = models.Filter(
        must_not=[
            models.FieldCondition(
                key="is_stub",
                match=models.MatchValue(value=True),
            ),
        ],
    )

    while True:
        results, next_offset = storage.client.scroll(
            collection_name=storage.collection_name,
            scroll_filter=scroll_filter,
            limit=batch_size,
            offset=offset,
            with_payload=["title", "year", "venue", "keywords_structured", "keywords"],
            with_vectors=[EMBEDDING_VECTOR_NAME],
        )

        if not results:
            break

        for point in results:
            vec = point.vector
            if isinstance(vec, dict):
                vec = vec.get(EMBEDDING_VECTOR_NAME)
            if vec and len(vec) > 0:
                vectors.append(vec)
                point_ids.append(str(point.id))
                metadata.append(point.payload or {})

        if next_offset is None:
            break
        offset = next_offset

        if len(vectors) % 10000 == 0:
            logger.info(f"Loaded {len(vectors):,} vectors...")

    if len(vectors) < hdbscan_min_cluster_size * 2:
        logger.warning(f"Too few vectors ({len(vectors)}) for clustering")
        return {"error": "Too few vectors for clustering", "count": len(vectors)}

    logger.info(f"Loaded {len(vectors):,} vectors. Running UMAP...")

    X = np.array(vectors, dtype=np.float32)
    del vectors  # Free memory

    # UMAP: 1024d -> 50d (for HDBSCAN) + 2d (for visualization)
    umap_50d = UMAP(
        n_components=umap_n_components,
        n_neighbors=umap_n_neighbors,
        metric="cosine",
        random_state=42,
        low_memory=True,
    )
    embeddings_50d = umap_50d.fit_transform(X)
    logger.info("UMAP 50d complete. Running UMAP 2d for visualization...")

    umap_2d = UMAP(
        n_components=2,
        n_neighbors=umap_n_neighbors,
        metric="cosine",
        random_state=42,
        low_memory=True,
    )
    embeddings_2d = umap_2d.fit_transform(X)
    del X  # Free memory
    logger.info("UMAP 2d complete. Running HDBSCAN...")

    # HDBSCAN clustering on 50d embeddings
    clusterer = HDBSCAN(
        min_cluster_size=hdbscan_min_cluster_size,
        min_samples=hdbscan_min_samples,
    )
    labels = clusterer.fit_predict(embeddings_50d)
    logger.info(f"HDBSCAN complete. Found {len(set(labels)) - (1 if -1 in labels else 0)} clusters")

    # Build cluster metadata
    clusters = _build_cluster_metadata(labels, metadata)

    elapsed = time.time() - start
    logger.info(f"Clustering complete in {elapsed:.1f}s")

    return {
        "point_ids": point_ids,
        "labels": labels.tolist(),
        "umap_x": embeddings_2d[:, 0].tolist(),
        "umap_y": embeddings_2d[:, 1].tolist(),
        "clusters": clusters,
        "num_papers": len(point_ids),
        "num_clusters": len(clusters),
        "noise_count": int((labels == -1).sum()),
        "elapsed_seconds": round(elapsed, 1),
    }


def _build_cluster_metadata(labels: np.ndarray, metadata: list[dict]) -> list[dict]:
    """Extract top keywords and year distribution per cluster."""
    cluster_ids = set(labels)
    cluster_ids.discard(-1)

    clusters = []
    for cid in sorted(cluster_ids):
        mask = labels == cid
        cluster_meta = [m for m, in_cluster in zip(metadata, mask) if in_cluster]

        # Count keywords across all papers in cluster
        keyword_counter: Counter = Counter()
        year_counter: Counter = Counter()
        for m in cluster_meta:
            ks = m.get("keywords_structured", {}) or {}
            for category_keywords in ks.values():
                if isinstance(category_keywords, list):
                    for kw in category_keywords:
                        keyword_counter[kw.lower()] += 1
            # Fallback to flat keywords
            if not keyword_counter:
                for kw in m.get("keywords", []) or []:
                    keyword_counter[kw.lower()] += 1
            year = m.get("year")
            if year:
                year_counter[str(year)] += 1

        top_kw = [kw for kw, _ in keyword_counter.most_common(10)]
        label = ", ".join(top_kw[:3]) if top_kw else f"Cluster {cid}"

        clusters.append({
            "cluster_id": int(cid),
            "label": label,
            "size": int(mask.sum()),
            "top_keywords": top_kw,
            "year_distribution": dict(year_counter),
        })

    return clusters


def store_cluster_results(storage: QdrantStorage, results: dict) -> int:
    """Write cluster_id, umap_x, umap_y back to Qdrant payloads."""
    point_ids = results["point_ids"]
    labels = results["labels"]
    umap_x = results["umap_x"]
    umap_y = results["umap_y"]

    updated = 0
    batch_size = 100

    for i in range(0, len(point_ids), batch_size):
        batch_ids = point_ids[i : i + batch_size]
        batch_labels = labels[i : i + batch_size]
        batch_x = umap_x[i : i + batch_size]
        batch_y = umap_y[i : i + batch_size]

        for pid, lbl, x, y in zip(batch_ids, batch_labels, batch_x, batch_y):
            storage.client.set_payload(
                collection_name=storage.collection_name,
                payload={
                    "cluster_id": int(lbl),
                    "umap_x": float(x),
                    "umap_y": float(y),
                },
                points=[pid],
            )
            updated += 1

        if updated % 10000 == 0:
            logger.info(f"Stored {updated:,} cluster assignments...")

    logger.info(f"Stored {updated:,} cluster assignments")
    return updated
