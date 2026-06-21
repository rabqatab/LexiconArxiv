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

    @cli.command("enrich-corpus-fields")
    @click.option("--snapshot-dir",
                  default="/mnt/nfs/ssd2/openalex_snapshot/data/works",
                  help="Path to OpenAlex works snapshot (updated_date=*/*.gz)")
    @click.option("--batch-size", type=int, default=500)
    @click.option("--dry-run", is_flag=True,
                  help="Count matches without writing.")
    @click.option("--resume/--no-resume", default=True,
                  help="Skip .gz files already marked done in the checkpoint.")
    @click.option("--limit-files", type=int, default=None,
                  help="Process at most N .gz files (debug).")
    def enrich_corpus_fields(snapshot_dir, batch_size, dry_run, resume, limit_files):
        """Stream the OpenAlex snapshot and fill missing metadata fields on
        every matched real paper (cited_by_count, fwci, concepts, topics,
        best_oa_pdf_url, orcid_map, ...). Fill-only-missing; idempotent."""
        from src.core.snapshot import phase1_corpus_fields
        from src.core.snapshot import checkpoint as cp
        storage = QdrantStorage()
        if not resume:
            cp.reset("p1")
        summary = phase1_corpus_fields.run(
            storage, snapshot_dir=snapshot_dir, batch_size=batch_size,
            dry_run=dry_run, limit_files=limit_files,
        )
        click.echo(summary.to_log_line())

    @cli.command("extend-cited-by-from-snapshot")
    @click.option("--snapshot-dir",
                  default="/mnt/nfs/ssd2/openalex_snapshot/data/works")
    @click.option("--batch-size", type=int, default=500)
    @click.option("--dry-run", is_flag=True)
    @click.option("--resume/--no-resume", default=True)
    @click.option("--limit-files", type=int, default=None)
    @click.option("--max-citers-per-paper", type=int, default=300,
                  help="Truncate external_cited_by to this many entries (year DESC, cited_by_count DESC).")
    def extend_cited_by_from_snapshot(snapshot_dir, batch_size, dry_run, resume,
                                       limit_files, max_citers_per_paper):
        """Attach external citers (OpenAlex works that cite a corpus paper) to
        the new external_cited_by payload field. Does NOT touch the existing
        cited_by field."""
        from src.core.snapshot import phase4_cited_by
        from src.core.snapshot import checkpoint as cp
        storage = QdrantStorage()
        if not resume:
            cp.reset("p4")
        summary = phase4_cited_by.run(
            storage, snapshot_dir=snapshot_dir, batch_size=batch_size,
            dry_run=dry_run, limit_files=limit_files, cap_per_paper=max_citers_per_paper,
        )
        click.echo(summary.to_log_line())
