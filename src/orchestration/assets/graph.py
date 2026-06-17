import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import build_cited_by_stage, analyze_graph_stage


@asset(deps=["resolve_refs"])
def build_cited_by(context: AssetExecutionContext) -> MaterializeResult:
    """Incrementally build reverse-citation edges. Depends on resolve_refs (state via Qdrant)."""
    counts = asyncio.run(build_cited_by_stage())
    context.log.info(f"Cited-by build: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )


@asset(deps=["build_cited_by"])
def analyze_graph(context: AssetExecutionContext) -> MaterializeResult:
    """Compute and store citation graph metrics (PageRank/HITS/communities).

    Depends on build_cited_by (state via Qdrant).
    """
    counts = asyncio.run(analyze_graph_stage())
    context.log.info(f"Graph analysis: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
