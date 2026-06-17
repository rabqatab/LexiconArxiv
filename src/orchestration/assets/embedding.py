import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import embed_papers_stage


@asset(deps=["label_abstracts"])
def embed_papers(context: AssetExecutionContext) -> MaterializeResult:
    """Embed new papers via the local Ollama service (GPU: qwen3-embedding:8b).

    Service-delegated GPU work: the asset only issues HTTP calls to Ollama, so it
    runs in-process. Depends on label_abstracts (state via Qdrant).
    """
    counts = asyncio.run(embed_papers_stage())
    context.log.info(f"Embedding: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
