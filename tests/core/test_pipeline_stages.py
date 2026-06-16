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
    embedder = AsyncMock()
    embedder.__aenter__.return_value = embedder
    embedder.__aexit__.return_value = False
    embedder.check_model_available.return_value = True
    embedder.embed_and_upsert_batch.return_value = 2

    storage = MagicMock()
    # one batch of two papers, then no more (next_offset=None)
    storage.get_papers_for_embedding.return_value = ([{"id": "a"}, {"id": "b"}], None)

    with patch.object(stages, "PaperEmbedder", return_value=embedder), \
         patch.object(stages, "QdrantStorage", return_value=storage):
        result = asyncio.run(stages.embed_papers_stage(batch_size=2))

    assert result == {"embedded": 2}
