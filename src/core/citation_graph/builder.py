"""Citation graph builder using NetworkX.

Builds directed graphs from Qdrant data or ReverseCitationIndex.
"""

import logging
from typing import Literal

import networkx as nx

from src.core.citation_graph.reverse_index import ReverseCitationIndex
from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


class CitationGraphBuilder:
    """Build NetworkX DiGraph from Qdrant data.

    Supports building full graphs or subgraphs around specific papers.
    """

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        reverse_index: ReverseCitationIndex | None = None,
    ):
        """Initialize the graph builder.

        Args:
            storage: QdrantStorage instance.
            reverse_index: Pre-built reverse index. If not provided, one will be built.
        """
        self.storage = storage or QdrantStorage()
        self._reverse_index = reverse_index

    def _ensure_index(self, include_metadata: bool = True) -> ReverseCitationIndex:
        """Ensure the reverse index is built.

        Args:
            include_metadata: Whether to include paper metadata.

        Returns:
            The reverse citation index.
        """
        if self._reverse_index is None:
            self._reverse_index = ReverseCitationIndex(self.storage)

        if not self._reverse_index._is_built:
            self._reverse_index.build_index(include_metadata=include_metadata)

        return self._reverse_index

    def build_graph(
        self,
        filter_venues: list[str] | None = None,
        filter_years: tuple[int, int] | None = None,
        include_metadata: bool = True,
    ) -> nx.DiGraph:
        """Build a full citation graph from all papers.

        Args:
            filter_venues: If provided, only include papers from these venues.
            filter_years: If provided, only include papers from (start_year, end_year) inclusive.
            include_metadata: Whether to add paper metadata as node attributes.

        Returns:
            NetworkX DiGraph with papers as nodes and citations as directed edges.
            Edge direction: citing_paper -> cited_paper (A cites B means edge A->B).
        """
        logger.info("Building citation graph...")

        # Build or retrieve reverse index
        index = self._ensure_index(include_metadata=include_metadata)

        # Create directed graph
        G = nx.DiGraph()

        # Collect papers to include (for filtering)
        papers_to_include: set[str] | None = None
        if filter_venues or filter_years:
            papers_to_include = set()
            for paper_id in index.get_all_paper_ids():
                metadata = index.get_paper_metadata(paper_id)
                if metadata is None:
                    continue

                # Filter by venue
                if filter_venues:
                    venue = metadata.get("venue", "")
                    if not any(v.lower() in venue.lower() for v in filter_venues):
                        continue

                # Filter by year
                if filter_years:
                    year = metadata.get("year")
                    if year is None or not (filter_years[0] <= year <= filter_years[1]):
                        continue

                papers_to_include.add(paper_id)

            logger.info(f"Filtered to {len(papers_to_include)} papers")

        # Add nodes with metadata
        node_count = 0
        for paper_id in index.get_all_paper_ids():
            if papers_to_include is not None and paper_id not in papers_to_include:
                continue

            node_attrs = {"id": paper_id}
            if include_metadata:
                metadata = index.get_paper_metadata(paper_id)
                if metadata:
                    node_attrs.update(metadata)

            G.add_node(paper_id, **node_attrs)
            node_count += 1

        logger.info(f"Added {node_count} nodes")

        # Add edges
        edge_count = 0
        for citing_id, cited_id in index.iter_all_edges():
            # Skip edges outside the filter
            if papers_to_include is not None:
                if citing_id not in papers_to_include or cited_id not in papers_to_include:
                    continue

            G.add_edge(citing_id, cited_id)
            edge_count += 1

        logger.info(f"Added {edge_count} edges")
        logger.info(f"Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

        return G

    def build_subgraph(
        self,
        center_paper_id: str,
        hops: int = 2,
        direction: Literal["both", "citing", "cited"] = "both",
        include_metadata: bool = True,
    ) -> nx.DiGraph:
        """Build a subgraph around a specific paper.

        Args:
            center_paper_id: The Qdrant point ID of the center paper.
            hops: Number of hops to traverse (1 = immediate neighbors, 2 = neighbors of neighbors).
            direction: Which edges to follow:
                - "both": Both citing and cited papers
                - "citing": Only papers that cite the center (incoming citations)
                - "cited": Only papers that the center cites (outgoing references)
            include_metadata: Whether to add paper metadata as node attributes.

        Returns:
            NetworkX DiGraph with the neighborhood subgraph.
        """
        logger.info(f"Building subgraph around {center_paper_id} ({hops} hops, {direction})...")

        # Build or retrieve reverse index
        index = self._ensure_index(include_metadata=include_metadata)

        # BFS to find papers within hops
        visited: set[str] = set()
        frontier: set[str] = {center_paper_id}

        for hop in range(hops):
            next_frontier: set[str] = set()
            for paper_id in frontier:
                if paper_id in visited:
                    continue
                visited.add(paper_id)

                # Get neighbors based on direction
                if direction in ("both", "citing"):
                    # Papers that cite this paper
                    next_frontier.update(index.get_citing_papers(paper_id))

                if direction in ("both", "cited"):
                    # Papers that this paper cites
                    next_frontier.update(index.get_cited_papers(paper_id))

            frontier = next_frontier - visited
            logger.debug(f"  Hop {hop + 1}: {len(frontier)} new papers")

        # Add final frontier to visited
        visited.update(frontier)

        logger.info(f"Found {len(visited)} papers in subgraph")

        # Build subgraph
        G = nx.DiGraph()

        # Add nodes
        for paper_id in visited:
            node_attrs = {"id": paper_id}
            if include_metadata:
                metadata = index.get_paper_metadata(paper_id)
                if metadata:
                    node_attrs.update(metadata)

            # Mark the center paper
            if paper_id == center_paper_id:
                node_attrs["is_center"] = True

            G.add_node(paper_id, **node_attrs)

        # Add edges (only within the subgraph)
        for paper_id in visited:
            cited_papers = index.get_cited_papers(paper_id)
            for cited_id in cited_papers:
                if cited_id in visited:
                    G.add_edge(paper_id, cited_id)

        logger.info(f"Subgraph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

        return G

    def build_ego_graph(
        self,
        center_paper_id: str,
        radius: int = 1,
        include_metadata: bool = True,
    ) -> nx.DiGraph:
        """Build an ego graph (all neighbors within radius).

        This is a convenience wrapper around build_subgraph with direction="both".

        Args:
            center_paper_id: The Qdrant point ID of the center paper.
            radius: Number of hops from center.
            include_metadata: Whether to add paper metadata.

        Returns:
            NetworkX DiGraph with the ego graph.
        """
        return self.build_subgraph(
            center_paper_id=center_paper_id,
            hops=radius,
            direction="both",
            include_metadata=include_metadata,
        )

    @property
    def reverse_index(self) -> ReverseCitationIndex | None:
        """Access the underlying reverse index."""
        return self._reverse_index
