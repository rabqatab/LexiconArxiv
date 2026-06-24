"""Dagster assets for the snapshot utilization passes (manual-trigger only)."""
from dagster import AssetExecutionContext, MaterializeResult, asset

from src.core.snapshot import phase1_corpus_fields, phase2_stub_resolution, phase3_gap_discovery, phase4_cited_by, live_worker
from src.core.storage import QdrantStorage


@asset(deps=[], group_name="snapshot")
def snapshot_enrich_corpus_fields(context: AssetExecutionContext) -> MaterializeResult:
    """P1: fill missing metadata fields on every matched corpus paper."""
    summary = phase1_corpus_fields.run(QdrantStorage(), snapshot_dir="/mnt/nfs/ssd2/openalex_snapshot/data/works")
    context.log.info(summary.to_log_line())
    return MaterializeResult(metadata=summary.to_dagster_metadata())


@asset(deps=[snapshot_enrich_corpus_fields], group_name="snapshot")
def snapshot_resolve_stubs(context: AssetExecutionContext) -> MaterializeResult:
    """P2: match stubs against the snapshot; promote or enrich."""
    summary = phase2_stub_resolution.run(
        QdrantStorage(),
        snapshot_dir="/mnt/nfs/ssd2/openalex_snapshot/data/works",
    )
    context.log.info(summary.to_log_line())
    return MaterializeResult(metadata=summary.to_dagster_metadata())


@asset(deps=[snapshot_resolve_stubs], group_name="snapshot")
def snapshot_discover_gaps(context: AssetExecutionContext) -> MaterializeResult:
    """P3: discover and inject hybrid-classified gap papers."""
    summary = phase3_gap_discovery.run(
        QdrantStorage(),
        snapshot_dir="/mnt/nfs/ssd2/openalex_snapshot/data/works",
    )
    context.log.info(summary.to_log_line())
    return MaterializeResult(metadata=summary.to_dagster_metadata())


@asset(deps=[snapshot_discover_gaps], group_name="snapshot")
def snapshot_extend_cited_by(context: AssetExecutionContext) -> MaterializeResult:
    """P4: attach external citers (corpus-internal) to external_cited_by."""
    summary = phase4_cited_by.run(QdrantStorage(), snapshot_dir="/mnt/nfs/ssd2/openalex_snapshot/data/works")
    context.log.info(summary.to_log_line())
    return MaterializeResult(metadata=summary.to_dagster_metadata())


@asset(deps=[], group_name="snapshot")
def snapshot_live_delta(context: AssetExecutionContext) -> MaterializeResult:
    """Daily live-mode pass: chain P1→P2→P3→P4 over yesterday's OpenAlex delta.

    Independent of the bootstrap DAG. Defaults to STOPPED at the schedule
    level; operator enables after bootstrap is stable.
    """
    out = live_worker.run_live_delta(QdrantStorage())
    context.log.info("live-delta: %s", out)
    # Flatten nested dict into Dagster metadata (top-level keys must be flat)
    md = {
        "since": out["since"],
        "fetched": out["fetched"],
        "queue_depth_after": out["queue_depth_after"],
        "duration_s": out["duration_s"],
        **{f"p1.{k}": v for k, v in out["per_phase"]["p1"].items()},
        **{f"p2.{k}": v for k, v in out["per_phase"]["p2"].items()},
        **{f"p3.{k}": v for k, v in out["per_phase"]["p3"].items()},
        **{f"p4.{k}": v for k, v in out["per_phase"]["p4"].items()},
    }
    return MaterializeResult(metadata=md)
