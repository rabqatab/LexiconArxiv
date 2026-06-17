import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import label_abstracts_stage


@asset(deps=["enrich_abstracts"])
def label_abstracts(context: AssetExecutionContext) -> MaterializeResult:
    """Label abstract sentences with rhetorical roles. Depends on enrich_abstracts (state via Qdrant)."""
    counts = asyncio.run(label_abstracts_stage())
    context.log.info(f"Abstract labeling: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
