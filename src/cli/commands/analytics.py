"""CLI commands for analytics pipeline."""

import json
import sys

import click

from src.cli._logging import logger


def register_commands(cli: click.Group):
    @cli.command()
    @click.option("--min-cluster-size", type=int, default=50, help="HDBSCAN min cluster size")
    @click.option("--min-samples", type=int, default=10, help="HDBSCAN min samples")
    @click.option("--umap-components", type=int, default=50, help="UMAP intermediate dimensions")
    @click.option("--umap-neighbors", type=int, default=15, help="UMAP n_neighbors")
    @click.option("--dry-run", is_flag=True, help="Run clustering but don't store results")
    def compute_topics(min_cluster_size, min_samples, umap_components, umap_neighbors, dry_run):
        """Compute topic clusters using UMAP + HDBSCAN on paper embeddings.

        Loads all paper vectors from Qdrant, reduces dimensionality with UMAP,
        clusters with HDBSCAN, and stores cluster_id + 2D coordinates back.

        Examples:

          uv run python -m src.cli.core_collect compute-topics

          uv run python -m src.cli.core_collect compute-topics --dry-run

          uv run python -m src.cli.core_collect compute-topics --min-cluster-size 100
        """
        from src.core.analytics.clustering import compute_clusters, store_cluster_results
        from src.core.storage.base import QdrantStorage

        storage = QdrantStorage()

        # Pre-flight: verify collection exists
        try:
            storage.client.get_collection(storage.collection_name)
        except Exception as e:
            click.echo(f"Error: Cannot connect to Qdrant: {e}", err=True)
            sys.exit(1)

        click.echo(f"Computing topic clusters (min_cluster_size={min_cluster_size}, "
                    f"min_samples={min_samples}, umap_components={umap_components})...")

        results = compute_clusters(
            storage=storage,
            umap_n_components=umap_components,
            umap_n_neighbors=umap_neighbors,
            hdbscan_min_cluster_size=min_cluster_size,
            hdbscan_min_samples=min_samples,
        )

        if "error" in results:
            click.echo(f"Error: {results['error']} (count={results.get('count', 0)})", err=True)
            sys.exit(1)

        click.echo(f"\nClustering results:")
        click.echo(f"  Papers:    {results['num_papers']:,}")
        click.echo(f"  Clusters:  {results['num_clusters']}")
        click.echo(f"  Noise:     {results['noise_count']:,}")
        click.echo(f"  Time:      {results['elapsed_seconds']}s")

        click.echo(f"\nTop clusters:")
        for c in sorted(results["clusters"], key=lambda x: x["size"], reverse=True)[:10]:
            click.echo(f"  [{c['cluster_id']:3d}] {c['size']:>6,} papers  |  {c['label']}")

        if dry_run:
            click.echo("\n[DRY RUN] Skipping Qdrant storage.")
            return

        click.echo(f"\nStoring cluster assignments to Qdrant...")
        updated = store_cluster_results(storage, results)
        click.echo(f"Stored {updated:,} cluster assignments.")
