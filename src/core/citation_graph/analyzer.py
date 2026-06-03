"""Graph analysis for citation networks.

Provides PageRank, HITS, community detection, and other metrics.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from qdrant_client.http.exceptions import UnexpectedResponse

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


@dataclass
class GraphMetrics:
    """Container for global graph metrics."""

    num_nodes: int = 0
    num_edges: int = 0
    density: float = 0.0
    is_weakly_connected: bool = False
    num_weakly_connected_components: int = 0
    largest_wcc_size: int = 0
    avg_in_degree: float = 0.0
    avg_out_degree: float = 0.0
    max_in_degree: int = 0
    max_out_degree: int = 0
    avg_clustering: float = 0.0
    reciprocity: float = 0.0


@dataclass
class AnalysisResults:
    """Container for analysis results."""

    metrics: GraphMetrics = field(default_factory=GraphMetrics)
    pagerank: dict[str, float] = field(default_factory=dict)
    hubs: dict[str, float] = field(default_factory=dict)
    authorities: dict[str, float] = field(default_factory=dict)
    communities: dict[str, int] = field(default_factory=dict)


class GraphAnalyzer:
    """Compute graph metrics and centrality measures.

    Supports:
    - Global graph metrics (density, connectivity, etc.)
    - PageRank (paper importance by citation flow)
    - HITS (hubs and authorities)
    - Community detection (Louvain algorithm)
    """

    def __init__(
        self,
        graph: nx.DiGraph,
        storage: QdrantStorage | None = None,
    ):
        """Initialize the analyzer.

        Args:
            graph: NetworkX DiGraph to analyze.
            storage: QdrantStorage for persisting metrics. Optional.
        """
        self.graph = graph
        self.storage = storage

    def compute_global_metrics(self) -> GraphMetrics:
        """Compute global graph statistics.

        Returns:
            GraphMetrics dataclass with statistics.
        """
        logger.info("Computing global graph metrics...")

        G = self.graph
        metrics = GraphMetrics()

        metrics.num_nodes = G.number_of_nodes()
        metrics.num_edges = G.number_of_edges()

        if metrics.num_nodes == 0:
            logger.warning("Graph is empty")
            return metrics

        # Density
        metrics.density = nx.density(G)

        # Connectivity
        metrics.is_weakly_connected = nx.is_weakly_connected(G)
        wccs = list(nx.weakly_connected_components(G))
        metrics.num_weakly_connected_components = len(wccs)
        metrics.largest_wcc_size = max(len(wcc) for wcc in wccs) if wccs else 0

        # Degree statistics
        in_degrees = [d for _, d in G.in_degree()]
        out_degrees = [d for _, d in G.out_degree()]

        metrics.avg_in_degree = sum(in_degrees) / len(in_degrees) if in_degrees else 0
        metrics.avg_out_degree = sum(out_degrees) / len(out_degrees) if out_degrees else 0
        metrics.max_in_degree = max(in_degrees) if in_degrees else 0
        metrics.max_out_degree = max(out_degrees) if out_degrees else 0

        # Clustering (on undirected version)
        try:
            metrics.avg_clustering = nx.average_clustering(G.to_undirected())
        except Exception:
            metrics.avg_clustering = 0.0

        # Reciprocity (fraction of edges that are reciprocated)
        metrics.reciprocity = nx.reciprocity(G)

        logger.info(
            f"Graph metrics: {metrics.num_nodes} nodes, {metrics.num_edges} edges, "
            f"density={metrics.density:.6f}"
        )

        return metrics

    def compute_pagerank(
        self,
        alpha: float = 0.85,
        max_iter: int = 100,
        tol: float = 1e-6,
    ) -> dict[str, float]:
        """Compute PageRank scores for all nodes.

        PageRank measures paper importance by modeling citation flow.
        Papers with many citations from important papers have high PageRank.

        Args:
            alpha: Damping factor (probability of following a citation).
            max_iter: Maximum iterations for convergence.
            tol: Convergence tolerance.

        Returns:
            Dictionary mapping paper_id to PageRank score.
        """
        logger.info("Computing PageRank...")

        if self.graph.number_of_nodes() == 0:
            return {}

        # Note: PageRank is computed on the graph where edges point
        # from citing to cited papers (A cites B means edge A->B).
        # This means highly cited papers will have high PageRank.
        pagerank = nx.pagerank(
            self.graph,
            alpha=alpha,
            max_iter=max_iter,
            tol=tol,
        )

        logger.info(f"Computed PageRank for {len(pagerank)} nodes")
        return pagerank

    def compute_hits(
        self,
        max_iter: int = 100,
        tol: float = 1e-8,
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Compute HITS hub and authority scores.

        HITS identifies:
        - Hubs: Papers that cite many important papers (good survey/review papers)
        - Authorities: Papers that are cited by many hubs (influential papers)

        Args:
            max_iter: Maximum iterations for convergence.
            tol: Convergence tolerance.

        Returns:
            Tuple of (hubs_dict, authorities_dict).
        """
        logger.info("Computing HITS scores...")

        if self.graph.number_of_nodes() == 0:
            return {}, {}

        hubs, authorities = nx.hits(
            self.graph,
            max_iter=max_iter,
            tol=tol,
        )

        logger.info(f"Computed HITS for {len(hubs)} nodes")
        return hubs, authorities

    def compute_communities(
        self,
        resolution: float = 1.0,
    ) -> dict[str, int]:
        """Detect communities using the Louvain algorithm.

        Communities are groups of papers that are more densely connected
        to each other than to the rest of the network (research topics/fields).

        Args:
            resolution: Resolution parameter for Louvain.
                       Higher values = more/smaller communities.

        Returns:
            Dictionary mapping paper_id to community_id.
        """
        logger.info("Detecting communities...")

        if self.graph.number_of_nodes() == 0:
            return {}

        # Louvain requires undirected graph
        G_undirected = self.graph.to_undirected()

        try:
            # Use louvain_communities from networkx
            communities_list = nx.community.louvain_communities(
                G_undirected,
                resolution=resolution,
                seed=42,  # For reproducibility
            )

            # Convert to node -> community_id mapping
            communities = {}
            for community_id, community_nodes in enumerate(communities_list):
                for node in community_nodes:
                    communities[node] = community_id

            logger.info(
                f"Detected {len(communities_list)} communities "
                f"for {len(communities)} nodes"
            )
            return communities

        except Exception as e:
            logger.warning(f"Community detection failed: {e}")
            return {}

    def get_top_papers(
        self,
        metric: str,
        n: int = 10,
        scores: dict[str, float] | None = None,
    ) -> list[tuple[str, float, dict | None]]:
        """Get top papers by a metric.

        Args:
            metric: Metric name ("pagerank", "hub", "authority", "in_degree", "out_degree").
            n: Number of top papers to return.
            scores: Pre-computed scores dictionary. If None, computes them.

        Returns:
            List of (paper_id, score, metadata) tuples sorted by score descending.
        """
        if scores is None:
            if metric == "pagerank":
                scores = self.compute_pagerank()
            elif metric == "hub":
                scores, _ = self.compute_hits()
            elif metric == "authority":
                _, scores = self.compute_hits()
            elif metric == "in_degree":
                scores = {node: deg for node, deg in self.graph.in_degree()}
            elif metric == "out_degree":
                scores = {node: deg for node, deg in self.graph.out_degree()}
            else:
                raise ValueError(f"Unknown metric: {metric}")

        # Sort by score
        sorted_papers = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n]

        # Add metadata
        results = []
        for paper_id, score in sorted_papers:
            metadata = self.graph.nodes.get(paper_id, {})
            results.append((paper_id, score, metadata if metadata else None))

        return results

    def compute_all(
        self,
        pagerank_alpha: float = 0.85,
        community_resolution: float = 1.0,
    ) -> AnalysisResults:
        """Compute all analysis metrics.

        Args:
            pagerank_alpha: Damping factor for PageRank.
            community_resolution: Resolution for community detection.

        Returns:
            AnalysisResults with all computed metrics.
        """
        results = AnalysisResults()

        results.metrics = self.compute_global_metrics()
        results.pagerank = self.compute_pagerank(alpha=pagerank_alpha)
        results.hubs, results.authorities = self.compute_hits()
        results.communities = self.compute_communities(resolution=community_resolution)

        return results

    def store_metrics_to_qdrant(
        self,
        pagerank: dict[str, float] | None = None,
        hubs: dict[str, float] | None = None,
        authorities: dict[str, float] | None = None,
        communities: dict[str, int] | None = None,
        batch_size: int = 100,
    ) -> int:
        """Store computed metrics back to Qdrant.

        Adds/updates payload fields:
        - pagerank: float
        - hub_score: float
        - authority_score: float
        - community_id: int

        Args:
            pagerank: PageRank scores to store.
            hubs: Hub scores to store.
            authorities: Authority scores to store.
            communities: Community assignments to store.
            batch_size: Number of updates per batch.

        Returns:
            Number of papers updated.
        """
        if self.storage is None:
            raise RuntimeError("Storage not configured. Pass storage to constructor.")

        logger.info("Storing metrics to Qdrant...")

        # Collect all paper IDs to update
        all_paper_ids = set()
        if pagerank:
            all_paper_ids.update(pagerank.keys())
        if hubs:
            all_paper_ids.update(hubs.keys())
        if authorities:
            all_paper_ids.update(authorities.keys())
        if communities:
            all_paper_ids.update(communities.keys())

        if not all_paper_ids:
            logger.warning("No metrics to store")
            return 0

        # Batch update
        updates: list[tuple[str, dict[str, Any]]] = []
        for paper_id in all_paper_ids:
            payload: dict[str, Any] = {}

            if pagerank and paper_id in pagerank:
                payload["pagerank"] = pagerank[paper_id]
            if hubs and paper_id in hubs:
                payload["hub_score"] = hubs[paper_id]
            if authorities and paper_id in authorities:
                payload["authority_score"] = authorities[paper_id]
            if communities and paper_id in communities:
                payload["community_id"] = communities[paper_id]

            if payload:
                updates.append((paper_id, payload))

        # Apply updates in batches
        updated = 0
        skipped = 0
        for i in range(0, len(updates), batch_size):
            batch = updates[i : i + batch_size]
            for point_id, payload in batch:
                try:
                    self.storage.client.set_payload(
                        collection_name=self.storage.collection_name,
                        payload=payload,
                        points=[point_id],
                    )
                    updated += 1
                except UnexpectedResponse as e:
                    # The graph includes dangling citation targets (node IDs that
                    # were never stored as points). set_payload 404s on those;
                    # skip them rather than aborting the whole run.
                    if e.status_code == 404:
                        skipped += 1
                        continue
                    raise

            if updated and updated % 1000 == 0:
                logger.info(f"  Updated {updated} papers...")

        if skipped:
            logger.info(f"Skipped {skipped} dangling node(s) not present in Qdrant")
        logger.info(f"Stored metrics for {updated} papers")
        return updated

    def get_in_corpus_citation_counts(self) -> dict[str, int]:
        """Get in-corpus citation counts (in-degree).

        This is the number of papers in the corpus that cite each paper,
        which may differ from the global citation count from external sources.

        Returns:
            Dictionary mapping paper_id to in-corpus citation count.
        """
        return {node: deg for node, deg in self.graph.in_degree()}
