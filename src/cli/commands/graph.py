"""Citation graph commands for LexiconArxiv CLI."""

import json
import logging
import sys

import click

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


def register_commands(cli: click.Group):

    @cli.command("build-citation-graph")
    @click.option("--output", "-o", type=click.Path(), help="Output file path")
    @click.option("--format", "-f", type=click.Choice(["json", "csv", "graphml", "gexf"]),
                  default="json", help="Export format (default: json)")
    @click.option("--venue", "-v", multiple=True, help="Filter by venue (can repeat)")
    @click.option("--year-start", type=int, help="Filter papers from this year")
    @click.option("--year-end", type=int, help="Filter papers until this year")
    @click.option("--no-metadata", is_flag=True, help="Don't include paper metadata in export")
    @click.option("--streaming", is_flag=True, help="Use streaming export (low memory, CSV only)")
    def build_citation_graph(
        output: str | None,
        format: str,
        venue: tuple[str, ...],
        year_start: int | None,
        year_end: int | None,
        no_metadata: bool,
        streaming: bool,
    ) -> None:
        """Build and export the citation graph.

        Creates a directed graph from resolved_references where edges point
        from citing papers to cited papers (A cites B means edge A->B).

        For large graphs (>1M edges), use --streaming to avoid memory issues.
        Streaming mode exports CSV files directly without loading the full graph.

        Examples:

          # Build and export to JSON
          python -m src.cli.core_collect build-citation-graph -o graph.json

          # Export for Gephi
          python -m src.cli.core_collect build-citation-graph -o graph.graphml --format graphml

          # Filter by venue
          python -m src.cli.core_collect build-citation-graph -v ACL -v EMNLP -o nlp_graph.json

          # Filter by year range
          python -m src.cli.core_collect build-citation-graph --year-start 2020 --year-end 2023 -o recent.json

          # Large graph: use streaming export (low memory)
          python -m src.cli.core_collect build-citation-graph -o /tmp/graph --streaming
        """
        from src.core.citation_graph import CitationGraphBuilder, GraphExporter, StreamingGraphExporter, estimate_memory_mb

        click.echo("\n=== Building Citation Graph ===\n")

        storage = QdrantStorage()

        # Streaming mode: export directly from Qdrant
        if streaming:
            if venue or year_start or year_end:
                click.echo("Warning: Filters are not supported in streaming mode. Exporting full graph.")

            if not output:
                click.echo("Error: --output is required for streaming export")
                sys.exit(1)

            click.echo("Using streaming export (low memory mode)...")
            exporter = StreamingGraphExporter(storage)
            result = exporter.export_csv(
                output_dir=output,
                prefix="citation_graph",
                include_metadata=not no_metadata,
            )

            click.echo(f"\nStreaming export complete:")
            click.echo(f"  Nodes: {result['node_count']:,}")
            click.echo(f"  Edges: {result['edge_count']:,}")
            click.echo(f"  Files: {result['edges_file']}")
            click.echo(f"         {result['nodes_file']}")
            return

        # Check graph size and warn about memory
        stats = storage.get_citation_graph_stats()
        est_memory = estimate_memory_mb(
            stats["total_papers"],
            stats["total_resolved_refs"],
            not no_metadata,
        )

        click.echo(f"Estimated graph size: {stats['total_papers']:,} nodes, {stats['total_resolved_refs']:,} edges")
        click.echo(f"Estimated memory: {est_memory:.0f} MB ({est_memory/1024:.1f} GB)")

        if est_memory > 2000:  # > 2 GB
            click.echo("\nWarning: Large graph may require significant memory.")
            click.echo("Consider using --streaming for memory-efficient CSV export.")
            click.echo("Or use --no-metadata to reduce memory by ~40%.\n")

        builder = CitationGraphBuilder(storage=storage)

        # Build filters
        filter_venues = list(venue) if venue else None
        filter_years = None
        if year_start or year_end:
            filter_years = (year_start or 1900, year_end or 2100)
            click.echo(f"Year filter: {filter_years[0]}-{filter_years[1]}")
        if filter_venues:
            click.echo(f"Venue filter: {', '.join(filter_venues)}")

        # Build graph
        click.echo("Building graph from resolved_references...")
        graph = builder.build_graph(
            filter_venues=filter_venues,
            filter_years=filter_years,
            include_metadata=not no_metadata,
        )

        click.echo(f"\nGraph built:")
        click.echo(f"  Nodes: {graph.number_of_nodes():,}")
        click.echo(f"  Edges: {graph.number_of_edges():,}")

        # Export if output specified
        if output:
            exporter = GraphExporter(graph)
            exporter.export(output, format=format)
            click.echo(f"\nExported to: {output}")
        else:
            click.echo("\nNo output file specified. Use -o to export.")

    @cli.command("analyze-citation-graph")
    @click.option("--compute-pagerank", is_flag=True, help="Compute PageRank scores")
    @click.option("--compute-hits", is_flag=True, help="Compute HITS hub/authority scores")
    @click.option("--compute-communities", is_flag=True, help="Detect communities")
    @click.option("--all", "compute_all", is_flag=True, help="Compute all metrics")
    @click.option("--top-n", type=int, default=10, help="Show top N papers per metric")
    @click.option("--store", is_flag=True, help="Store metrics to Qdrant")
    @click.option("--pagerank-alpha", type=float, default=0.85, help="PageRank damping factor")
    @click.option("--community-resolution", type=float, default=1.0, help="Community detection resolution")
    def analyze_citation_graph(
        compute_pagerank: bool,
        compute_hits: bool,
        compute_communities: bool,
        compute_all: bool,
        top_n: int,
        store: bool,
        pagerank_alpha: float,
        community_resolution: float,
    ) -> None:
        """Analyze the citation graph and compute metrics.

        Computes:
        - PageRank: Paper importance by citation flow
        - HITS: Hub (good surveys) and authority (influential) scores
        - Communities: Research topic clusters

        Examples:

          # Compute all metrics and show top papers
          python -m src.cli.core_collect analyze-citation-graph --all --top-n 50

          # Compute PageRank and store to Qdrant
          python -m src.cli.core_collect analyze-citation-graph --compute-pagerank --store

          # Detect communities
          python -m src.cli.core_collect analyze-citation-graph --compute-communities
        """
        from src.core.citation_graph import CitationGraphBuilder, GraphAnalyzer, estimate_memory_mb

        click.echo("\n=== Analyzing Citation Graph ===\n")

        # Check graph size and warn about memory
        storage = QdrantStorage()
        stats = storage.get_citation_graph_stats()
        est_memory = estimate_memory_mb(
            stats["total_papers"],
            stats["total_resolved_refs"],
            True,  # Analysis needs metadata
        )

        click.echo(f"Estimated graph size: {stats['total_papers']:,} nodes, {stats['total_resolved_refs']:,} edges")
        click.echo(f"Estimated memory: {est_memory:.0f} MB ({est_memory/1024:.1f} GB)")

        if est_memory > 3000:  # > 3 GB
            click.echo("\nWarning: Graph analysis may require significant memory (3+ GB).")
            click.echo("Ensure sufficient RAM is available.\n")

        # Build graph
        builder = CitationGraphBuilder(storage=storage)

        click.echo("Building graph...")
        graph = builder.build_graph(include_metadata=True)

        click.echo(f"Graph: {graph.number_of_nodes():,} nodes, {graph.number_of_edges():,} edges\n")

        if graph.number_of_nodes() == 0:
            click.echo("Graph is empty. Run resolve-refs first to build citation edges.")
            return

        analyzer = GraphAnalyzer(graph, storage=storage)

        # Compute global metrics
        metrics = analyzer.compute_global_metrics()
        click.echo("=== Global Metrics ===\n")
        click.echo(f"  Nodes:                  {metrics.num_nodes:,}")
        click.echo(f"  Edges:                  {metrics.num_edges:,}")
        click.echo(f"  Density:                {metrics.density:.6f}")
        click.echo(f"  Weakly connected:       {'Yes' if metrics.is_weakly_connected else 'No'}")
        click.echo(f"  Weakly connected comps: {metrics.num_weakly_connected_components:,}")
        click.echo(f"  Largest WCC size:       {metrics.largest_wcc_size:,}")
        click.echo(f"  Avg in-degree:          {metrics.avg_in_degree:.2f}")
        click.echo(f"  Avg out-degree:         {metrics.avg_out_degree:.2f}")
        click.echo(f"  Max in-degree:          {metrics.max_in_degree:,}")
        click.echo(f"  Max out-degree:         {metrics.max_out_degree:,}")
        click.echo(f"  Avg clustering:         {metrics.avg_clustering:.4f}")
        click.echo(f"  Reciprocity:            {metrics.reciprocity:.4f}")

        pagerank = None
        hubs = None
        authorities = None
        communities = None

        # Compute PageRank
        if compute_pagerank or compute_all:
            click.echo("\n=== PageRank ===\n")
            pagerank = analyzer.compute_pagerank(alpha=pagerank_alpha)

            top_papers = analyzer.get_top_papers("pagerank", n=top_n, scores=pagerank)
            click.echo(f"Top {top_n} papers by PageRank:\n")
            for i, (paper_id, score, metadata) in enumerate(top_papers, 1):
                title = ((metadata.get("title") or "")[:60] + "...") if metadata else paper_id[:30]
                year = metadata.get("year", "") if metadata else ""
                click.echo(f"  {i:3}. [{year}] {title}")
                click.echo(f"       PageRank: {score:.6f}  ID: {paper_id[:20]}...")

        # Compute HITS
        if compute_hits or compute_all:
            click.echo("\n=== HITS Scores ===\n")
            hubs, authorities = analyzer.compute_hits()

            click.echo(f"Top {top_n} Hub papers (cite many important papers):\n")
            top_hubs = analyzer.get_top_papers("hub", n=top_n, scores=hubs)
            for i, (paper_id, score, metadata) in enumerate(top_hubs, 1):
                title = ((metadata.get("title") or "")[:60] + "...") if metadata else paper_id[:30]
                click.echo(f"  {i:3}. Hub: {score:.6f}  {title}")

            click.echo(f"\nTop {top_n} Authority papers (cited by many hubs):\n")
            top_auths = analyzer.get_top_papers("authority", n=top_n, scores=authorities)
            for i, (paper_id, score, metadata) in enumerate(top_auths, 1):
                title = ((metadata.get("title") or "")[:60] + "...") if metadata else paper_id[:30]
                click.echo(f"  {i:3}. Authority: {score:.6f}  {title}")

        # Compute communities
        if compute_communities or compute_all:
            click.echo("\n=== Communities ===\n")
            communities = analyzer.compute_communities(resolution=community_resolution)

            if communities:
                # Count community sizes
                from collections import Counter
                community_sizes = Counter(communities.values())
                click.echo(f"Detected {len(community_sizes)} communities")
                click.echo(f"\nTop 10 largest communities:")
                for comm_id, size in community_sizes.most_common(10):
                    click.echo(f"  Community {comm_id}: {size:,} papers")

        # Store metrics
        if store and (pagerank or hubs or authorities or communities):
            click.echo("\n=== Storing Metrics ===\n")
            updated = analyzer.store_metrics_to_qdrant(
                pagerank=pagerank,
                hubs=hubs,
                authorities=authorities,
                communities=communities,
            )
            click.echo(f"Stored metrics for {updated:,} papers")

    @cli.command("citation-graph-stats")
    @click.option("--json", "output_json", is_flag=True, help="Output as JSON")
    def citation_graph_stats(output_json: bool) -> None:
        """Show citation graph statistics.

        Displays statistics about the citation graph including:
        - Number of papers with references
        - Number of resolved citation edges
        - Resolution coverage

        Examples:

          python -m src.cli.core_collect citation-graph-stats
          python -m src.cli.core_collect citation-graph-stats --json
        """
        try:
            storage = QdrantStorage()
            click.echo("Analyzing citation graph (this may take a moment)...")
            stats = storage.get_citation_graph_stats()
        except Exception as e:
            click.echo(f"Error connecting to Qdrant: {e}")
            sys.exit(1)

        if output_json:
            click.echo(json.dumps(stats, indent=2))
            return

        from src.core.citation_graph import estimate_memory_mb

        click.echo(f"\n{'=' * 50}")
        click.echo("CITATION GRAPH STATISTICS")
        click.echo(f"{'=' * 50}\n")

        click.echo(f"Total papers:                 {stats['total_papers']:,}")
        click.echo(f"Papers with references:       {stats['papers_with_refs']:,}")
        click.echo(f"Papers with resolved refs:    {stats['papers_with_resolved_refs']:,}")
        click.echo(f"Total raw references:         {stats['total_raw_refs']:,}")
        click.echo(f"Total resolved references:    {stats['total_resolved_refs']:,}")
        click.echo(f"Resolution coverage:          {stats['resolution_coverage']:.1f}%")
        click.echo(f"Papers with graph metrics:    {stats['papers_with_graph_metrics']:,}")

        # Memory estimates
        est_with_meta = estimate_memory_mb(stats['total_papers'], stats['total_resolved_refs'], True)
        est_no_meta = estimate_memory_mb(stats['total_papers'], stats['total_resolved_refs'], False)

        click.echo(f"\n=== Memory Estimates ===\n")
        click.echo(f"With metadata:     {est_with_meta:.0f} MB ({est_with_meta/1024:.1f} GB)")
        click.echo(f"Without metadata:  {est_no_meta:.0f} MB ({est_no_meta/1024:.1f} GB)")
        if est_with_meta > 2000:
            click.echo(f"\nTip: Use --streaming for memory-efficient CSV export")

    @cli.command("build-cited-by")
    @click.option("--incremental", is_flag=True, help="Only process papers not yet indexed (graph_indexed != True)")
    @click.option("--full", "force_full", is_flag=True, help="Force full rebuild even if incremental is possible")
    def build_cited_by(incremental: bool, force_full: bool) -> None:
        """Build the cited_by field for all papers (required for GraphRAG).

        Scans all papers' resolved_references and builds a reverse index,
        storing the `cited_by` list in each paper's payload. This enables
        O(1) bidirectional citation traversal for GraphRAG queries.

        After running this command, each paper will have:
        - resolved_references: papers this paper cites
        - cited_by: papers that cite this paper

        Use --incremental for efficient updates after new papers are resolved.
        This only processes papers whose resolved_references haven't been
        indexed yet (graph_indexed != True).

        Examples:

          # Full rebuild
          python -m src.cli.core_collect build-cited-by

          # Incremental update (after new papers resolved)
          python -m src.cli.core_collect build-cited-by --incremental
        """
        storage = QdrantStorage()

        if incremental and not force_full:
            click.echo("\n=== Building cited_by Index (Incremental) ===\n")
            click.echo("Processing only papers not yet indexed (graph_indexed != True).\n")

            def progress(processed: int, total: int) -> None:
                if processed % 2000 == 0 or processed == total:
                    pct = processed / total * 100 if total > 0 else 0
                    click.echo(f"  Progress: {processed:,}/{total:,} ({pct:.1f}%)")

            result = storage.build_cited_by_incremental(progress_callback=progress)

            click.echo(f"\n=== Complete ===\n")
            click.echo(f"New papers processed:      {result['new_papers_processed']:,}")
            click.echo(f"New citation edges:         {result['new_edges']:,}")
            click.echo(f"Cited papers updated:      {result['papers_updated']:,}")

            if result["new_papers_processed"] == 0:
                click.echo("\nNo new papers to index. cited_by is already up to date.")
            else:
                click.echo("\nThe cited_by field has been incrementally updated.")
        else:
            click.echo("\n=== Building cited_by Index (Full Rebuild) ===\n")
            click.echo("This will scan all papers and compute reverse citations.")
            click.echo("Progress will be logged every 5000 papers.\n")

            def progress(processed: int, total: int) -> None:
                if processed % 5000 == 0 or processed == total:
                    pct = processed / total * 100 if total > 0 else 0
                    click.echo(f"  Progress: {processed:,}/{total:,} ({pct:.1f}%)")

            result = storage.build_cited_by_index(progress_callback=progress)

            click.echo(f"\n=== Complete ===\n")
            click.echo(f"Total papers:              {result['total_papers']:,}")
            click.echo(f"Total citation edges:      {result['total_edges']:,}")
            click.echo(f"Papers with citations:     {result['papers_with_citations']:,}")
            click.echo(f"Unique cited papers:       {result['unique_cited_papers']:,}")

        click.echo("\nThe cited_by field is now available for GraphRAG queries.")
        click.echo("Use get-citing-papers <paper_id> to query reverse citations.")

    @cli.command("get-citing-papers")
    @click.argument("paper_id")
    @click.option("--limit", "-n", type=int, default=20, help="Max papers to show")
    @click.option("--json", "output_json", is_flag=True, help="Output as JSON")
    def get_citing_papers(paper_id: str, limit: int, output_json: bool) -> None:
        """Find papers that cite the given paper.

        PAPER_ID is the Qdrant point ID of the paper.

        Examples:

          python -m src.cli.core_collect get-citing-papers abc123-def456
          python -m src.cli.core_collect get-citing-papers abc123-def456 --limit 50
        """
        from src.core.citation_graph import ReverseCitationIndex

        storage = QdrantStorage()

        # Get the paper info
        paper = storage.get_paper_by_id(paper_id)
        if paper is None:
            click.echo(f"Paper not found: {paper_id}")
            sys.exit(1)

        click.echo(f"\nPaper: {paper.get('title', 'Unknown')[:80]}")
        click.echo(f"Year:  {paper.get('year', 'Unknown')}")
        click.echo(f"Venue: {paper.get('venue', 'Unknown')}")

        # Build reverse index
        click.echo("\nBuilding citation index...")
        index = ReverseCitationIndex(storage)
        index.build_index(include_metadata=True)

        # Get citing papers
        citing_ids = index.get_citing_papers(paper_id)
        click.echo(f"\nFound {len(citing_ids)} papers citing this paper")

        if not citing_ids:
            return

        if output_json:
            results = []
            for cid in citing_ids[:limit]:
                metadata = index.get_paper_metadata(cid)
                results.append({"id": cid, **(metadata or {})})
            click.echo(json.dumps(results, indent=2, default=str))
            return

        click.echo(f"\nShowing top {min(limit, len(citing_ids))} citing papers:\n")
        for i, citing_id in enumerate(citing_ids[:limit], 1):
            metadata = index.get_paper_metadata(citing_id)
            if metadata:
                title = (metadata.get("title") or "")[:70]
                year = metadata.get("year", "")
                venue = (metadata.get("venue") or "")[:20]
                click.echo(f"{i:3}. [{year}] {title}")
                click.echo(f"     Venue: {venue}  ID: {citing_id[:30]}...")
            else:
                click.echo(f"{i:3}. {citing_id}")

    @cli.command("export-graph-subgraph")
    @click.argument("paper_id")
    @click.option("--output", "-o", type=click.Path(), required=True, help="Output file path")
    @click.option("--hops", type=int, default=2, help="Number of hops from center (default: 2)")
    @click.option("--direction", type=click.Choice(["both", "citing", "cited"]),
                  default="both", help="Edge direction to follow")
    @click.option("--format", "-f", type=click.Choice(["json", "csv", "graphml", "gexf"]),
                  default="json", help="Export format")
    def export_graph_subgraph(
        paper_id: str,
        output: str,
        hops: int,
        direction: str,
        format: str,
    ) -> None:
        """Export the citation subgraph around a specific paper.

        Creates a neighborhood graph by traversing citations from the center paper.

        PAPER_ID is the Qdrant point ID of the center paper.

        Examples:

          # Export 2-hop neighborhood
          python -m src.cli.core_collect export-graph-subgraph abc123 -o subgraph.json

          # Export only papers citing this paper (1 hop)
          python -m src.cli.core_collect export-graph-subgraph abc123 -o citing.json --hops 1 --direction citing

          # Export for Gephi
          python -m src.cli.core_collect export-graph-subgraph abc123 -o subgraph.graphml --format graphml
        """
        from src.core.citation_graph import CitationGraphBuilder, GraphExporter

        storage = QdrantStorage()

        # Get the paper info
        paper = storage.get_paper_by_id(paper_id)
        if paper is None:
            click.echo(f"Paper not found: {paper_id}")
            sys.exit(1)

        click.echo(f"\nCenter paper: {paper.get('title', 'Unknown')[:80]}")
        click.echo(f"Year:         {paper.get('year', 'Unknown')}")

        # Build subgraph
        builder = CitationGraphBuilder(storage=storage)

        click.echo(f"\nBuilding {hops}-hop subgraph ({direction} direction)...")
        subgraph = builder.build_subgraph(
            center_paper_id=paper_id,
            hops=hops,
            direction=direction,
            include_metadata=True,
        )

        click.echo(f"Subgraph: {subgraph.number_of_nodes()} nodes, {subgraph.number_of_edges()} edges")

        # Export
        exporter = GraphExporter(subgraph)
        exporter.export(output, format=format)
        click.echo(f"\nExported to: {output}")
