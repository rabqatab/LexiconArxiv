import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import enrich_refs_s2_stage, enrich_refs_crossref_stage


@asset(deps=["collect_papers"])
def enrich_refs_s2(context: AssetExecutionContext) -> MaterializeResult:
    """Fill references via Semantic Scholar. Depends on collect_papers (state via Qdrant)."""
    counts = asyncio.run(enrich_refs_s2_stage())
    context.log.info(f"S2 refs: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )


@asset(deps=["enrich_refs_s2"])
def enrich_refs_crossref(context: AssetExecutionContext) -> MaterializeResult:
    """Fill remaining references via CrossRef. Depends on enrich_refs_s2 (state via Qdrant)."""
    counts = asyncio.run(enrich_refs_crossref_stage())
    context.log.info(f"CrossRef refs: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
