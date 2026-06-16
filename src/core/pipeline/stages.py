"""Importable pipeline stage functions shared by the CLI and the Dagster assets.

Each stage is a thin, side-effecting orchestration over src.core.* that returns
a small structured result (counts), not paper data. Paper data lives in Qdrant.
"""

import datetime

from src.core.storage import QdrantStorage
from src.core.enrichment.openalex import PaperEnricher
from src.core.enrichment.semantic_scholar import SemanticScholarEnricher
from src.core.enrichment.crossref import CrossRefEnricher
from src.core.embedding.embedder import PaperEmbedder
from src.core.constants import ALL_DENSE_VECTORS
from src.core.crawler import (
    CoreCorpusCollector,
    ACLAnthologyCollector,
    get_acl_venues,
    DBLPCollector,
    get_dblp_venues,
    OpenReviewCollector,
    get_openreview_venues,
    AAOJSCollector,
    get_aaai_venues,
)


async def collect_incremental_stage(days: int = 3, source: str = "all") -> dict[str, int]:
    """Collect new papers from the last `days` days across sources.

    Returns a dict of per-source counts plus a "total" key. Mirrors the logic in
    the collect-incremental CLI command. The collector dedups against existing
    DOIs/IDs, so overlapping daily windows are harmless.
    """
    since_year = (datetime.datetime.now() - datetime.timedelta(days=days)).year
    current_year = datetime.datetime.now().year

    storage = QdrantStorage()
    storage.ensure_collection()
    results: dict[str, int] = {}

    if source in ("all", "openalex"):
        async with CoreCorpusCollector(storage=storage) as collector:
            results["openalex"] = await collector.collect_incremental(days_back=days)

    if source in ("all", "acl"):
        async with ACLAnthologyCollector(storage=storage) as collector:
            count = 0
            for venue in get_acl_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["acl"] = count

    if source in ("all", "dblp"):
        async with DBLPCollector(storage=storage) as collector:
            count = 0
            for venue in get_dblp_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["dblp"] = count

    if source in ("all", "openreview"):
        async with OpenReviewCollector(storage=storage) as collector:
            count = 0
            for venue in get_openreview_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["openreview"] = count

    if source in ("all", "aaai"):
        async with AAOJSCollector(storage=storage) as collector:
            count = 0
            for venue in get_aaai_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["aaai"] = count

    results["total"] = sum(v for k, v in results.items() if k != "total")
    return results


async def enrich_abstracts_stage(
    limit: int | None = None, batch_size: int = 100, delay: float = 0.1, parallel: int = 10
) -> dict[str, int]:
    """Fill missing abstracts via OpenAlex for papers that have a DOI.

    Returns processed/enriched/not_found/errors counts.

    Note: `parallel` defaults to 10 here (vs. 1 in the CLI) intentionally —
    Dagster batch runs benefit from higher concurrency than an interactive CLI default.
    """
    storage = QdrantStorage()
    async with PaperEnricher(
        storage=storage, batch_size=batch_size, delay=delay, max_concurrent=parallel
    ) as enricher:
        progress = await enricher.enrich_abstracts(dry_run=False, limit=limit)
    return {
        "processed": progress.processed,
        "enriched": progress.enriched,
        "not_found": progress.not_found,
        "errors": progress.errors,
    }


async def embed_papers_stage(
    batch_size: int = 8,
    embed_batch_size: int = 64,
    concurrency: int = 4,
    limit: int | None = None,
    resume: bool = True,
) -> dict[str, int]:
    """Embed new papers (section + structured-abstract + BM25 vectors) via Ollama.

    The GPU work is delegated to the local Ollama service (qwen3-embedding:8b);
    this function only makes HTTP calls, so it runs in-process. `resume=True`
    skips papers that already have dense vectors. Returns {"embedded": N}.
    """
    storage = QdrantStorage()

    # Pre-flight: verify the collection has the required dense vector configs.
    info = storage.client.get_collection(storage.collection_name)
    vectors = info.config.params.vectors or {}
    missing = [v for v in ALL_DENSE_VECTORS if v not in vectors]
    if missing:
        raise RuntimeError(
            f"Collection missing vector configs: {missing}. "
            "Run: uv run python -m src.cli.core_collect migrate-collection"
        )

    embedder = PaperEmbedder(max_concurrent=concurrency)
    total_embedded = 0
    async with embedder:
        if not await embedder.check_model_available():
            raise RuntimeError(
                "Embedding model not available in Ollama "
                "(run: ollama pull qwen3-embedding:8b)"
            )
        offset = None
        while True:
            papers, next_offset = storage.get_papers_for_embedding(
                limit=batch_size, offset=offset, skip_embedded=resume
            )
            if not papers:
                break
            total_embedded += await embedder.embed_and_upsert_batch(
                papers=papers, storage=storage, embed_batch_size=embed_batch_size
            )
            if limit and total_embedded >= limit:
                break
            if next_offset is None:
                break
            offset = next_offset
    return {"embedded": total_embedded}


async def enrich_refs_s2_stage(
    limit: int | None = None, batch_size: int = 100, delay: float = 0.1,
    parallel: int = 10, recent_days: int | None = None,
) -> dict[str, int]:
    """Fill referenced_works via Semantic Scholar for DOI papers missing refs."""
    fetched_since = None
    if recent_days is not None:
        fetched_since = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=recent_days)
        ).isoformat()
    storage = QdrantStorage()
    async with SemanticScholarEnricher(
        storage=storage, batch_size=batch_size, delay=delay, max_concurrent=parallel
    ) as enricher:
        p = await enricher.enrich_by_doi(dry_run=False, limit=limit, fetched_since=fetched_since)
    return {"processed": p.processed, "enriched": p.enriched,
            "not_found": p.not_found, "no_refs": p.no_refs, "errors": p.errors}


async def enrich_refs_crossref_stage(
    limit: int | None = None, batch_size: int = 100, delay: float = 0.1, parallel: int = 10,
) -> dict[str, int]:
    """Fill referenced_works via CrossRef for DOI papers missing refs."""
    async with CrossRefEnricher(
        batch_size=batch_size, delay=delay, max_concurrent=parallel
    ) as enricher:
        p = await enricher.enrich_by_doi(dry_run=False, limit=limit)
    return {"processed": p.processed, "enriched": p.enriched,
            "not_found": p.not_found, "no_refs": p.no_refs, "errors": p.errors}
