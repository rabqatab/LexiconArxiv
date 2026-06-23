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

    @cli.command("resolve-stubs-from-snapshot")
    @click.option("--snapshot-dir",
                  default="/mnt/nfs/ssd2/openalex_snapshot/data/works")
    @click.option("--batch-size", type=int, default=500)
    @click.option("--dry-run", is_flag=True,
                  help="Report would-be promotions/enrichments without writing.")
    @click.option("--resume/--no-resume", default=True)
    @click.option("--limit-files", type=int, default=None)
    @click.option("--allow-promotion/--no-allow-promotion", default=True,
                  help="If False, only enrich-in-place; never flip is_stub.")
    @click.option("--allow-merge/--no-allow-merge", default=True,
                  help="If False, refuse to merge a stub into an existing real paper.")
    def resolve_stubs_from_snapshot(snapshot_dir, batch_size, dry_run, resume,
                                     limit_files, allow_promotion, allow_merge):
        """Match every stub against the OpenAlex snapshot, then promote (preserve
        cited_by), enrich-in-place, or merge into an existing real paper."""
        from src.core.snapshot import phase2_stub_resolution
        from src.core.snapshot import checkpoint as cp
        from src.core.storage import QdrantStorage
        storage = QdrantStorage()
        if not resume:
            cp.reset("p2")
        summary = phase2_stub_resolution.run(
            storage, snapshot_dir=snapshot_dir, batch_size=batch_size,
            dry_run=dry_run, limit_files=limit_files,
            allow_promotion=allow_promotion, allow_merge=allow_merge,
        )
        click.echo(summary.to_log_line())

    @cli.command("discover-corpus-gaps")
    @click.option("--snapshot-dir",
                  default="/mnt/nfs/ssd2/openalex_snapshot/data/works")
    @click.option("--batch-size", type=int, default=500)
    @click.option("--dry-run", is_flag=True)
    @click.option("--resume/--no-resume", default=True)
    @click.option("--limit-files", type=int, default=None)
    @click.option("--anchor-min-citers", type=int, default=2)
    @click.option("--concept-min-recent", type=int, default=50)
    @click.option("--concept-min-old", type=int, default=200)
    @click.option("--concept-min-year", type=int, default=2018)
    @click.option("--max-injections", type=int, default=None,
                  help="Stop after this many injections (safety cap).")
    def discover_corpus_gaps(snapshot_dir, batch_size, dry_run, resume, limit_files,
                              anchor_min_citers, concept_min_recent, concept_min_old,
                              concept_min_year, max_injections):
        """Discover snapshot works missing from the corpus, classify as
        anchor-citation or AI-concept-high-impact, inject as new real papers."""
        from src.core.snapshot import phase3_gap_discovery
        from src.core.snapshot import checkpoint as cp
        from src.core.snapshot.gap_filter import Thresholds
        from src.core.storage import QdrantStorage
        storage = QdrantStorage()
        if not resume:
            cp.reset("p3")
        thresholds = Thresholds(
            anchor_min_citers=anchor_min_citers,
            concept_min_recent=concept_min_recent,
            concept_min_old=concept_min_old,
            concept_min_year=concept_min_year,
        )
        summary = phase3_gap_discovery.run(
            storage, snapshot_dir=snapshot_dir, batch_size=batch_size,
            dry_run=dry_run, limit_files=limit_files,
            max_injections=max_injections, thresholds=thresholds,
        )
        click.echo(summary.to_log_line())
