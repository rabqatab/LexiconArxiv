"""Importable pipeline stage functions shared by the CLI and the Dagster assets.

Each stage is a thin, side-effecting orchestration over src.core.* that returns
a small structured result (counts), not paper data. Paper data lives in Qdrant.
"""

import asyncio
import datetime
import logging

from src.core.storage import QdrantStorage
from src.core.enrichment.openalex import PaperEnricher
from src.core.enrichment.semantic_scholar import SemanticScholarEnricher
from src.core.enrichment.crossref import CrossRefEnricher
from src.core.keyword import KeywordExtractor
from src.core.labeling import AbstractLabeler
from src.core.embedding.embedder import PaperEmbedder
from src.core.constants import ALL_DENSE_VECTORS
from src.core.resolution.resolver import ReferenceResolver
from src.core.enrichment import StubEnricher
from src.core.citation_graph import CitationGraphBuilder, GraphAnalyzer
from src.core.analytics.similarity import compute_similarity_batch
from src.core.analytics.clustering import compute_clusters, store_cluster_results
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

logger = logging.getLogger(__name__)


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
    limit: int | None = None, batch_size: int = 100, delay: float = 0.1, parallel: int = 10,
    fetched_since: str | None = None,
) -> dict[str, int]:
    """Fill missing abstracts via OpenAlex for papers that have a DOI.

    Returns processed/enriched/not_found/errors counts.

    Note: `parallel` defaults to 10 here (vs. 1 in the CLI) intentionally —
    Dagster batch runs benefit from higher concurrency than an interactive CLI default.

    ``fetched_since`` (ISO date) narrows the scroll to recently-fetched
    papers via the indexed ``fetched_at`` field. Set for incremental
    cycles; leave unset for full-corpus reruns.
    """
    storage = QdrantStorage()
    async with PaperEnricher(
        storage=storage, batch_size=batch_size, delay=delay, max_concurrent=parallel
    ) as enricher:
        progress = await enricher.enrich_abstracts(
            dry_run=False, limit=limit, fetched_since=fetched_since,
        )
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
    fetched_since: str | None = None,
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
                limit=batch_size, offset=offset, skip_embedded=resume,
                fetched_since=fetched_since,
            )
            if not papers:
                break
            total_embedded += await embedder.embed_and_upsert_batch(
                papers=papers, storage=storage, embed_batch_size=embed_batch_size
            )
            if limit is not None and total_embedded >= limit:
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
    storage = QdrantStorage()
    async with CrossRefEnricher(
        storage=storage, batch_size=batch_size, delay=delay, max_concurrent=parallel
    ) as enricher:
        p = await enricher.enrich_by_doi(dry_run=False, limit=limit)
    return {"processed": p.processed, "enriched": p.enriched,
            "not_found": p.not_found, "no_refs": p.no_refs, "errors": p.errors}


async def extract_keywords_stage(
    limit: int | None = None, batch_size: int = 100, force: bool = False,
    use_keybert: bool = True, fetched_since: str | None = None,
) -> dict[str, int]:
    """Extract BM25/display keywords (sync KeyBERT path) for papers missing them."""
    storage = QdrantStorage()
    extractor = KeywordExtractor(use_keybert=use_keybert)
    processed = with_keywords = total_keywords = 0
    offset = None
    while True:
        papers, next_offset = storage.get_papers_for_keyword_extraction(
            limit=batch_size, offset=offset, skip_existing=not force,
            fetched_since=fetched_since,
        )
        if not papers:
            break
        updates = []
        for point_id, payload in papers:
            title = payload.get("title") or ""
            abstract = payload.get("abstract") or ""
            keywords = extractor.extract(title, abstract)
            source = extractor.get_extraction_source(title, abstract)
            processed += 1
            if keywords:
                with_keywords += 1
                total_keywords += len(keywords)
            updates.append((point_id, keywords, source, None))
        storage.batch_update_keywords_with_source(updates)
        if limit is not None and processed >= limit:
            break
        if next_offset is None:
            break
        offset = next_offset
    return {"processed": processed, "with_keywords": with_keywords,
            "total_keywords": total_keywords}


async def label_abstracts_stage(
    limit: int | None = None, batch_size: int = 500, force: bool = False,
    llm_backend: str = "ollama", fetched_since: str | None = None,
) -> dict[str, int]:
    """Label abstract sentences (rhetorical roles -> abstract_structure)."""
    storage = QdrantStorage()
    labeler = AbstractLabeler(llm_backend=llm_backend)
    processed = labeled = errors = 0
    offset = None
    try:
        while True:
            papers, next_offset = storage.get_papers_for_abstract_labeling(
                limit=batch_size, offset=offset, skip_existing=not force,
                fetched_since=fetched_since,
            )
            if not papers:
                break
            results = await asyncio.gather(*[
                labeler.label_abstract(p.get("title") or "", p.get("abstract") or "")
                for _, p in papers
            ], return_exceptions=True)
            updates = []
            for (point_id, _), result in zip(papers, results):
                if isinstance(result, Exception):
                    errors += 1
                    logger.warning("label_abstract failed for %s: %s", point_id, result)
                    continue
                processed += 1
                structure, source = result
                if structure:
                    labeled += 1
                    updates.append((point_id, structure, source))
            if updates:
                storage.batch_update_abstract_structure(updates)
            if limit is not None and processed >= limit:
                break
            if next_offset is None:
                break
            offset = next_offset
    finally:
        await labeler.close()
    return {"processed": processed, "labeled": labeled, "errors": errors}


