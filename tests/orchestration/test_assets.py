from unittest.mock import patch
from dagster import materialize, build_asset_context
from src.orchestration.assets.collection import collect_papers
from src.orchestration.assets.enrichment import enrich_abstracts


def test_collect_papers_asset_records_total():
    async def fake_collect(days, source="all"):
        return {"openalex": 5, "openreview": 1, "total": 6}

    with patch("src.orchestration.assets.collection.collect_incremental_stage",
               side_effect=fake_collect):
        result = materialize([collect_papers])
    assert result.success
    mat = result.asset_materializations_for_node("collect_papers")[0]
    assert mat.metadata["total"].value == 6


def test_enrich_abstracts_asset_records_enriched():
    async def fake_enrich(limit=None, batch_size=100, delay=0.1, parallel=10):
        return {"processed": 4, "enriched": 3, "not_found": 1, "errors": 0}

    with patch("src.orchestration.assets.enrichment.enrich_abstracts_stage",
               side_effect=fake_enrich):
        out = enrich_abstracts(build_asset_context())
    assert out.metadata["enriched"].value == 3
