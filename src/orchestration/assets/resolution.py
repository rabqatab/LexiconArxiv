import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import resolve_refs_stage, enrich_stubs_stage


@asset(deps=["enrich_refs_crossref"])
def resolve_refs(context: AssetExecutionContext) -> MaterializeResult:
    """Normalize/resolve references and create stubs.

    Depends on enrich_refs_crossref (state via Qdrant).
    """
    counts = asyncio.run(resolve_refs_stage())
    context.log.info(f"Reference resolution: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )


@asset(deps=["resolve_refs"])
def enrich_stubs(context: AssetExecutionContext) -> MaterializeResult:
    """Enrich most-cited stub papers with metadata. Depends on resolve_refs (state via Qdrant)."""
    counts = asyncio.run(enrich_stubs_stage())
    context.log.info(f"Stub enrichment: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
