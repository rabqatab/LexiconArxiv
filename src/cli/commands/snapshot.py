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
    @click.option("--min-cites-per-year", type=float, default=0.0, show_default=True,
                  help="Age-normalized quality gate: drop promotion to ENRICH_KEEP_STUB "
                       "if cited_by_count / max(1, now_year - publication_year) < N. "
                       "Default 0 = no filter. Self-normalizes recent vs old papers "
                       "(a 2026 paper with 5 cites and a 2010 paper with 80 cites both "
                       "pass at 5.0). Suggested: 1.0 = trim long-tail, 5.0 = strict.")
    @click.option("--now-year", type=int, default=None,
                  help="Reference year for the age calculation (default: current UTC year). "
                       "Pass explicitly for reproducible dry-runs.")
    def resolve_stubs_from_snapshot(snapshot_dir, batch_size, dry_run, resume,
                                     limit_files, allow_promotion, allow_merge,
                                     min_cites_per_year, now_year):
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
            min_cites_per_year=min_cites_per_year,
            now_year=now_year,
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

    @cli.command("retrofit-tier-from-source-id")
    @click.option("--limit", type=int, default=None, help="Cap points scanned (for testing)")
    @click.option("--batch-size", type=int, default=500)
    @click.option("--dry-run", is_flag=True, help="Count matches, do not write.")
    def retrofit_tier_from_source_id(limit, batch_size, dry_run):
        """Retroactively assign ``tier`` to P2/P3-injected papers by joining
        ``openalex_source_id`` against the venue tier config.

        Prerequisite: run ``enrich-corpus-fields`` (P1) FIRST so that the
        ``openalex_source_id`` payload field (added 2026-07-06) has been
        backfilled from the snapshot. This CLI is a cheap Python join —
        no OpenAlex API calls, no snapshot re-scan.

        Motivation: incremental crawlers set ``tier=venue.tier`` at write
        time because they query OpenAlex per venue source_id. P2/P3 scanned
        the snapshot without a per-venue query, so the tier field never
        got set — this is why ``label-abstracts --priority-tier N`` returns
        zero papers on the P2/P3 subset. Setting ``tier`` here fixes that.
        """
        from src.core.storage.base import QdrantStorage
        from src.core.config import VENUES
        from qdrant_client.http import models as qmodels

        source_id_to_tier: dict[str, int] = {}
        for venue in VENUES:
            for sid in venue.all_source_ids:
                source_id_to_tier[sid] = venue.tier
        click.echo(f"tier map: {len(source_id_to_tier)} source ids (Tier 0/1/2)")

        s = QdrantStorage()
        # Scroll all papers that have openalex_source_id set but no tier yet
        scroll_filter = qmodels.Filter(
            must=[qmodels.IsEmptyCondition(is_empty=qmodels.PayloadField(key="tier"))],
            must_not=[qmodels.IsEmptyCondition(is_empty=qmodels.PayloadField(key="openalex_source_id"))],
        )
        offset = None
        scanned = 0
        matched = 0
        by_tier = {0: 0, 1: 0, 2: 0}
        updates: list[tuple[str, int]] = []
        while True:
            records, next_offset = s.client.scroll(
                collection_name=s.collection_name,
                scroll_filter=scroll_filter,
                limit=batch_size,
                offset=offset,
                with_payload=["openalex_source_id"],
                with_vectors=False,
            )
            if not records:
                break
            for r in records:
                sid = (r.payload or {}).get("openalex_source_id")
                if sid and sid in source_id_to_tier:
                    tier = source_id_to_tier[sid]
                    matched += 1
                    by_tier[tier] = by_tier.get(tier, 0) + 1
                    updates.append((str(r.id), tier))
                scanned += 1
                if limit and scanned >= limit:
                    break
            if not dry_run and updates:
                # Batch-write ``tier`` per matched point. Uses batch_update_points
                # so 500 writes = 1 HTTP call — same pattern as batch_update_
                # abstract_structure. wait=False keeps latency down; papers
                # only need the field for label-abstracts priority filter,
                # which tolerates a 5-second flush lag.
                ops = [
                    qmodels.SetPayloadOperation(
                        set_payload=qmodels.SetPayload(
                            payload={"tier": tier}, points=[pid],
                        ),
                    ) for pid, tier in updates
                ]
                s.client.batch_update_points(
                    collection_name=s.collection_name,
                    update_operations=ops,
                    wait=False,
                )
                updates = []
            offset = next_offset
            if offset is None or (limit and scanned >= limit):
                break

        click.echo(f"scanned:   {scanned:,}")
        click.echo(f"matched:   {matched:,} ({100*matched/max(1,scanned):.1f}%)")
        click.echo(f"  by tier: {by_tier}")
        if dry_run:
            click.echo("(dry-run — no writes performed)")


    @cli.command("snapshot-status")
    def snapshot_status():
        """Print checkpoint progress + embedding queue depth for all 4 phases."""
        from src.core.snapshot import checkpoint as cp
        from src.core.snapshot import embedding_queue
        import json
        for phase in ("p1", "p2", "p3", "p4"):
            done = cp.load(phase)
            click.echo(f"{phase}: {len(done)} files done")
            # Surface last_summary.json if it exists
            from pathlib import Path
            import os
            root = Path(os.environ.get("DAGSTER_HOME", str(Path.home()/"dagster_home"))) \
                   / "snapshot_checkpoints" / phase
            ls = root / "last_summary.json"
            if ls.exists():
                click.echo(f"  last: {ls.read_text().strip()}")
            q = root / "quarantine.jsonl"
            if q.exists():
                click.echo(f"  quarantine: {sum(1 for _ in q.open())} entries")
        click.echo(f"embedding_queue depth: {embedding_queue.depth()}")


    @cli.command("snapshot-reset")
    @click.option("--phase", type=click.Choice(["p1","p2","p3","p4"]), required=True)
    @click.option("--confirm", is_flag=True, help="Required to actually delete.")
    def snapshot_reset(phase, confirm):
        """Delete the per-phase checkpoint directory. Data is not touched (phases are idempotent)."""
        if not confirm:
            click.echo("Add --confirm to actually delete.", err=True)
            raise click.exceptions.Exit(1)
        from src.core.snapshot import checkpoint as cp
        cp.reset(phase)
        click.echo(f"reset {phase}")


    @cli.command("snapshot-replay-failed")
    @click.option("--phase", type=click.Choice(["p1","p2","p3","p4"]), required=True)
    @click.option("--quarantine", is_flag=True, help="Also replay quarantine.jsonl items.")
    def snapshot_replay_failed(phase, quarantine):
        """Re-attempt the failed_batches (and optionally quarantine) of a phase."""
        import json
        from pathlib import Path
        import os
        root = Path(os.environ.get("DAGSTER_HOME", str(Path.home()/"dagster_home"))) \
               / "snapshot_checkpoints" / phase
        d = root / "failed_batches"
        n = 0
        if d.exists():
            for f in sorted(d.glob("*.jsonl")):
                lines = f.read_text().splitlines()
                # We do not auto-reapply here — surface the items and let the operator
                # decide. (Auto-replay is too risky without root-cause analysis.)
                click.echo(f"{f.name}: {len(lines)} items")
                n += len(lines)
        if quarantine:
            qf = root / "quarantine.jsonl"
            if qf.exists():
                n_q = sum(1 for _ in qf.open())
                click.echo(f"quarantine.jsonl: {n_q} items")
                n += n_q
        click.echo(f"total items needing operator review: {n}")

    @cli.command("snapshot-live-delta")
    @click.option("--days-back", type=int, default=1,
                  help="Fetch updates from N days ago (default 1 = yesterday).")
    @click.option("--since", type=str, default=None,
                  help="Explicit ISO date (YYYY-MM-DD); overrides --days-back.")
    @click.option("--dry-run", is_flag=True,
                  help="Run the full chain but do not write to storage.")
    @click.option("--max-injections", type=int, default=None,
                  help="Stop P3 after this many injections (safety cap).")
    @click.option("--anchor-min-citers", type=int, default=2)
    @click.option("--concept-min-recent", type=int, default=50)
    @click.option("--concept-min-old", type=int, default=200)
    @click.option("--concept-min-year", type=int, default=2018)
    @click.option("--max-citers-per-paper", type=int, default=300)
    def snapshot_live_delta(days_back, since, dry_run, max_injections,
                             anchor_min_citers, concept_min_recent,
                             concept_min_old, concept_min_year,
                             max_citers_per_paper):
        """Run one live-mode pass: fetch yesterday's OpenAlex API delta and
        chain P1→P2→P3→P4 per work (same phase logic as the snapshot bootstrap)."""
        from datetime import date as _date
        from src.core.snapshot import live_worker
        from src.core.snapshot.gap_filter import Thresholds
        from src.core.storage import QdrantStorage
        storage = QdrantStorage()
        since_date = _date.fromisoformat(since) if since else None
        thresholds = Thresholds(
            anchor_min_citers=anchor_min_citers,
            concept_min_recent=concept_min_recent,
            concept_min_old=concept_min_old,
            concept_min_year=concept_min_year,
        )
        out = live_worker.run_live_delta(
            storage,
            since=since_date,
            days_back=days_back,
            dry_run=dry_run,
            thresholds=thresholds,
            max_injections=max_injections,
            cap_per_paper=max_citers_per_paper,
        )
        click.echo(
            f"live-delta since={out['since']} fetched={out['fetched']} "
            f"p1={out['per_phase']['p1']} p2={out['per_phase']['p2']} "
            f"p3={out['per_phase']['p3']} p4={out['per_phase']['p4']} "
            f"queue_depth_after={out['queue_depth_after']} "
            f"hwm_updated={out['hwm_updated']} duration_s={out['duration_s']}"
        )
