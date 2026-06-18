"""CLI: enrich corpus from a local OpenAlex works snapshot."""

import click

from src.core.storage import QdrantStorage
from src.core.snapshot.runner import run_snapshot_enrichment

DEFAULT_SNAPSHOT_DIR = "/mnt/nfs/ssd2/openalex_snapshot/data/works"


def register_commands(cli: click.Group):
    @cli.command("enrich-from-openalex-snapshot")
    @click.option("--snapshot-dir", default=DEFAULT_SNAPSHOT_DIR, show_default=True,
                  help="Path to the OpenAlex works snapshot (updated_date=*/*.gz)")
    @click.option("--batch-size", type=int, default=500)
    @click.option("--dry-run", is_flag=True, help="Count matches without writing")
    def enrich_from_openalex_snapshot(snapshot_dir, batch_size, dry_run):
        """Stream the OpenAlex works snapshot and fill-only-missing enrich the corpus."""
        storage = QdrantStorage()
        result = run_snapshot_enrichment(
            storage=storage, snapshot_dir=snapshot_dir,
            dry_run=dry_run, batch_size=batch_size,
        )
        click.echo(f"Snapshot enrichment: {result}")
