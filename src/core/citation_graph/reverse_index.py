"""Reverse citation index for efficient "who cites this paper?" lookups.

Builds an in-memory index from resolved_references field in Qdrant.
"""

import logging
import sys
from collections import defaultdict
from typing import Iterator

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


def estimate_memory_mb(num_papers: int, num_edges: int, include_metadata: bool) -> float:
    """Estimate memory usage in MB for the citation index.

    Args:
        num_papers: Approximate number of papers.
        num_edges: Approximate number of citation edges.
        include_metadata: Whether metadata will be cached.

    Returns:
        Estimated memory usage in MB.
    """
    # UUID string: ~36 bytes + Python str overhead (~50 bytes) = ~90 bytes
    # List entry overhead: ~8 bytes (pointer)
    # Dict entry overhead: ~50 bytes

    # Forward index: num_citing_papers entries, each with list of refs
    # Assume ~70% of papers have refs
    citing_papers = int(num_papers * 0.7)
    forward_mb = (citing_papers * 50 + num_edges * 8) / (1024 * 1024)

    # Reverse index: similar structure
    reverse_mb = forward_mb

    # Metadata: ~500 bytes per paper (title, venue, year, etc.)
    metadata_mb = (num_papers * 500 / (1024 * 1024)) if include_metadata else 0

    # NetworkX graph overhead if building full graph: ~100 bytes per node, ~50 per edge
    # (This is separate but good to know)

    return forward_mb + reverse_mb + metadata_mb


