import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import compute_similarity_stage, compute_topics_stage


@asset(deps=["embed_papers"])
def compute_similarity(context: AssetExecutionContext) -> MaterializeResult:
    """Compute semantic similarity graph via Qdrant ANN.

    Depends on embed_papers (state via Qdrant).
    """
    counts = asyncio.run(compute_similarity_stage())
    context.log.info(f"Similarity: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )


@asset(deps=["embed_papers"])
def compute_topics(context: AssetExecutionContext) -> MaterializeResult:
    """Cluster papers into topics via UMAP+HDBSCAN. Depends on embed_papers (state via Qdrant)."""
    counts = asyncio.run(compute_topics_stage())
    context.log.info(f"Topics: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
