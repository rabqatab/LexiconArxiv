"""Batch write operations for Qdrant storage.

Provides methods for updating paper fields in bulk.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)


class BatchWriter:
    """Handles batch update operations for papers."""

    def __init__(self, client: QdrantClient, collection_name: str):
        self.client = client
        self.collection_name = collection_name

    def update_referenced_works(
        self,
        point_id: str,
        referenced_works: list[str],
    ) -> bool:
        """Update referenced_works for a paper.

        Uses set_payload() to preserve other fields.

        Args:
            point_id: The Qdrant point ID.
            referenced_works: List of OpenAlex IDs to set.

        Returns:
            True if successful.
        """
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={"referenced_works": referenced_works},
            points=[point_id],
        )
        return True

    def batch_update_referenced_works(
        self,
        updates: list[tuple[str, list[str]]],  # [(point_id, refs), ...]
    ) -> int:
        """Batch update referenced_works for multiple papers.

        Args:
            updates: List of (point_id, referenced_works) tuples.

        Returns:
            Number of papers updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        for point_id, refs in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"referenced_works": refs, "enriched_at": now},
                points=[point_id],
            )
        return len(updates)

    def update_abstract(
        self,
        point_id: str,
        abstract: str,
    ) -> bool:
        """Update abstract for a paper.

        Uses set_payload() to preserve other fields.

        Args:
            point_id: The Qdrant point ID.
            abstract: The abstract text to set.

        Returns:
            True if successful.
        """
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={"abstract": abstract},
            points=[point_id],
        )
        return True

    def batch_update_abstracts(
        self,
        updates: list[tuple[str, str]],  # [(point_id, abstract), ...]
    ) -> int:
        """Batch update abstracts for multiple papers.

        Args:
            updates: List of (point_id, abstract) tuples.

        Returns:
            Number of papers updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        for point_id, abstract in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"abstract": abstract, "enriched_at": now},
                points=[point_id],
            )
        return len(updates)

    def update_paper_with_doi_and_refs(
        self,
        point_id: str,
        doi: str,
        referenced_works: list[str],
    ) -> bool:
        """Update paper with DOI and referenced_works found via title search.

        Args:
            point_id: The Qdrant point ID.
            doi: The DOI found via title search.
            referenced_works: List of OpenAlex IDs.

        Returns:
            True if successful.
        """
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={
                "doi": doi,
                "referenced_works": referenced_works,
            },
            points=[point_id],
        )
        return True

    def batch_update_papers_with_doi_and_refs(
        self,
        updates: list[tuple[str, str, list[str]]],  # [(point_id, doi, refs), ...]
    ) -> int:
        """Batch update papers with DOI and refs found via title search.

        Args:
            updates: List of (point_id, doi, referenced_works) tuples.

        Returns:
            Number of papers updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        for point_id, doi, refs in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={
                    "doi": doi,
                    "referenced_works": refs,
                    "enriched_at": now,
                },
                points=[point_id],
            )
        return len(updates)

    def batch_update_referenced_works_normalized(
        self,
        updates: list[tuple[str, list[str]]],  # [(point_id, normalized_refs), ...]
    ) -> int:
        """Batch update referenced_works with normalized identifiers.

        Args:
            updates: List of (point_id, normalized_referenced_works) tuples.

        Returns:
            Number of papers updated.
        """
        for point_id, refs in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"referenced_works": refs},
                points=[point_id],
            )
        return len(updates)

    def batch_update_resolved_references(
        self,
        updates: list[tuple[str, list[str]]],  # [(point_id, resolved_point_ids), ...]
    ) -> int:
        """Batch update resolved_references with internal paper IDs.

        Args:
            updates: List of (point_id, resolved_references) tuples where
                     resolved_references contains Qdrant point IDs.

        Returns:
            Number of papers updated.
        """
        for point_id, resolved_refs in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"resolved_references": resolved_refs},
                points=[point_id],
            )
        return len(updates)

    def batch_update_graph_metrics(
        self,
        updates: list[tuple[str, dict]],  # [(point_id, {metric: value}), ...]
    ) -> int:
        """Batch update graph metrics (pagerank, hub_score, etc.) for papers.

        Args:
            updates: List of (point_id, metrics_dict) tuples where
                     metrics_dict contains fields like pagerank, hub_score,
                     authority_score, community_id.

        Returns:
            Number of papers updated.
        """
        for point_id, metrics in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload=metrics,
                points=[point_id],
            )
        return len(updates)

    def batch_update_keywords(
        self,
        updates: list[tuple[str, list[str]]],  # [(point_id, keywords), ...]
    ) -> int:
        """Batch update keywords for multiple papers.

        Args:
            updates: List of (point_id, keywords) tuples.

        Returns:
            Number of papers updated.
        """
        for point_id, keywords in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"keywords": keywords},
                points=[point_id],
            )
        return len(updates)

    def batch_update_keywords_with_source(
        self,
        updates: list[tuple[str, list[str], str]]
        | list[tuple[str, list[str], str, dict | None]],
    ) -> int:
        """Batch update keywords and extraction source for multiple papers.

        Args:
            updates: List of (point_id, keywords, source) or
                     (point_id, keywords, source, structured) tuples.
                     When structured is provided and not None, it is stored
                     as keywords_structured.

        Returns:
            Number of papers updated.
        """
        for update in updates:
            if len(update) == 4:
                point_id, keywords, source, structured = update
            else:
                point_id, keywords, source = update
                structured = None

            payload: dict = {
                "keywords": keywords,
                "keywords_source": source,
            }
            if structured:
                payload["keywords_structured"] = structured

            self.client.set_payload(
                collection_name=self.collection_name,
                payload=payload,
                points=[point_id],
            )
        return len(updates)

    def clear_all_keywords(self) -> int:
        """Clear keywords from all papers.

        Returns:
            Number of papers cleared.
        """
        cleared = 0
        offset = None

        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                offset=offset,
                with_payload=False,
            )

            for point in results:
                self.client.set_payload(
                    collection_name=self.collection_name,
                    payload={"keywords": [], "keywords_source": None},
                    points=[str(point.id)],
                )
                cleared += 1

            if offset is None:
                break

        return cleared
