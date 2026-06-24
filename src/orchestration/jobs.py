"""Dagster asset jobs: daily core pipeline + weekly maintenance."""

from dagster import AssetSelection, define_asset_job

from src.orchestration.assets import snapshot as _snapshot_assets

# Daily core: collect -> enrich -> resolve -> graph-build -> embed
CORE_ASSETS = [
    "collect_papers", "enrich_abstracts", "enrich_refs_s2", "enrich_refs_crossref",
    "extract_keywords", "label_abstracts", "resolve_refs", "enrich_stubs",
    "build_cited_by", "embed_papers",
]
# Weekly maintenance: analytics over the latest core materialization
MAINTENANCE_ASSETS = ["compute_similarity", "analyze_graph", "compute_topics"]

core_job = define_asset_job(
    name="core_pipeline_job",
    selection=AssetSelection.assets(*CORE_ASSETS),
)
maintenance_job = define_asset_job(
    name="maintenance_pipeline_job",
    selection=AssetSelection.assets(*MAINTENANCE_ASSETS),
)
snapshot_live_delta_job = define_asset_job(
    name="snapshot_live_delta_job",
    selection=AssetSelection.assets(_snapshot_assets.snapshot_live_delta),
)