class ReverseCitationIndex:
    """Build in-memory reverse citation index from resolved_references.

    The forward graph: paper A -> [list of papers A cites]
    The reverse index: paper B -> [list of papers that cite B]

    This enables answering "which papers cite paper B?" efficiently.
    """

    def __init__(self, storage: QdrantStorage | None = None):
        """Initialize the reverse citation index.

        Args:
            storage: QdrantStorage instance. Creates one if not provided.
        """
        self.storage = storage or QdrantStorage()

        # Forward index: paper_id -> [cited_paper_ids]
        self._forward: dict[str, list[str]] = {}

        # Reverse index: paper_id -> [citing_paper_ids]
        self._reverse: dict[str, list[str]] = defaultdict(list)

        # Paper metadata cache (for node attributes)
        self._metadata: dict[str, dict] = {}

        self._is_built = False

    def build_index(
        self,
        include_metadata: bool = True,
        warn_memory_gb: float = 2.0,
    ) -> None:
        """Build the reverse citation index by scanning all papers.

        Args:
            include_metadata: Whether to cache paper metadata (title, venue, year).
                            Needed for graph node attributes. Adds memory overhead.
                            Set to False to reduce memory by ~40%.
            warn_memory_gb: Warn if estimated memory exceeds this threshold (in GB).
        """
        logger.info("Building reverse citation index...")

        # Fields to retrieve
        fields = ["resolved_references"]
        if include_metadata:
            fields.extend(["title", "venue", "year", "citation_count", "doi", "authors"])

        # Scroll through all papers
        offset = None
        total_papers = 0
        total_edges = 0

        while True:
            results, offset = self.storage.client.scroll(
                collection_name=self.storage.collection_name,
                limit=1000,
                offset=offset,
                with_payload=fields,
            )

            for point in results:
                paper_id = str(point.id)
                payload = point.payload

                # Store metadata
                if include_metadata:
                    self._metadata[paper_id] = {
                        "title": payload.get("title", ""),
                        "venue": payload.get("venue", ""),
                        "year": payload.get("year"),
                        "citation_count": payload.get("citation_count", 0),
                        "doi": payload.get("doi"),
                        "authors": payload.get("authors", []),
                    }

                # Get resolved references (papers this paper cites)
                resolved_refs = payload.get("resolved_references", [])
                if resolved_refs:
                    self._forward[paper_id] = resolved_refs
                    total_edges += len(resolved_refs)

                    # Build reverse index
                    for cited_id in resolved_refs:
                        self._reverse[cited_id].append(paper_id)

                total_papers += 1

            if total_papers % 10000 == 0:
                logger.info(f"  Processed {total_papers} papers, {total_edges} edges...")

            if offset is None:
                break

        self._is_built = True

        # Estimate and report memory usage
        est_memory_mb = estimate_memory_mb(total_papers, total_edges, include_metadata)
        est_memory_gb = est_memory_mb / 1024

        logger.info(
            f"Built reverse citation index: {total_papers:,} papers, "
            f"{total_edges:,} edges, {len(self._reverse):,} cited papers"
        )
        logger.info(f"Estimated memory usage: {est_memory_mb:.0f} MB ({est_memory_gb:.2f} GB)")

        if est_memory_gb > warn_memory_gb:
            logger.warning(
                f"Memory usage ({est_memory_gb:.1f} GB) exceeds threshold ({warn_memory_gb} GB). "
                f"Consider using include_metadata=False or streaming export."
            )

    def get_citing_papers(self, paper_id: str) -> list[str]:
        """Get papers that cite the given paper.

        Args:
            paper_id: The Qdrant point ID of the paper.

        Returns:
            List of point IDs of papers that cite this paper.
        """
        if not self._is_built:
            raise RuntimeError("Index not built. Call build_index() first.")
        return self._reverse.get(paper_id, [])

    def get_cited_papers(self, paper_id: str) -> list[str]:
        """Get papers that the given paper cites.

        Args:
            paper_id: The Qdrant point ID of the paper.

        Returns:
            List of point IDs of papers cited by this paper.
        """
        if not self._is_built:
            raise RuntimeError("Index not built. Call build_index() first.")
        return self._forward.get(paper_id, [])

    def get_citation_count(self, paper_id: str) -> int:
        """Get the number of papers citing this paper (in-corpus).

        Note: This is the in-corpus citation count, not the global count.

        Args:
            paper_id: The Qdrant point ID of the paper.

        Returns:
            Number of papers in the corpus that cite this paper.
        """
        if not self._is_built:
            raise RuntimeError("Index not built. Call build_index() first.")
        return len(self._reverse.get(paper_id, []))

    def get_reference_count(self, paper_id: str) -> int:
        """Get the number of papers this paper cites (resolved).

        Args:
            paper_id: The Qdrant point ID of the paper.

        Returns:
            Number of resolved references for this paper.
        """
        if not self._is_built:
            raise RuntimeError("Index not built. Call build_index() first.")
        return len(self._forward.get(paper_id, []))

    def iter_all_edges(self) -> Iterator[tuple[str, str]]:
        """Iterate over all citation edges in the graph.

        Yields:
            Tuples of (citing_paper_id, cited_paper_id) representing edges.
        """
        if not self._is_built:
            raise RuntimeError("Index not built. Call build_index() first.")

        for citing_id, cited_ids in self._forward.items():
            for cited_id in cited_ids:
                yield (citing_id, cited_id)

    def get_paper_metadata(self, paper_id: str) -> dict | None:
        """Get cached metadata for a paper.

        Args:
            paper_id: The Qdrant point ID of the paper.

        Returns:
            Metadata dict or None if not cached.
        """
        return self._metadata.get(paper_id)

    def get_all_paper_ids(self) -> set[str]:
        """Get all paper IDs in the index (both citing and cited).

        Returns:
            Set of all paper IDs.
        """
        if not self._is_built:
            raise RuntimeError("Index not built. Call build_index() first.")

        all_ids = set(self._forward.keys())
        all_ids.update(self._reverse.keys())
        return all_ids

    @property
    def num_papers(self) -> int:
        """Number of papers with at least one edge."""
        if not self._is_built:
            return 0
        return len(self.get_all_paper_ids())

    @property
    def num_edges(self) -> int:
        """Total number of citation edges."""
        if not self._is_built:
            return 0
        return sum(len(refs) for refs in self._forward.values())

    @property
    def num_citing_papers(self) -> int:
        """Number of papers that cite at least one paper."""
        if not self._is_built:
            return 0
        return len(self._forward)

    @property
    def num_cited_papers(self) -> int:
        """Number of papers that are cited by at least one paper."""
        if not self._is_built:
            return 0
        return len(self._reverse)

    def get_stats(self) -> dict:
        """Get summary statistics about the citation index.

        Returns:
            Dictionary with index statistics.
        """
        if not self._is_built:
            return {"is_built": False}

        citing_counts = [len(refs) for refs in self._forward.values()]
        cited_counts = [len(refs) for refs in self._reverse.values()]

        est_memory_mb = estimate_memory_mb(
            self.num_papers, self.num_edges, bool(self._metadata)
        )

        return {
            "is_built": True,
            "num_papers": self.num_papers,
            "num_edges": self.num_edges,
            "num_citing_papers": self.num_citing_papers,
            "num_cited_papers": self.num_cited_papers,
            "avg_refs_per_paper": sum(citing_counts) / len(citing_counts) if citing_counts else 0,
            "avg_citations_per_paper": sum(cited_counts) / len(cited_counts) if cited_counts else 0,
            "max_refs": max(citing_counts) if citing_counts else 0,
            "max_citations": max(cited_counts) if cited_counts else 0,
            "has_metadata": bool(self._metadata),
            "estimated_memory_mb": est_memory_mb,
        }

    def clear(self) -> None:
        """Clear the index to free memory."""
        self._forward.clear()
        self._reverse.clear()
        self._metadata.clear()
        self._is_built = False
        logger.info("Cleared citation index")
