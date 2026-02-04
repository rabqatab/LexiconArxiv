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

# Vector dimensions (placeholder for future embeddings)
VECTOR_DIM = 768


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
            # Collection doesn't exist, create it
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=VECTOR_DIM,
                    distance=models.Distance.COSINE,
                ),
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

    def _generate_placeholder_vector(self) -> list[float]:
        """Generate a placeholder zero vector.

        Embeddings will be computed later; for now use zeros.
        """
        return [0.0] * VECTOR_DIM

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
                    vector=self._generate_placeholder_vector(),
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
                    vector=self._generate_placeholder_vector(),
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
