import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import extract_keywords_stage


@asset(deps=["enrich_abstracts"])
def extract_keywords(context: AssetExecutionContext) -> MaterializeResult:
    """Extract BM25/display keywords for papers missing them. Depends on enrich_abstracts (state via Qdrant)."""
    counts = asyncio.run(extract_keywords_stage())
    context.log.info(f"Keywords: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
