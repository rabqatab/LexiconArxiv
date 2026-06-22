"""Dagster assets for the snapshot utilization passes (manual-trigger only)."""
from dagster import AssetExecutionContext, MaterializeResult, asset

from src.core.snapshot import phase1_corpus_fields, phase4_cited_by
from src.core.storage import QdrantStorage


@asset(deps=[], group_name="snapshot")
def snapshot_enrich_corpus_fields(context: AssetExecutionContext) -> MaterializeResult:
    """P1: fill missing metadata fields on every matched corpus paper."""
    summary = phase1_corpus_fields.run(QdrantStorage(), snapshot_dir="/mnt/nfs/ssd2/openalex_snapshot/data/works")
    context.log.info(summary.to_log_line())
    return MaterializeResult(metadata=summary.to_dagster_metadata())


@asset(deps=[snapshot_enrich_corpus_fields], group_name="snapshot")
def snapshot_extend_cited_by(context: AssetExecutionContext) -> MaterializeResult:
    """P4: attach external citers (corpus-internal) to external_cited_by."""
    summary = phase4_cited_by.run(QdrantStorage(), snapshot_dir="/mnt/nfs/ssd2/openalex_snapshot/data/works")
    context.log.info(summary.to_log_line())
    return MaterializeResult(metadata=summary.to_dagster_metadata())
