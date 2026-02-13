"""Paper query operations for Qdrant storage.

Provides methods for looking up individual papers by various identifiers.
"""

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)


class PaperQuery:
    """Handles individual paper lookups by various identifiers."""

    def __init__(self, client: QdrantClient, collection_name: str):
        self.client = client
        self.collection_name = collection_name

    def get_paper_by_doi(self, doi: str) -> dict[str, Any] | None:
        """Get a paper by DOI.

        Args:
            doi: The DOI to search for.

        Returns:
            Paper payload if found, None otherwise.
        """
        results = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doi",
                        match=models.MatchValue(value=doi),
                    )
                ]
            ),
            limit=1,
        )
        points = results[0]
        if points:
            return points[0].payload
        return None

    def get_paper_by_openalex_id(self, openalex_id: str) -> dict[str, Any] | None:
        """Get a paper by OpenAlex ID.

        Args:
            openalex_id: The OpenAlex ID to search for.

        Returns:
            Paper payload if found, None otherwise.
        """
        results = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="openalex_id",
                        match=models.MatchValue(value=openalex_id),
                    )
                ]
            ),
            limit=1,
        )
        points = results[0]
        if points:
            return points[0].payload
        return None

    def get_paper_by_arxiv_id(self, arxiv_id: str) -> tuple[str, dict] | None:
        """Get a paper by arXiv ID.

        Args:
            arxiv_id: The arXiv ID to search for (e.g., '2303.08774').

        Returns:
            Tuple of (point_id, payload) if found, None otherwise.
        """
        # arXiv IDs are stored in source_id for arXiv-sourced papers
        # or may be in a dedicated field
        results = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                should=[
                    # Check source_id for arXiv format
                    models.FieldCondition(
                        key="source_id",
                        match=models.MatchValue(value=f"arXiv:{arxiv_id}"),
                    ),
                    models.FieldCondition(
                        key="source_id",
                        match=models.MatchValue(value=arxiv_id),
                    ),
                ]
            ),
            limit=1,
            with_payload=True,
        )
        points = results[0]
        if points:
            return (str(points[0].id), points[0].payload)
        return None

    def get_paper_by_id(self, point_id: str) -> dict[str, Any] | None:
        """Get a paper by its Qdrant point ID.

        Args:
            point_id: The Qdrant point ID.

        Returns:
            Paper payload if found, None otherwise.
        """
        try:
            result = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
                with_payload=True,
            )
            if result:
                return result[0].payload
        except Exception:
            pass
        return None

    def get_paper_by_normalized_title(
        self, normalized_title: str
    ) -> tuple[str, dict] | None:
        """Get a paper by normalized title.

        This is a slow operation as it requires scanning all papers.
        Consider building an in-memory index for bulk operations.

        Args:
            normalized_title: Normalized title string.

        Returns:
            Tuple of (point_id, payload) if found, None otherwise.
        """
        from src.core.deduplication import Deduplicator

        offset = None
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=100,
                offset=offset,
                with_payload=["title"],
            )

            for point in results:
                title = point.payload.get("title", "")
                if Deduplicator.normalize_title(title) == normalized_title:
                    # Get full payload
                    full_result = self.client.retrieve(
                        collection_name=self.collection_name,
                        ids=[point.id],
                        with_payload=True,
                    )
                    if full_result:
                        return (str(point.id), full_result[0].payload)

            if offset is None:
                break

        return None

    def exists_by_doi(self, doi: str) -> bool:
        """Check if a paper with this DOI exists.

        Args:
            doi: The DOI to check.

        Returns:
            True if the paper exists.
        """
        return self.get_paper_by_doi(doi) is not None

    def exists_by_openalex_id(self, openalex_id: str) -> bool:
        """Check if a paper with this OpenAlex ID exists.

        Args:
            openalex_id: The OpenAlex ID to check.

        Returns:
            True if the paper exists.
        """
        return self.get_paper_by_openalex_id(openalex_id) is not None
