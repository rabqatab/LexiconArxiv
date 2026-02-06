"""Qdrant storage layer for Core Corpus papers.

Provides vector database storage with payload fields for filtering and retrieval.
"""

import logging
import os
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from src.models.paper import RawPaper

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Default collection name for core corpus
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "lexicon_arxiv")

# Vector dimensions (commented out - using payload-only storage)
# Vectors will be added later via named vectors feature
# VECTOR_DIM = 768


class QdrantStorage:
    """Qdrant storage for core corpus papers.

    Stores papers with vector embeddings (placeholder) and payload metadata
    for efficient filtering and retrieval.
    """

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
        url: str | None = None,
        api_key: str | None = None,
    ):
        """Initialize Qdrant storage.

        Args:
            collection_name: Name of the Qdrant collection.
            url: Qdrant server URL. Defaults to QDRANT_URL env var.
            api_key: Qdrant API key. Defaults to QDRANT_API_KEY env var.
        """
        self.collection_name = collection_name
        self.url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self.api_key = api_key or os.getenv("QDRANT_API_KEY") or None

        # Initialize client
        if self.api_key:
            self.client = QdrantClient(url=self.url, api_key=self.api_key)
        else:
            self.client = QdrantClient(url=self.url)

    def ensure_collection(self) -> bool:
        """Ensure the collection exists, creating it if necessary.

        Returns:
            True if collection was created, False if it already existed.
        """
        try:
            self.client.get_collection(self.collection_name)
            logger.info(f"Collection '{self.collection_name}' already exists")
            return False
        except (UnexpectedResponse, Exception):
            # Collection doesn't exist, create it (payload-only, vectors added later)
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={},  # Empty config for payload-only storage
            )
            logger.info(f"Created collection '{self.collection_name}'")
            return True

    def _paper_to_payload(self, paper: RawPaper) -> dict[str, Any]:
        """Convert RawPaper to Qdrant payload.

        Args:
            paper: The paper to convert.

        Returns:
            Payload dictionary for Qdrant.
        """
        return {
            "source_id": paper.source_id,
            "openalex_id": paper.openalex_id,
            "title": paper.title,
            "abstract": paper.abstract or "",
            "venue": paper.venue,
            "venue_type": paper.venue_type,
            "tier": paper.tier,
            "is_core": paper.is_core,
            "year": paper.year,
            "doi": paper.doi,
            "citation_count": paper.citation_count,
            "referenced_works": paper.referenced_works,
            "authors": [a.name for a in paper.authors],
            "categories": paper.categories,
            "pdf_url": paper.pdf_url,
        }

    # NOTE: Placeholder vector removed - using payload-only storage
    # Vectors will be added later via named vectors feature
    # def _generate_placeholder_vector(self) -> list[float]:
    #     """Generate a placeholder zero vector."""
    #     return [0.0] * VECTOR_DIM

    def upsert_paper(self, paper: RawPaper) -> str:
        """Upsert a single paper into the collection.

        Args:
            paper: The paper to upsert.

        Returns:
            The point ID used for the paper.
        """
        point_id = str(uuid4())
        payload = self._paper_to_payload(paper)

        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector={},  # Empty for payload-only storage
                    payload=payload,
                )
            ],
        )
        return point_id

    def upsert_papers(self, papers: list[RawPaper], batch_size: int = 100) -> int:
        """Upsert multiple papers into the collection.

        Args:
            papers: List of papers to upsert.
            batch_size: Number of papers per batch.

        Returns:
            Number of papers upserted.
        """
        total_upserted = 0

        for i in range(0, len(papers), batch_size):
            batch = papers[i : i + batch_size]
            points = [
                models.PointStruct(
                    id=str(uuid4()),
                    vector={},  # Empty for payload-only storage
                    payload=self._paper_to_payload(paper),
                )
                for paper in batch
            ]

            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
            )
            total_upserted += len(batch)
            logger.debug(f"Upserted batch of {len(batch)} papers")

        return total_upserted

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

    def count_papers(self, venue: str | None = None, tier: int | None = None) -> int:
        """Count papers in the collection.

        Args:
            venue: Optional venue filter.
            tier: Optional tier filter.

        Returns:
            Number of papers matching the filters.
        """
        filter_conditions = []

        if venue is not None:
            filter_conditions.append(
                models.FieldCondition(
                    key="venue",
                    match=models.MatchValue(value=venue),
                )
            )

        if tier is not None:
            filter_conditions.append(
                models.FieldCondition(
                    key="tier",
                    match=models.MatchValue(value=tier),
                )
            )

        if filter_conditions:
            count_filter = models.Filter(must=filter_conditions)
        else:
            count_filter = None

        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=count_filter,
        )
        return result.count

    def get_venue_stats(self) -> dict[str, int]:
        """Get paper counts by venue.

        Returns:
            Dictionary mapping venue names to paper counts.
        """
        # Scroll through all papers and count by venue
        venue_counts: dict[str, int] = {}
        offset = None

        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                offset=offset,
                with_payload=["venue"],
            )

            for point in results:
                venue = point.payload.get("venue")
                if venue:
                    venue_counts[venue] = venue_counts.get(venue, 0) + 1

            if offset is None:
                break

        return venue_counts

    def delete_collection(self) -> bool:
        """Delete the collection.

        Returns:
            True if deleted successfully.
        """
        try:
            self.client.delete_collection(self.collection_name)
            logger.info(f"Deleted collection '{self.collection_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to delete collection: {e}")
            return False

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
        for point_id, refs in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"referenced_works": refs},
                points=[point_id],
            )
        return len(updates)

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
        for point_id, abstract in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"abstract": abstract},
                points=[point_id],
            )
        return len(updates)

    def get_data_quality_stats(self) -> dict[str, Any]:
        """Get comprehensive data quality statistics.

        Returns:
            Dictionary with data quality metrics including:
            - total: Total paper count
            - by_source: Breakdown by source with DOI/abstract/refs counts
            - enrichment_potential: Papers that can be enriched
        """
        stats: dict[str, Any] = {
            "total": 0,
            "by_source": {},
            "by_venue": {},
            "summary": {
                "has_doi": 0,
                "has_abstract": 0,
                "has_refs": 0,
            },
            "enrichment_potential": {
                "citations": 0,  # has DOI, no refs
                "abstracts": 0,  # has DOI, no abstract
            },
        }

        offset = None
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                offset=offset,
                with_payload=["source_id", "venue", "doi", "abstract", "referenced_works"],
            )

            for point in results:
                payload = point.payload
                stats["total"] += 1

                # Determine source from source_id
                source_id = payload.get("source_id", "")
                if source_id.startswith("https://openalex.org/"):
                    source = "openalex"
                elif source_id.startswith("acl:"):
                    source = "acl_anthology"
                elif source_id.startswith("openreview:"):
                    source = "openreview"
                elif source_id.startswith("dblp:"):
                    source = "dblp"
                elif source_id.startswith("acm:"):
                    source = "acm"
                elif source_id.startswith("aaai:"):
                    source = "aaai"
                else:
                    source = "other"

                # Initialize source stats if needed
                if source not in stats["by_source"]:
                    stats["by_source"][source] = {
                        "count": 0,
                        "has_doi": 0,
                        "has_abstract": 0,
                        "has_refs": 0,
                    }

                source_stats = stats["by_source"][source]
                source_stats["count"] += 1

                # Check DOI
                has_doi = bool(payload.get("doi"))
                if has_doi:
                    source_stats["has_doi"] += 1
                    stats["summary"]["has_doi"] += 1

                # Check abstract
                abstract = payload.get("abstract", "")
                has_abstract = bool(abstract and abstract.strip())
                if has_abstract:
                    source_stats["has_abstract"] += 1
                    stats["summary"]["has_abstract"] += 1

                # Check referenced_works
                refs = payload.get("referenced_works", [])
                has_refs = bool(refs and len(refs) > 0)
                if has_refs:
                    source_stats["has_refs"] += 1
                    stats["summary"]["has_refs"] += 1

                # Enrichment potential
                if has_doi and not has_refs:
                    stats["enrichment_potential"]["citations"] += 1
                if has_doi and not has_abstract:
                    stats["enrichment_potential"]["abstracts"] += 1

                # Venue stats
                venue = payload.get("venue", "unknown")
                if venue not in stats["by_venue"]:
                    stats["by_venue"][venue] = {
                        "count": 0,
                        "has_doi": 0,
                        "has_abstract": 0,
                        "has_refs": 0,
                    }
                venue_stats = stats["by_venue"][venue]
                venue_stats["count"] += 1
                if has_doi:
                    venue_stats["has_doi"] += 1
                if has_abstract:
                    venue_stats["has_abstract"] += 1
                if has_refs:
                    venue_stats["has_refs"] += 1

            if offset is None:
                break

        return stats

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
        for point_id, doi, refs in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={
                    "doi": doi,
                    "referenced_works": refs,
                },
                points=[point_id],
            )
        return len(updates)

    # =========================================================================
    # Reference Resolution Methods
    # =========================================================================

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

    def get_reference_stats(self) -> dict[str, Any]:
        """Get statistics about reference resolution.

        Returns:
            Dictionary with reference resolution metrics.
        """
        stats = {
            "total_papers": 0,
            "papers_with_refs": 0,
            "papers_with_resolved_refs": 0,
            "total_references": 0,
            "total_resolved": 0,
            "ref_types": {
                "DOI": 0,
                "arXiv": 0,
                "W": 0,  # OpenAlex
                "TITLE": 0,
                "UNKNOWN": 0,
            },
        }

        offset = None
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                offset=offset,
                with_payload=["referenced_works", "resolved_references"],
            )

            for point in results:
                payload = point.payload
                stats["total_papers"] += 1

                refs = payload.get("referenced_works", [])
                if refs:
                    stats["papers_with_refs"] += 1
                    stats["total_references"] += len(refs)

                    # Count reference types
                    for ref in refs:
                        if ref.startswith("DOI:"):
                            stats["ref_types"]["DOI"] += 1
                        elif ref.startswith("arXiv:"):
                            stats["ref_types"]["arXiv"] += 1
                        elif ref.startswith("W") and ref[1:].isdigit():
                            stats["ref_types"]["W"] += 1
                        elif ref.startswith("TITLE:"):
                            stats["ref_types"]["TITLE"] += 1
                        else:
                            stats["ref_types"]["UNKNOWN"] += 1

                resolved = payload.get("resolved_references", [])
                if resolved:
                    stats["papers_with_resolved_refs"] += 1
                    stats["total_resolved"] += len(resolved)

            if offset is None:
                break

        return stats

    # =========================================================================
    # Citation Graph Methods
    # =========================================================================

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

    def get_citation_graph_stats(self) -> dict[str, Any]:
        """Get statistics about the citation graph.

        Returns:
            Dictionary with citation graph metrics including:
            - papers_with_refs: Papers with referenced_works
            - papers_with_resolved_refs: Papers with resolved_references
            - total_edges: Total resolved citation edges
            - coverage: Percentage of refs that are resolved
        """
        stats: dict[str, Any] = {
            "total_papers": 0,
            "papers_with_refs": 0,
            "papers_with_resolved_refs": 0,
            "total_raw_refs": 0,
            "total_resolved_refs": 0,
            "papers_with_graph_metrics": 0,
        }

        offset = None
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                offset=offset,
                with_payload=[
                    "referenced_works",
                    "resolved_references",
                    "pagerank",
                ],
            )

            for point in results:
                payload = point.payload
                stats["total_papers"] += 1

                refs = payload.get("referenced_works", [])
                if refs:
                    stats["papers_with_refs"] += 1
                    stats["total_raw_refs"] += len(refs)

                resolved = payload.get("resolved_references", [])
                if resolved:
                    stats["papers_with_resolved_refs"] += 1
                    stats["total_resolved_refs"] += len(resolved)

                if payload.get("pagerank") is not None:
                    stats["papers_with_graph_metrics"] += 1

            if offset is None:
                break

        # Calculate coverage
        if stats["total_raw_refs"] > 0:
            stats["resolution_coverage"] = (
                stats["total_resolved_refs"] / stats["total_raw_refs"] * 100
            )
        else:
            stats["resolution_coverage"] = 0.0

        return stats

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

    def build_cited_by_index(
        self,
        batch_size: int = 100,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Build the cited_by field for all papers.

        Scans all papers and builds a reverse citation index, then stores
        the `cited_by` list in each paper's payload. This enables O(1)
        bidirectional citation traversal for GraphRAG queries.

        Args:
            batch_size: Number of papers to update in each batch.
            progress_callback: Optional callback(processed, total) for progress.

        Returns:
            Statistics about the operation.
        """
        from collections import defaultdict

        logger.info("Building cited_by index...")

        # Phase 1: Build reverse index in memory
        reverse_index: dict[str, list[str]] = defaultdict(list)
        total_papers = 0
        total_edges = 0

        offset = None
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                offset=offset,
                with_payload=["resolved_references"],
            )

            for point in results:
                paper_id = str(point.id)
                resolved_refs = point.payload.get("resolved_references", [])

                for cited_id in resolved_refs:
                    reverse_index[cited_id].append(paper_id)
                    total_edges += 1

                total_papers += 1

            if total_papers % 10000 == 0:
                logger.info(f"  Scanned {total_papers} papers, {total_edges} edges...")

            if offset is None:
                break

        logger.info(
            f"Built reverse index: {total_papers} papers, "
            f"{total_edges} edges, {len(reverse_index)} cited papers"
        )

        # Phase 2: Store cited_by field for each paper
        updated = 0
        papers_with_citations = 0

        # Get all paper IDs for updating
        offset = None
        all_ids: list[str] = []
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                offset=offset,
                with_payload=False,
            )
            all_ids.extend(str(point.id) for point in results)
            if offset is None:
                break

        # Update in batches
        for i in range(0, len(all_ids), batch_size):
            batch_ids = all_ids[i : i + batch_size]

            for paper_id in batch_ids:
                citing_papers = reverse_index.get(paper_id, [])
                self.client.set_payload(
                    collection_name=self.collection_name,
                    payload={"cited_by": citing_papers},
                    points=[paper_id],
                )
                if citing_papers:
                    papers_with_citations += 1
                updated += 1

            if progress_callback:
                progress_callback(updated, len(all_ids))

            if updated % 5000 == 0:
                logger.info(f"  Updated {updated}/{len(all_ids)} papers...")

        logger.info(
            f"Stored cited_by field: {updated} papers updated, "
            f"{papers_with_citations} have incoming citations"
        )

        return {
            "total_papers": total_papers,
            "total_edges": total_edges,
            "papers_with_citations": papers_with_citations,
            "unique_cited_papers": len(reverse_index),
        }

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

    # =========================================================================
    # Keyword Extraction Methods
    # =========================================================================

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
        updates: list[tuple[str, list[str], str]],  # [(point_id, keywords, source), ...]
    ) -> int:
        """Batch update keywords and extraction source for multiple papers.

        Args:
            updates: List of (point_id, keywords, keywords_source) tuples.
                     keywords_source is one of: "regex", "keybert", "both", "none"

        Returns:
            Number of papers updated.
        """
        for point_id, keywords, source in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={
                    "keywords": keywords,
                    "keywords_source": source,
                },
                points=[point_id],
            )
        return len(updates)

    def get_keyword_stats(self) -> dict[str, Any]:
        """Get statistics about keyword extraction.

        Returns:
            Dictionary with keyword extraction metrics including:
            - total_papers: Total paper count
            - papers_with_keywords: Papers that have keywords
            - papers_without_keywords: Papers missing keywords
            - total_keywords: Total number of keywords across all papers
            - avg_keywords_per_paper: Average keywords per paper
            - by_source: Breakdown by extraction source
        """
        stats: dict[str, Any] = {
            "total_papers": 0,
            "papers_with_keywords": 0,
            "papers_without_keywords": 0,
            "total_keywords": 0,
            "by_source": {
                "regex": 0,
                "keybert": 0,
                "both": 0,
                "none": 0,
            },
        }

        offset = None
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                offset=offset,
                with_payload=["keywords", "keywords_source"],
            )

            for point in results:
                payload = point.payload
                stats["total_papers"] += 1

                keywords = payload.get("keywords", [])
                if keywords:
                    stats["papers_with_keywords"] += 1
                    stats["total_keywords"] += len(keywords)
                else:
                    stats["papers_without_keywords"] += 1

                # Count by source
                source = payload.get("keywords_source", "none")
                if source in stats["by_source"]:
                    stats["by_source"][source] += 1

            if offset is None:
                break

        # Calculate average
        if stats["papers_with_keywords"] > 0:
            stats["avg_keywords_per_paper"] = (
                stats["total_keywords"] / stats["papers_with_keywords"]
            )
        else:
            stats["avg_keywords_per_paper"] = 0.0

        return stats

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

    # =========================================================================
    # Stub Paper Methods (External References)
    # =========================================================================

    def _generate_stub_id(self, identifier: str) -> str:
        """Generate a deterministic ID for a stub paper from its identifier.

        Args:
            identifier: The raw identifier (e.g., 'doi:10.1234/example').

        Returns:
            A deterministic UUID-like string based on the identifier.
        """
        import hashlib

        # Create a deterministic hash from the identifier
        hash_bytes = hashlib.sha256(identifier.lower().encode()).digest()
        # Format as UUID-like string for Qdrant compatibility
        hex_str = hash_bytes.hex()
        return f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"

    def create_stub_paper(
        self,
        identifier: str,
        identifier_type: str,
        citing_paper_id: str,
    ) -> str | None:
        """Create a stub paper for an external reference.

        Stub papers have is_stub=True and no vector embedding.
        They track which corpus papers cite them.

        Args:
            identifier: The raw identifier (e.g., 'doi:10.1234/example').
            identifier_type: Type of identifier ('doi', 'arxiv', 'title', 'openalex').
            citing_paper_id: The corpus paper ID that cites this stub.

        Returns:
            The stub's point ID, or None if creation failed.
        """
        stub_id = self._generate_stub_id(identifier)

        # Check if stub already exists
        try:
            existing = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[stub_id],
                with_payload=True,
            )
            if existing:
                # Stub exists, update cited_by
                current_cited_by = existing[0].payload.get("cited_by", [])
                if citing_paper_id not in current_cited_by:
                    current_cited_by.append(citing_paper_id)
                    self.client.set_payload(
                        collection_name=self.collection_name,
                        payload={
                            "cited_by": current_cited_by,
                            "cited_by_count_internal": len(current_cited_by),
                        },
                        points=[stub_id],
                    )
                return stub_id
        except Exception:
            pass  # Stub doesn't exist, create it

        # Create new stub (payload-only, no vector)
        payload = {
            "is_stub": True,
            "identifier": identifier,
            "identifier_type": identifier_type,
            "title": None,
            "abstract": None,
            "year": None,
            "authors": [],
            "venue": None,
            "doi": identifier[4:] if identifier_type == "doi" else None,
            "citation_count": None,  # Global citation count (from API)
            "cited_by": [citing_paper_id],
            "cited_by_count_internal": 1,
            "is_core": False,
        }

        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=stub_id,
                        vector={},  # Empty for payload-only storage
                        payload=payload,
                    )
                ],
            )
            return stub_id
        except Exception as e:
            logger.error(f"Failed to create stub paper: {e}")
            return None

    def batch_create_stub_papers(
        self,
        stubs: list[tuple[str, str, str]],  # [(identifier, type, citing_id), ...]
    ) -> dict[str, str]:
        """Batch create stub papers for external references.

        Args:
            stubs: List of (identifier, identifier_type, citing_paper_id) tuples.

        Returns:
            Dictionary mapping identifier to stub_id for created stubs.
        """
        # Group by identifier to handle multiple citations to same paper
        stub_citations: dict[str, tuple[str, list[str]]] = {}  # id -> (type, [citing_ids])
        for identifier, id_type, citing_id in stubs:
            if identifier not in stub_citations:
                stub_citations[identifier] = (id_type, [])
            stub_citations[identifier][1].append(citing_id)

        created: dict[str, str] = {}
        for identifier, (id_type, citing_ids) in stub_citations.items():
            stub_id = self._generate_stub_id(identifier)

            # Check if stub exists
            try:
                existing = self.client.retrieve(
                    collection_name=self.collection_name,
                    ids=[stub_id],
                    with_payload=["cited_by"],
                )
                if existing:
                    # Update existing stub
                    current_cited_by = existing[0].payload.get("cited_by", [])
                    new_cited_by = list(set(current_cited_by + citing_ids))
                    self.client.set_payload(
                        collection_name=self.collection_name,
                        payload={
                            "cited_by": new_cited_by,
                            "cited_by_count_internal": len(new_cited_by),
                        },
                        points=[stub_id],
                    )
                    created[identifier] = stub_id
                    continue
            except Exception:
                pass

            # Create new stub
            payload = {
                "is_stub": True,
                "identifier": identifier,
                "identifier_type": id_type,
                "title": None,
                "abstract": None,
                "year": None,
                "authors": [],
                "venue": None,
                "doi": identifier[4:] if id_type == "doi" else None,
                "citation_count": None,
                "cited_by": citing_ids,
                "cited_by_count_internal": len(citing_ids),
                "is_core": False,
            }

            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=[
                        models.PointStruct(
                            id=stub_id,
                            vector={},  # Empty for payload-only storage
                            payload=payload,
                        )
                    ],
                )
                created[identifier] = stub_id
            except Exception as e:
                logger.debug(f"Failed to create stub {identifier}: {e}")

        return created

    def get_stub_by_identifier(self, identifier: str) -> tuple[str, dict] | None:
        """Get a stub paper by its identifier.

        Args:
            identifier: The raw identifier (e.g., 'doi:10.1234/example').

        Returns:
            Tuple of (stub_id, payload) if found, None otherwise.
        """
        stub_id = self._generate_stub_id(identifier)
        try:
            result = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[stub_id],
                with_payload=True,
            )
            if result and result[0].payload.get("is_stub"):
                return (stub_id, result[0].payload)
        except Exception:
            pass
        return None

    def get_stub_stats(self) -> dict[str, Any]:
        """Get statistics about stub papers.

        Returns:
            Dictionary with stub paper metrics.
        """
        stats: dict[str, Any] = {
            "total_stubs": 0,
            "by_identifier_type": {
                "doi": 0,
                "arxiv": 0,
                "title": 0,
                "openalex": 0,
                "other": 0,
            },
            "stubs_with_metadata": 0,  # Stubs that have been enriched
            "total_internal_citations": 0,
            "avg_citations_per_stub": 0.0,
            "max_citations": 0,
            "top_cited_stubs": [],  # Will be filled with top 20
        }

        # Track top cited for sorting
        all_stubs: list[tuple[int, str, str | None]] = []  # (count, id, title)

        offset = None
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="is_stub",
                            match=models.MatchValue(value=True),
                        )
                    ]
                ),
                limit=1000,
                offset=offset,
                with_payload=["identifier_type", "title", "cited_by_count_internal", "identifier"],
            )

            for point in results:
                payload = point.payload
                stats["total_stubs"] += 1

                # Count by type
                id_type = payload.get("identifier_type", "other")
                if id_type in stats["by_identifier_type"]:
                    stats["by_identifier_type"][id_type] += 1
                else:
                    stats["by_identifier_type"]["other"] += 1

                # Check if enriched
                if payload.get("title"):
                    stats["stubs_with_metadata"] += 1

                # Citation stats
                cite_count = payload.get("cited_by_count_internal", 0)
                stats["total_internal_citations"] += cite_count
                if cite_count > stats["max_citations"]:
                    stats["max_citations"] = cite_count

                # Track for top cited
                all_stubs.append((
                    cite_count,
                    payload.get("identifier", str(point.id)),
                    payload.get("title"),
                ))

            if offset is None:
                break

        # Calculate average
        if stats["total_stubs"] > 0:
            stats["avg_citations_per_stub"] = (
                stats["total_internal_citations"] / stats["total_stubs"]
            )

        # Get top 20 most cited
        all_stubs.sort(reverse=True, key=lambda x: x[0])
        stats["top_cited_stubs"] = [
            {"citations": count, "identifier": ident, "title": title}
            for count, ident, title in all_stubs[:20]
        ]

        return stats

    def get_most_cited_stubs(
        self,
        limit: int = 50,
        min_citations: int = 1,
    ) -> list[tuple[str, dict]]:
        """Get the most cited stub papers.

        Args:
            limit: Maximum number of stubs to return.
            min_citations: Minimum internal citation count.

        Returns:
            List of (stub_id, payload) sorted by citation count descending.
        """
        stubs: list[tuple[int, str, dict]] = []  # (count, id, payload)

        offset = None
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="is_stub",
                            match=models.MatchValue(value=True),
                        )
                    ]
                ),
                limit=1000,
                offset=offset,
                with_payload=True,
            )

            for point in results:
                cite_count = point.payload.get("cited_by_count_internal", 0)
                if cite_count >= min_citations:
                    stubs.append((cite_count, str(point.id), point.payload))

            if offset is None:
                break

        # Sort by citation count descending
        stubs.sort(reverse=True, key=lambda x: x[0])

        return [(stub_id, payload) for _, stub_id, payload in stubs[:limit]]

    def get_stubs_for_enrichment(
        self,
        identifier_type: str | None = None,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get stub papers that need enrichment (no title/metadata).

        Args:
            identifier_type: Filter by identifier type ('doi', 'arxiv', etc.).
            limit: Maximum number of stubs to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (stub_id, payload), next_offset).
        """
        filter_conditions = [
            models.FieldCondition(
                key="is_stub",
                match=models.MatchValue(value=True),
            ),
            models.IsNullCondition(
                is_null=models.PayloadField(key="title"),
            ),
        ]

        if identifier_type:
            filter_conditions.append(
                models.FieldCondition(
                    key="identifier_type",
                    match=models.MatchValue(value=identifier_type),
                )
            )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(must=filter_conditions),
            limit=limit,
            offset=offset,
            with_payload=True,
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def update_stub_metadata(
        self,
        stub_id: str,
        title: str | None = None,
        year: int | None = None,
        authors: list[str] | None = None,
        venue: str | None = None,
        abstract: str | None = None,
        citation_count: int | None = None,
    ) -> bool:
        """Update a stub paper with enriched metadata.

        Args:
            stub_id: The stub's point ID.
            title: Paper title.
            year: Publication year.
            authors: List of author names.
            venue: Publication venue.
            abstract: Paper abstract.
            citation_count: Global citation count from API.

        Returns:
            True if successful.
        """
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if year is not None:
            payload["year"] = year
        if authors is not None:
            payload["authors"] = authors
        if venue is not None:
            payload["venue"] = venue
        if abstract is not None:
            payload["abstract"] = abstract
        if citation_count is not None:
            payload["citation_count"] = citation_count

        if not payload:
            return True

        try:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload=payload,
                points=[stub_id],
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update stub metadata: {e}")
            return False

    def batch_update_stub_metadata(
        self,
        updates: list[tuple[str, dict]],  # [(stub_id, metadata_dict), ...]
    ) -> int:
        """Batch update metadata for multiple stub papers.

        Args:
            updates: List of (stub_id, metadata_dict) tuples.

        Returns:
            Number of stubs updated.
        """
        updated = 0
        for stub_id, metadata in updates:
            try:
                self.client.set_payload(
                    collection_name=self.collection_name,
                    payload=metadata,
                    points=[stub_id],
                )
                updated += 1
            except Exception as e:
                logger.debug(f"Failed to update stub {stub_id}: {e}")
        return updated

    def count_stubs(self) -> int:
        """Count total stub papers.

        Returns:
            Number of stub papers.
        """
        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="is_stub",
                        match=models.MatchValue(value=True),
                    )
                ]
            ),
        )
        return result.count

    def count_real_papers(self) -> int:
        """Count real (non-stub) papers.

        Returns:
            Number of real papers.
        """
        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=models.Filter(
                must_not=[
                    models.FieldCondition(
                        key="is_stub",
                        match=models.MatchValue(value=True),
                    )
                ]
            ),
        )
        return result.count

    # =========================================================================
    # Stub Deduplication Methods
    # =========================================================================

    def build_stub_identifier_index(self) -> dict[str, str]:
        """Build an in-memory index mapping identifiers to stub IDs.

        This includes both primary identifiers and alternate identifiers.
        Used for fast cross-reference lookup during stub creation.

        Returns:
            Dictionary mapping lowercase identifier to stub_id.
        """
        index: dict[str, str] = {}

        offset = None
        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="is_stub",
                            match=models.MatchValue(value=True),
                        )
                    ]
                ),
                limit=1000,
                offset=offset,
                with_payload=["identifier", "alternate_identifiers", "doi"],
            )

            for point in results:
                stub_id = str(point.id)
                payload = point.payload

                # Index primary identifier
                primary = payload.get("identifier", "")
                if primary:
                    index[primary.lower()] = stub_id

                # Index alternate identifiers
                alternates = payload.get("alternate_identifiers", {})
                for alt_type, alt_value in alternates.items():
                    if alt_value:
                        # Store with prefix for consistency
                        prefixed = f"{alt_type.upper()}:{alt_value}"
                        index[prefixed.lower()] = stub_id

                # Index DOI separately (for stubs enriched before this feature)
                doi = payload.get("doi")
                if doi:
                    index[f"doi:{doi}".lower()] = stub_id

            if offset is None:
                break

        logger.info(f"Built stub identifier index: {len(index)} entries")
        return index

    def find_stub_by_alternate_identifier(
        self,
        doi: str | None = None,
        arxiv_id: str | None = None,
        openalex_id: str | None = None,
    ) -> tuple[str, dict] | None:
        """Find a stub paper by any of its identifiers.

        Searches both primary identifier and alternate_identifiers field.

        Args:
            doi: DOI to search for.
            arxiv_id: arXiv ID to search for.
            openalex_id: OpenAlex Work ID to search for.

        Returns:
            Tuple of (stub_id, payload) or None if not found.
        """
        # Try each identifier type
        for id_type, id_value in [("doi", doi), ("arxiv", arxiv_id), ("openalex", openalex_id)]:
            if not id_value:
                continue

            # Clean the identifier
            id_value_clean = id_value.lower().strip()

            # Build prefixed version
            prefixed = f"{id_type.upper()}:{id_value_clean}"

            # First try direct lookup by primary identifier
            stub = self.get_stub_by_identifier(prefixed)
            if stub:
                return stub

            # Try alternate identifiers search
            offset = None
            while True:
                results, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="is_stub",
                                match=models.MatchValue(value=True),
                            ),
                            models.FieldCondition(
                                key=f"alternate_identifiers.{id_type}",
                                match=models.MatchValue(value=id_value_clean),
                            ),
                        ]
                    ),
                    limit=1,
                    offset=offset,
                    with_payload=True,
                )

                if results:
                    return (str(results[0].id), results[0].payload)

                if offset is None:
                    break

            # Also check the doi field directly for legacy stubs
            if id_type == "doi":
                offset = None
                while True:
                    results, offset = self.client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="is_stub",
                                    match=models.MatchValue(value=True),
                                ),
                                models.FieldCondition(
                                    key="doi",
                                    match=models.MatchValue(value=id_value_clean),
                                ),
                            ]
                        ),
                        limit=1,
                        offset=offset,
                        with_payload=True,
                    )

                    if results:
                        return (str(results[0].id), results[0].payload)

                    if offset is None:
                        break

        return None

    def add_stub_alternate_identifier(
        self,
        stub_id: str,
        identifier_type: str,
        identifier_value: str,
    ) -> bool:
        """Add an alternate identifier to a stub paper.

        Args:
            stub_id: The stub's point ID.
            identifier_type: Type of identifier ('doi', 'arxiv', 'openalex').
            identifier_value: The identifier value.

        Returns:
            True if successful.
        """
        try:
            # Get current alternate identifiers
            existing = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[stub_id],
                with_payload=["alternate_identifiers"],
            )

            if not existing:
                return False

            alternates = existing[0].payload.get("alternate_identifiers", {})
            alternates[identifier_type] = identifier_value.lower()

            # Also update the doi field if it's a DOI
            payload: dict[str, Any] = {"alternate_identifiers": alternates}
            if identifier_type == "doi":
                payload["doi"] = identifier_value.lower()

            self.client.set_payload(
                collection_name=self.collection_name,
                payload=payload,
                points=[stub_id],
            )
            return True

        except Exception as e:
            logger.error(f"Failed to add alternate identifier: {e}")
            return False

    def merge_stubs(
        self,
        keep_stub_id: str,
        merge_stub_id: str,
    ) -> bool:
        """Merge two stub papers, combining their citations.

        The merge_stub will be deleted and its cited_by list merged into keep_stub.

        Args:
            keep_stub_id: The stub to keep.
            merge_stub_id: The stub to merge and delete.

        Returns:
            True if successful.
        """
        try:
            # Get both stubs
            stubs = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[keep_stub_id, merge_stub_id],
                with_payload=True,
            )

            if len(stubs) != 2:
                logger.warning(f"Could not find both stubs for merge: {keep_stub_id}, {merge_stub_id}")
                return False

            keep_stub = next((s for s in stubs if str(s.id) == keep_stub_id), None)
            merge_stub = next((s for s in stubs if str(s.id) == merge_stub_id), None)

            if not keep_stub or not merge_stub:
                return False

            keep_payload = keep_stub.payload
            merge_payload = merge_stub.payload

            # Merge cited_by lists
            keep_cited_by = set(keep_payload.get("cited_by", []))
            merge_cited_by = set(merge_payload.get("cited_by", []))
            combined_cited_by = list(keep_cited_by | merge_cited_by)

            # Merge alternate identifiers
            keep_alternates = keep_payload.get("alternate_identifiers", {})
            merge_alternates = merge_payload.get("alternate_identifiers", {})

            # Add merge stub's primary identifier to alternates
            merge_identifier = merge_payload.get("identifier", "")
            merge_type = merge_payload.get("identifier_type", "")
            if merge_type and merge_identifier:
                # Extract just the value part
                if ":" in merge_identifier:
                    merge_value = merge_identifier.split(":", 1)[1]
                else:
                    merge_value = merge_identifier
                keep_alternates[merge_type] = merge_value.lower()

            # Combine alternates
            for alt_type, alt_value in merge_alternates.items():
                if alt_value and alt_type not in keep_alternates:
                    keep_alternates[alt_type] = alt_value

            # Use better metadata if available
            update_payload: dict[str, Any] = {
                "cited_by": combined_cited_by,
                "cited_by_count_internal": len(combined_cited_by),
                "alternate_identifiers": keep_alternates,
            }

            # Prefer non-null metadata
            if not keep_payload.get("title") and merge_payload.get("title"):
                update_payload["title"] = merge_payload["title"]
            if not keep_payload.get("year") and merge_payload.get("year"):
                update_payload["year"] = merge_payload["year"]
            if not keep_payload.get("authors") and merge_payload.get("authors"):
                update_payload["authors"] = merge_payload["authors"]
            if not keep_payload.get("venue") and merge_payload.get("venue"):
                update_payload["venue"] = merge_payload["venue"]
            if not keep_payload.get("abstract") and merge_payload.get("abstract"):
                update_payload["abstract"] = merge_payload["abstract"]
            if not keep_payload.get("doi") and merge_payload.get("doi"):
                update_payload["doi"] = merge_payload["doi"]

            # Update keep stub
            self.client.set_payload(
                collection_name=self.collection_name,
                payload=update_payload,
                points=[keep_stub_id],
            )

            # Delete merge stub
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[merge_stub_id]),
            )

            logger.info(f"Merged stub {merge_stub_id} into {keep_stub_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to merge stubs: {e}")
            return False
