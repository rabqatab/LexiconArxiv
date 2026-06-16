import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.core.pipeline import stages


def test_collect_incremental_stage_returns_per_source_counts():
    fake = AsyncMock()
    fake.__aenter__.return_value = fake
    fake.__aexit__.return_value = False
    fake.collect_incremental.return_value = 42

    with patch.object(stages, "CoreCorpusCollector", return_value=fake), \
         patch.object(stages, "QdrantStorage") as Storage:
        Storage.return_value.ensure_collection.return_value = None
        result = asyncio.run(stages.collect_incremental_stage(days=3, source="openalex"))

    assert result["openalex"] == 42
    assert result["total"] == 42


def test_enrich_abstracts_stage_returns_progress_counts():
    enricher = AsyncMock()
    enricher.__aenter__.return_value = enricher
    enricher.__aexit__.return_value = False
    progress = type("P", (), {"processed": 10, "enriched": 7, "not_found": 3, "errors": 0})()
    enricher.enrich_abstracts.return_value = progress

    with patch.object(stages, "PaperEnricher", return_value=enricher), \
         patch.object(stages, "QdrantStorage"):
        result = asyncio.run(stages.enrich_abstracts_stage(limit=None, parallel=10))

    assert result == {"processed": 10, "enriched": 7, "not_found": 3, "errors": 0}


def test_embed_papers_stage_returns_embedded_count():
    from src.core.constants import ALL_DENSE_VECTORS

    embedder = AsyncMock()
    embedder.__aenter__.return_value = embedder
    embedder.__aexit__.return_value = False
    embedder.check_model_available.return_value = True
    embedder.embed_and_upsert_batch.return_value = 2

    storage = MagicMock()
    # one batch of two papers, then no more (next_offset=None)
    storage.get_papers_for_embedding.return_value = ([{"id": "a"}, {"id": "b"}], None)
    # Satisfy the vector pre-flight check: return a dict containing all required dense vectors.
    storage.client.get_collection.return_value.config.params.vectors = {v: MagicMock() for v in ALL_DENSE_VECTORS}

    with patch.object(stages, "PaperEmbedder", return_value=embedder), \
         patch.object(stages, "QdrantStorage", return_value=storage):
        result = asyncio.run(stages.embed_papers_stage(batch_size=2))

    assert result == {"embedded": 2}


def test_enrich_refs_s2_stage_returns_counts():
    enricher = AsyncMock()
    enricher.__aenter__.return_value = enricher
    enricher.__aexit__.return_value = False
    enricher.enrich_by_doi.return_value = type("P", (), {
        "processed": 8, "enriched": 5, "not_found": 2, "no_refs": 1, "errors": 0})()
    with patch.object(stages, "SemanticScholarEnricher", return_value=enricher), \
         patch.object(stages, "QdrantStorage"):
        result = asyncio.run(stages.enrich_refs_s2_stage(limit=None, parallel=10))
    assert result == {"processed": 8, "enriched": 5, "not_found": 2, "no_refs": 1, "errors": 0}


def test_enrich_refs_crossref_stage_returns_counts():
    enricher = AsyncMock()
    enricher.__aenter__.return_value = enricher
    enricher.__aexit__.return_value = False
    enricher.enrich_by_doi.return_value = type("P", (), {
        "processed": 4, "enriched": 3, "not_found": 1, "no_refs": 0, "errors": 0})()
    with patch.object(stages, "CrossRefEnricher", return_value=enricher):
        result = asyncio.run(stages.enrich_refs_crossref_stage(limit=None, parallel=10))
    assert result == {"processed": 4, "enriched": 3, "not_found": 1, "no_refs": 0, "errors": 0}


