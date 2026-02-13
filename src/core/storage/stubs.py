"""Stub paper management for Qdrant storage.

Provides methods for creating and managing stub papers (external references).
"""

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)


class StubManager:
    """Handles stub paper creation, enrichment, and deduplication."""

    def __init__(self, client: QdrantClient, collection_name: str):
        self.client = client
        self.collection_name = collection_name

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
