"""CLI command for computing semantic similarity graph."""

import sys

import click

from src.cli._logging import logger


def register_commands(cli: click.Group):
    @cli.command()
    @click.option("--k", type=int, default=10, help="Neighbors per edge type")
    @click.option("--batch-size", type=int, default=50, help="Papers per scroll batch")
    @click.option("--limit", "-n", type=int, default=None, help="Max papers to process")
    @click.option("--only-missing", is_flag=True,
                  help="Skip papers that already have similar_papers (incremental re-run)")
    @click.option("--dry-run", is_flag=True, help="Count eligible papers without computing")
    def compute_similarity(k, batch_size, limit, only_missing, dry_run):
        """Precompute semantic similarity edges between papers.

        For each paper, finds top-K similar papers per section vector,
        creating typed edges: same_method, same_task, same_result,
        method_transfer, overall.

        Examples:

          uv run python -m src.cli.core_collect compute-similarity

          uv run python -m src.cli.core_collect compute-similarity --k 20

          uv run python -m src.cli.core_collect compute-similarity -n 100
        """
        from qdrant_client import models

        from src.core.constants import STRUCTURED_VECTOR_NAME
        from src.core.storage.base import QdrantStorage

        storage = QdrantStorage()

        if dry_run:
            must_not = [models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))]
            if only_missing:
                must_not.append(models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="similar_papers")))
            count = storage.client.count(
                storage.collection_name,
                count_filter=models.Filter(
                    must=[models.HasVectorCondition(has_vector=STRUCTURED_VECTOR_NAME)],
                    must_not=must_not,
                ),
            ).count
            click.echo(f"Papers eligible for similarity computation: {count:,}")
            return

        from src.core.analytics.similarity import compute_similarity_batch

        click.echo(f"Computing similarity graph (k={k})...")
        stats = compute_similarity_batch(
            storage=storage,
            k=k,
            batch_size=batch_size,
            limit=limit,
            only_missing=only_missing,
        )

        click.echo(f"\nSimilarity computation complete:")
        click.echo(f"  Papers processed: {stats['processed']:,}")
        click.echo(f"  Papers updated:   {stats['updated']:,}")
        click.echo(f"  Edge types:       {', '.join(stats['edge_types'])}")
        click.echo(f"  K per type:       {stats['k']}")
        click.echo(f"  Time:             {stats['elapsed_seconds']}s")
