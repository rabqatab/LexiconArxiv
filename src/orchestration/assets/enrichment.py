import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import enrich_abstracts_stage


@asset(deps=["collect_papers"])
def enrich_abstracts(context: AssetExecutionContext) -> MaterializeResult:
    """Fill missing abstracts via OpenAlex. Depends on collect_papers (state via Qdrant)."""
    counts = asyncio.run(enrich_abstracts_stage())
    context.log.info(f"Abstract enrichment: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
