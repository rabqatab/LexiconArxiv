"""Paper reader operations for Qdrant storage.

Provides methods for bulk reading papers with various filters.
"""

import logging

from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)


class PaperReader:
    """Handles bulk paper reading with filtering."""

    def __init__(self, client: QdrantClient, collection_name: str):
        self.client = client
        self.collection_name = collection_name

    def get_papers_missing_references(
        self,
        has_doi: bool = True,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers with DOI but empty referenced_works.

        Args:
            has_doi: If True, only return papers that have a DOI.
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        filter_conditions = [
            models.IsEmptyCondition(
                is_empty=models.PayloadField(key="referenced_works"),
            )
        ]
        # Exclude papers where DOI is null (we need DOI for lookup)
        must_not_conditions = []
        if has_doi:
            must_not_conditions.append(
                models.IsNullCondition(
                    is_null=models.PayloadField(key="doi"),
                )
            )

        scroll_filter = models.Filter(
            must=filter_conditions,
            must_not=must_not_conditions if must_not_conditions else None,
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_missing_abstracts(
        self,
        has_doi: bool = True,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers with DOI but empty/missing abstract.

        Args:
            has_doi: If True, only return papers that have a DOI.
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        # Papers with empty string abstract
        filter_conditions = [
            models.FieldCondition(
                key="abstract",
                match=models.MatchValue(value=""),
            )
        ]
        # Exclude papers where DOI is null (we need DOI for lookup)
        must_not_conditions = []
        if has_doi:
            must_not_conditions.append(
                models.IsNullCondition(
                    is_null=models.PayloadField(key="doi"),
                )
            )

        scroll_filter = models.Filter(
            must=filter_conditions,
            must_not=must_not_conditions if must_not_conditions else None,
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_without_doi_missing_references(
        self,
        limit: int = 100,
        offset: str | None = None,
        venues: list[str] | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers without DOI that are missing referenced_works.

        These papers need title-based lookup for enrichment.

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.
            venues: Optional list of venues to filter by.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        # Papers with empty referenced_works AND null DOI
        filter_conditions = [
            models.IsEmptyCondition(
                is_empty=models.PayloadField(key="referenced_works"),
            ),
            models.IsNullCondition(
                is_null=models.PayloadField(key="doi"),
            ),
        ]

        # Optionally filter by venue
        if venues:
            filter_conditions.append(
                models.FieldCondition(
                    key="venue",
                    match=models.MatchAny(any=venues),
                )
            )

        scroll_filter = models.Filter(must=filter_conditions)

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_with_references(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers that have referenced_works (non-empty).

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        scroll_filter = models.Filter(
            must_not=[
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="referenced_works"),
                )
            ]
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_needing_resolution(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers with referenced_works but no resolved_references.

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        scroll_filter = models.Filter(
            must=[
                # Has referenced_works
                models.FieldCondition(
                    key="referenced_works",
                    match=models.MatchExcept(**{"except": []}),  # Not empty
                ),
            ],
            must_not=[
                # But no resolved_references yet (null or empty)
                models.FieldCondition(
                    key="resolved_references",
                    match=models.MatchExcept(**{"except": []}),  # Not empty
                ),
            ],
        )

        # Simpler approach: just get papers with refs and check in Python
        scroll_filter = models.Filter(
            must_not=[
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="referenced_works"),
                )
            ]
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=["title", "doi", "referenced_works", "resolved_references"],
        )

        # Filter to papers without resolved_references
        papers = []
        for p in results:
            resolved = p.payload.get("resolved_references", [])
            if not resolved:
                papers.append((str(p.id), p.payload))

        return papers, next_offset

    def get_papers_for_keyword_extraction(
        self,
        limit: int = 100,
        offset: str | None = None,
        skip_existing: bool = True,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers for keyword extraction.

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.
            skip_existing: If True, only return papers without keywords.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        filter_conditions = []

        if skip_existing:
            # Papers without keywords (empty list or null)
            filter_conditions.append(
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="keywords"),
                )
            )

        scroll_filter = models.Filter(must=filter_conditions) if filter_conditions else None

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=["title", "abstract", "keywords"],
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_all_papers_for_index(
        self,
        fields: list[str],
        limit: int = 1000,
    ) -> dict[str, dict]:
        """Get all papers with specified fields for building indexes.

        Args:
            fields: List of payload fields to retrieve.
            limit: Batch size for scrolling.

        Returns:
            Dictionary mapping point_id to payload dict.
        """
        papers: dict[str, dict] = {}
        offset = None

        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                offset=offset,
                with_payload=fields,
            )

            for point in results:
                papers[str(point.id)] = point.payload

            if offset is None:
                break

        return papers
