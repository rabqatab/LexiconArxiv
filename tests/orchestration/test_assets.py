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


def test_embed_papers_asset_records_embedded():
    from src.orchestration.assets.embedding import embed_papers

    async def fake_embed(**kwargs):
        return {"embedded": 5}

    with patch("src.orchestration.assets.embedding.embed_papers_stage",
               side_effect=fake_embed):
        out = embed_papers(build_asset_context())
    assert out.metadata["embedded"].value == 5


# --- Phase-2 asset tests ---

def test_enrich_refs_s2_asset_records_enriched():
    from src.orchestration.assets.references import enrich_refs_s2
    async def fake(**k): return {"processed": 8, "enriched": 5, "not_found": 2, "no_refs": 1, "errors": 0}
    with patch("src.orchestration.assets.references.enrich_refs_s2_stage", side_effect=fake):
        out = enrich_refs_s2(build_asset_context())
    assert out.metadata["enriched"].value == 5


def test_enrich_refs_crossref_asset_records_enriched():
    from src.orchestration.assets.references import enrich_refs_crossref
    async def fake(**k): return {"processed": 4, "enriched": 3, "not_found": 1, "no_refs": 0, "errors": 0}
    with patch("src.orchestration.assets.references.enrich_refs_crossref_stage", side_effect=fake):
        out = enrich_refs_crossref(build_asset_context())
    assert out.metadata["enriched"].value == 3


def test_extract_keywords_asset_records_processed():
    from src.orchestration.assets.keywords import extract_keywords
    async def fake(**k): return {"processed": 10, "with_keywords": 9, "total_keywords": 45}
    with patch("src.orchestration.assets.keywords.extract_keywords_stage", side_effect=fake):
        out = extract_keywords(build_asset_context())
    assert out.metadata["processed"].value == 10


def test_label_abstracts_asset_records_labeled():
    from src.orchestration.assets.labeling import label_abstracts
    async def fake(**k): return {"processed": 7, "labeled": 6}
    with patch("src.orchestration.assets.labeling.label_abstracts_stage", side_effect=fake):
        out = label_abstracts(build_asset_context())
    assert out.metadata["labeled"].value == 6


def test_resolve_refs_asset_records_updated():
    from src.orchestration.assets.resolution import resolve_refs
    async def fake(**k): return {"processed": 20, "updated": 15, "stubs_created": 5, "errors": 0}
    with patch("src.orchestration.assets.resolution.resolve_refs_stage", side_effect=fake):
        out = resolve_refs(build_asset_context())
    assert out.metadata["updated"].value == 15


def test_enrich_stubs_asset_records_enriched():
    from src.orchestration.assets.resolution import enrich_stubs
    async def fake(**k): return {"processed": 5, "enriched": 3, "merged": 1, "not_found": 1, "errors": 0}
    with patch("src.orchestration.assets.resolution.enrich_stubs_stage", side_effect=fake):
        out = enrich_stubs(build_asset_context())
    assert out.metadata["enriched"].value == 3


def test_build_cited_by_asset_records_new_edges():
    from src.orchestration.assets.graph import build_cited_by
    async def fake(**k): return {"new_papers_processed": 12, "new_edges": 30, "papers_updated": 9}
    with patch("src.orchestration.assets.graph.build_cited_by_stage", side_effect=fake):
        out = build_cited_by(build_asset_context())
    assert out.metadata["new_edges"].value == 30


def test_analyze_graph_asset_records_metrics():
    from src.orchestration.assets.graph import analyze_graph
    async def fake(**k): return {"metrics_stored": 424000}
    with patch("src.orchestration.assets.graph.analyze_graph_stage", side_effect=fake):
        out = analyze_graph(build_asset_context())
    assert out.metadata["metrics_stored"].value == 424000


def test_compute_similarity_asset_records_updated():
    from src.orchestration.assets.analytics import compute_similarity
    async def fake(**k): return {"processed": 100, "updated": 95}
    with patch("src.orchestration.assets.analytics.compute_similarity_stage", side_effect=fake):
        out = compute_similarity(build_asset_context())
    assert out.metadata["updated"].value == 95


def test_compute_topics_asset_records_clusters():
    from src.orchestration.assets.analytics import compute_topics
    async def fake(**k): return {"papers": 100, "clusters": 8, "noise": 12, "stored": 100}
    with patch("src.orchestration.assets.analytics.compute_topics_stage", side_effect=fake):
        out = compute_topics(build_asset_context())
    assert out.metadata["clusters"].value == 8
