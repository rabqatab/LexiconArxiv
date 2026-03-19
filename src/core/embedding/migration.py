"""Collection migration: payload-only -> vector-enabled collection."""

import logging
import time

from qdrant_client import QdrantClient, models

from src.core.constants import (
    ALL_DENSE_VECTORS,
    EMBEDDING_VECTOR_SIZE,
    get_qdrant_url,
)

logger = logging.getLogger(__name__)

SCROLL_BATCH_SIZE = 100


class CollectionMigrator:
    """Migrate a payload-only Qdrant collection to one with vector configs."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        old_collection: str = "lexicon_arxiv",
        new_collection: str | None = None,
    ):
        self.client = QdrantClient(url=url or get_qdrant_url(), api_key=api_key or None)
        self.old_collection = old_collection
        self.new_collection = new_collection or f"{old_collection}_v2"

    def migrate(
        self,
        delete_old: bool = False,
        dense_vector_size: int = EMBEDDING_VECTOR_SIZE,
    ) -> dict:
        """Run the full migration. Returns dict with migration stats."""
        start = time.time()

        # 1. Snapshot backup
        logger.info(f"Creating snapshot of '{self.old_collection}'...")
        snapshot = self.client.create_snapshot(self.old_collection)
        logger.info(f"Snapshot created: {snapshot.name}")

        # 2. Create new collection with ALL dense vector configs + BM25 sparse
        logger.info(f"Creating new collection '{self.new_collection}'...")
        vectors_config = {
            name: models.VectorParams(
                size=dense_vector_size,
                distance=models.Distance.COSINE,
            )
            for name in ALL_DENSE_VECTORS
        }
        self.client.create_collection(
            collection_name=self.new_collection,
            vectors_config=vectors_config,
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                ),
            },
        )

        # 3. Scroll and re-insert all points (preserving existing vectors)
        points_migrated = 0
        offset = None

        while True:
            results, next_offset = self.client.scroll(
                collection_name=self.old_collection,
                limit=SCROLL_BATCH_SIZE,
                offset=offset,
                with_payload=True,
                with_vectors=True,  # Preserve existing vectors during migration
            )

            if not results:
                break

            points = []
            for point in results:
                vec = point.vector if point.vector else {}
                points.append(
                    models.PointStruct(
                        id=point.id,
                        vector=vec,
                        payload=point.payload,
                    )
                )

            self.client.upsert(
                collection_name=self.new_collection,
                points=points,
            )

            points_migrated += len(results)
            if points_migrated % 10000 == 0:
                logger.info(f"Migrated {points_migrated:,} points...")

            if next_offset is None:
                break
            offset = next_offset

        elapsed = time.time() - start
        logger.info(f"Migration complete: {points_migrated:,} points in {elapsed:.1f}s")

        # 4. Optionally delete old collection
        if delete_old:
            logger.info(f"Deleting old collection '{self.old_collection}'...")
            self.client.delete_collection(self.old_collection)

        # 5. Verify counts match
        old_count = self.client.count(self.old_collection).count if not delete_old else points_migrated
        new_count = self.client.count(self.new_collection).count

        return {
            "points_migrated": points_migrated,
            "old_count": old_count,
            "new_count": new_count,
            "elapsed_seconds": round(elapsed, 1),
            "snapshot_name": snapshot.name,
            "new_collection": self.new_collection,
        }
