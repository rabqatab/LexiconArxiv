"""Storage statistics for Qdrant storage.

Provides methods for collecting various statistics about the paper collection.
"""

import logging
import time
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import ResponseHandlingException

logger = logging.getLogger(__name__)


class StorageStatistics:
    """Handles statistics and analytics queries."""

    def __init__(self, client: QdrantClient, collection_name: str):
        self.client = client
        self.collection_name = collection_name

    def _scroll_with_retry(
        self,
        offset: str | None = None,
        with_payload: bool | list[str] = True,
        limit: int = 1000,
        scroll_filter: models.Filter | None = None,
        max_retries: int = 5,
        base_delay: float = 3.0,
    ):
        """Scroll with retry on connection errors."""
        for attempt in range(max_retries + 1):
            try:
                return self.client.scroll(
                    collection_name=self.collection_name,
                    limit=limit,
                    offset=offset,
                    with_payload=with_payload,
                    scroll_filter=scroll_filter,
                )
            except (ResponseHandlingException, ConnectionError, OSError) as e:
                if attempt == max_retries:
                    raise
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Scroll failed (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay:.0f}s: {e}"
                )
                time.sleep(delay)

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
            "by_source": {},
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

                # Count by source (dynamic — supports any pipe-delimited value)
                source = payload.get("keywords_source", "none") or "none"
                stats["by_source"][source] = stats["by_source"].get(source, 0) + 1

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
            results, next_off = self._scroll_with_retry(
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

            offset = next_off
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
            results, next_off = self._scroll_with_retry(
                offset=offset,
                with_payload=False,
            )
            all_ids.extend(str(point.id) for point in results)
            offset = next_off
            if offset is None:
                break

        # Update in batches with retry logic
        import time

        max_retries = 3
        operations_per_batch = 50  # Smaller batches for stability

        for i in range(0, len(all_ids), batch_size):
            batch_ids = all_ids[i : i + batch_size]

            # Process in smaller sub-batches to avoid connection issues
            for j in range(0, len(batch_ids), operations_per_batch):
                sub_batch = batch_ids[j : j + operations_per_batch]

                for attempt in range(max_retries):
                    try:
                        sub_batch_citations = 0
                        for paper_id in sub_batch:
                            citing_papers = reverse_index.get(paper_id, [])
                            self.client.set_payload(
                                collection_name=self.collection_name,
                                payload={
                                    "cited_by": citing_papers,
                                    "cited_by_count": len(citing_papers),
                                    "graph_indexed": True,
                                },
                                points=[paper_id],
                                wait=True,
                            )
                            if citing_papers:
                                sub_batch_citations += 1
                        # Only update counters after successful batch
                        updated += len(sub_batch)
                        papers_with_citations += sub_batch_citations
                        break  # Success, exit retry loop
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"Update failed at {updated}/{len(all_ids)}, "
                                f"retrying ({attempt + 1}/{max_retries}): {e}"
                            )
                            time.sleep(2 ** (attempt + 1))  # Exponential backoff: 2, 4, 8 seconds
                        else:
                            logger.error(f"Failed after {max_retries} retries: {e}")
                            raise

                # Small delay between sub-batches to avoid overwhelming Qdrant
                time.sleep(0.05)

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

    def build_cited_by_incremental(
        self,
        batch_size: int = 100,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Incrementally update the cited_by field for papers.

        Only processes papers whose resolved_references have not yet been
        indexed into the cited_by reverse index (graph_indexed != True).
        For each such paper, appends its ID to the cited_by list of each
        referenced paper, then marks it as graph_indexed = True.

        Args:
            batch_size: Number of papers to update in each batch.
            progress_callback: Optional callback(processed, total) for progress.

        Returns:
            Statistics about the operation.
        """
        import time
        from collections import defaultdict

        logger.info("Building cited_by index (incremental)...")

        # Phase 1: Find papers with resolved_references that haven't been indexed
        unindexed_papers: list[tuple[str, list[str]]] = []

        unindexed_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="resolved_references",
                    match=models.MatchExcept(**{"except": []}),
                ),
            ],
            must_not=[
                models.FieldCondition(
                    key="graph_indexed",
                    match=models.MatchValue(value=True),
                ),
            ],
        )

        offset = None
        while True:
            results, next_off = self._scroll_with_retry(
                offset=offset,
                scroll_filter=unindexed_filter,
                with_payload=["resolved_references"],
            )

            for point in results:
                paper_id = str(point.id)
                resolved_refs = point.payload.get("resolved_references", [])
                if resolved_refs:
                    unindexed_papers.append((paper_id, resolved_refs))

            offset = next_off
            if offset is None:
                break

        if not unindexed_papers:
            logger.info("No unindexed papers found. cited_by is up to date.")
            return {
                "new_papers_processed": 0,
                "new_edges": 0,
                "papers_updated": 0,
            }

        logger.info(f"Found {len(unindexed_papers)} unindexed papers to process")

        # Phase 2: Build partial reverse index from unindexed papers only
        reverse_index: dict[str, list[str]] = defaultdict(list)
        total_new_edges = 0

        for paper_id, resolved_refs in unindexed_papers:
            for cited_id in resolved_refs:
                reverse_index[cited_id].append(paper_id)
                total_new_edges += 1

        logger.info(
            f"Partial reverse index: {total_new_edges} new edges, "
            f"{len(reverse_index)} cited papers to update"
        )

        # Phase 3: For each cited paper, read current cited_by and append new citers
        max_retries = 3
        updated = 0
        skipped_missing = 0
        cited_paper_ids = list(reverse_index.keys())

        for i in range(0, len(cited_paper_ids), batch_size):
            batch_ids = cited_paper_ids[i : i + batch_size]

            for attempt in range(max_retries):
                try:
                    for cited_id in batch_ids:
                        new_citers = reverse_index[cited_id]

                        # Read current cited_by; skip if cited point doesn't exist.
                        # resolve-refs can leave dangling IDs when a stub couldn't be
                        # created (e.g., ref had no DOI/arXiv/usable title). Updating
                        # cited_by on a nonexistent point would 404; skipping is safe
                        # because the back-reference would be unreachable anyway.
                        try:
                            points = self.client.retrieve(
                                collection_name=self.collection_name,
                                ids=[cited_id],
                                with_payload=["cited_by"],
                            )
                        except Exception:
                            points = []

                        if not points:
                            skipped_missing += 1
                            continue

                        current_cited_by = points[0].payload.get("cited_by", [])

                        # Merge (deduplicate)
                        existing_set = set(current_cited_by)
                        merged = current_cited_by + [
                            c for c in new_citers if c not in existing_set
                        ]

                        self.client.set_payload(
                            collection_name=self.collection_name,
                            payload={
                                "cited_by": merged,
                                "cited_by_count": len(merged),
                            },
                            points=[cited_id],
                            wait=True,
                        )

                    updated += len(batch_ids)
                    break  # Success
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Update failed at {updated}/{len(cited_paper_ids)}, "
                            f"retrying ({attempt + 1}/{max_retries}): {e}"
                        )
                        time.sleep(2 ** (attempt + 1))
                    else:
                        logger.error(f"Failed after {max_retries} retries: {e}")
                        raise

            if progress_callback:
                progress_callback(updated, len(cited_paper_ids))

            if updated % 5000 == 0 and updated > 0:
                logger.info(f"  Updated cited_by for {updated}/{len(cited_paper_ids)} papers...")

            time.sleep(0.05)

        # Phase 4: Mark all newly processed papers as graph_indexed
        logger.info(f"Marking {len(unindexed_papers)} papers as graph_indexed...")
        for i in range(0, len(unindexed_papers), batch_size):
            batch = unindexed_papers[i : i + batch_size]
            for paper_id, _ in batch:
                self.client.set_payload(
                    collection_name=self.collection_name,
                    payload={"graph_indexed": True},
                    points=[paper_id],
                )

        logger.info(
            f"Incremental cited_by complete: {len(unindexed_papers)} papers processed, "
            f"{total_new_edges} new edges, {updated} cited papers updated, "
            f"{skipped_missing} skipped (cited point not in Qdrant)"
        )

        return {
            "new_papers_processed": len(unindexed_papers),
            "new_edges": total_new_edges,
            "papers_updated": updated,
            "skipped_missing": skipped_missing,
        }