def test_extract_keywords_stage_returns_counts():
    extractor = MagicMock()
    extractor.extract.return_value = ["kw1", "kw2"]
    extractor.get_extraction_source.return_value = "keybert"
    storage = MagicMock()
    storage.get_papers_for_keyword_extraction.return_value = (
        [("id1", {"title": "T", "abstract": "A"})], None)
    with patch.object(stages, "KeywordExtractor", return_value=extractor), \
         patch.object(stages, "QdrantStorage", return_value=storage):
        result = asyncio.run(stages.extract_keywords_stage(batch_size=10))
    assert result["processed"] == 1
    assert result["with_keywords"] == 1


def test_label_abstracts_stage_returns_counts():
    labeler = AsyncMock()
    labeler.label_abstract.return_value = ({"task": "x"}, "gemini")
    labeler.close.return_value = None
    storage = MagicMock()
    storage.get_papers_for_abstract_labeling.return_value = (
        [("id1", {"title": "T", "abstract": "A"})], None)
    with patch.object(stages, "AbstractLabeler", return_value=labeler), \
         patch.object(stages, "QdrantStorage", return_value=storage):
        result = asyncio.run(stages.label_abstracts_stage(batch_size=10))
    assert result == {"processed": 1, "labeled": 1}


def test_resolve_refs_stage_returns_counts():
    resolver = AsyncMock()
    resolver.__aenter__.return_value = resolver
    resolver.__aexit__.return_value = False
    step = type("RP", (), {"processed": 6, "updated": 4, "stubs_created": 3, "errors": 0})()
    resolver.run_full_pipeline.return_value = {"normalize": step, "arxiv": step, "internal": step}
    with patch.object(stages, "ReferenceResolver", return_value=resolver), \
         patch.object(stages, "QdrantStorage"):
        result = asyncio.run(stages.resolve_refs_stage())
    assert result["stubs_created"] == 9   # summed across 3 steps
    assert result["updated"] == 12


def test_enrich_stubs_stage_returns_counts():
    enricher = AsyncMock()
    enricher.__aenter__.return_value = enricher
    enricher.__aexit__.return_value = False
    enricher.enrich_stubs.return_value = type("SP", (), {
        "processed": 5, "enriched": 3, "merged": 1, "not_found": 1, "errors": 0})()
    with patch.object(stages, "StubEnricher", return_value=enricher), \
         patch.object(stages, "QdrantStorage"):
        result = asyncio.run(stages.enrich_stubs_stage(limit=100, parallel=10))
    assert result == {"processed": 5, "enriched": 3, "merged": 1, "not_found": 1, "errors": 0}


def test_build_cited_by_stage_returns_counts():
    storage = MagicMock()
    storage.build_cited_by_incremental.return_value = {
        "new_papers_processed": 12, "new_edges": 30, "papers_updated": 9}
    with patch.object(stages, "QdrantStorage", return_value=storage):
        result = asyncio.run(stages.build_cited_by_stage())
    assert result == {"new_papers_processed": 12, "new_edges": 30, "papers_updated": 9}


def test_analyze_graph_stage_returns_counts():
    builder = MagicMock()
    builder.build_graph.return_value = MagicMock()  # nx.DiGraph stand-in
    analyzer = MagicMock()
    analyzer.compute_pagerank.return_value = {"a": 0.5}
    analyzer.compute_hits.return_value = ({"a": 0.1}, {"a": 0.2})
    analyzer.compute_communities.return_value = {"a": 0}
    analyzer.store_metrics_to_qdrant.return_value = 1
    with patch.object(stages, "CitationGraphBuilder", return_value=builder), \
         patch.object(stages, "GraphAnalyzer", return_value=analyzer), \
         patch.object(stages, "QdrantStorage"):
        result = asyncio.run(stages.analyze_graph_stage())
    assert result == {"metrics_stored": 1}


def test_compute_similarity_stage_returns_counts():
    storage = MagicMock()
    with patch.object(stages, "QdrantStorage", return_value=storage), \
         patch.object(stages, "compute_similarity_batch",
                      return_value={"processed": 100, "updated": 95}) as csb:
        result = asyncio.run(stages.compute_similarity_stage(k=10, batch_size=50))
    assert result == {"processed": 100, "updated": 95}
    assert csb.called