async def resolve_refs_stage(
    limit: int | None = None, batch_size: int = 100, parallel: int = 10,
    create_stubs: bool = True, fuzzy_matching: bool = True, external_search: bool = False,
) -> dict[str, int]:
    """Normalize/resolve references and (optionally) create stub papers."""
    storage = QdrantStorage()
    async with ReferenceResolver(
        storage=storage, batch_size=batch_size, max_concurrent=parallel
    ) as resolver:
        results = await resolver.run_full_pipeline(
            dry_run=False, limit=limit, fuzzy_matching=fuzzy_matching,
            external_search=external_search, create_stubs=create_stubs,
        )
    out = {"processed": 0, "updated": 0, "stubs_created": 0, "errors": 0}
    for step in results.values():
        out["processed"] = max(out["processed"], getattr(step, "processed", 0))
        out["updated"] += getattr(step, "updated", 0)
        out["stubs_created"] += getattr(step, "stubs_created", 0)
        out["errors"] += getattr(step, "errors", 0)
    return out


async def enrich_stubs_stage(
    limit: int = 100, parallel: int = 10, identifier_type: str | None = None,
    min_citations: int = 1,
) -> dict[str, int]:
    """Enrich most-cited stub papers with metadata via OpenAlex."""
    storage = QdrantStorage()
    async with StubEnricher(storage=storage, max_concurrent=parallel) as enricher:
        p = await enricher.enrich_stubs(
            limit=limit, identifier_type=identifier_type,
            min_citations=min_citations, dry_run=False,
        )
    return {"processed": p.processed, "enriched": p.enriched, "merged": p.merged,
            "not_found": p.not_found, "errors": p.errors}


async def build_cited_by_stage() -> dict[str, int]:
    """Incrementally build reverse-citation (cited_by) edges."""
    storage = QdrantStorage()
    result = storage.build_cited_by_incremental()
    return {
        "new_papers_processed": result.get("new_papers_processed", 0),
        "new_edges": result.get("new_edges", 0),
        "papers_updated": result.get("papers_updated", 0),
    }


async def analyze_graph_stage(
    pagerank_alpha: float = 0.85, community_resolution: float = 1.0,
) -> dict[str, int]:
    """Build the citation graph and store PageRank/HITS/community metrics to Qdrant."""
    storage = QdrantStorage()
    builder = CitationGraphBuilder(storage=storage)
    graph = builder.build_graph(include_metadata=True)
    analyzer = GraphAnalyzer(graph, storage=storage)
    pagerank = analyzer.compute_pagerank(alpha=pagerank_alpha)
    hubs, authorities = analyzer.compute_hits()
    communities = analyzer.compute_communities(resolution=community_resolution)
    updated = analyzer.store_metrics_to_qdrant(pagerank, hubs, authorities, communities)
    return {"metrics_stored": updated}


async def compute_similarity_stage(
    k: int = 10, batch_size: int = 20, limit: int | None = None,
) -> dict[str, int]:
    """Compute the semantic similarity graph (Qdrant ANN; CPU-bound)."""
    storage = QdrantStorage()
    stats = compute_similarity_batch(storage=storage, k=k, batch_size=batch_size, limit=limit)
    return {"processed": stats.get("processed", 0), "updated": stats.get("updated", 0)}


async def compute_topics_stage(
    umap_n_components: int = 50, umap_n_neighbors: int = 15,
    hdbscan_min_cluster_size: int = 50, hdbscan_min_samples: int = 10,
) -> dict[str, int]:
    """Cluster papers into topics (UMAP + HDBSCAN; CPU-bound)."""
    storage = QdrantStorage()
    results = compute_clusters(
        storage, umap_n_components=umap_n_components, umap_n_neighbors=umap_n_neighbors,
        hdbscan_min_cluster_size=hdbscan_min_cluster_size, hdbscan_min_samples=hdbscan_min_samples,
    )
    if "error" in results:
        raise RuntimeError(results["error"])
    stored = store_cluster_results(storage, results)
    return {"papers": results.get("num_papers", 0), "clusters": results.get("num_clusters", 0),
            "noise": results.get("noise_count", 0), "stored": stored}
