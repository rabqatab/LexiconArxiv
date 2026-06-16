import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import collect_incremental_stage

DAYS_LOOKBACK = 3  # daily runs use a 3-day rolling window (self-healing via dedup)


@asset
def collect_papers(context: AssetExecutionContext) -> MaterializeResult:
    """Collect new papers from all sources (3-day rolling window)."""
    counts = asyncio.run(collect_incremental_stage(days=DAYS_LOOKBACK, source="all"))
    context.log.info(f"Collected: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
