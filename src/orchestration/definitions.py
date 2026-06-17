from dagster import Definitions

from src.orchestration.assets.collection import collect_papers
from src.orchestration.assets.enrichment import enrich_abstracts
from src.orchestration.assets.references import enrich_refs_s2, enrich_refs_crossref
from src.orchestration.assets.keywords import extract_keywords
from src.orchestration.assets.labeling import label_abstracts
from src.orchestration.assets.resolution import resolve_refs, enrich_stubs
from src.orchestration.assets.graph import build_cited_by, analyze_graph
from src.orchestration.assets.embedding import embed_papers
from src.orchestration.assets.analytics import compute_similarity, compute_topics
from src.orchestration.checks import ALL_CHECKS
from src.orchestration.jobs import core_job, maintenance_job
from src.orchestration.schedules import daily_core_schedule, weekly_maintenance_schedule
from src.orchestration.sensors import run_failure_alert_sensor

defs = Definitions(
    assets=[
        collect_papers, enrich_abstracts, enrich_refs_s2, enrich_refs_crossref,
        extract_keywords, label_abstracts, resolve_refs, enrich_stubs,
        build_cited_by, analyze_graph, embed_papers, compute_similarity, compute_topics,
    ],
    asset_checks=ALL_CHECKS,
    jobs=[core_job, maintenance_job],
    schedules=[daily_core_schedule, weekly_maintenance_schedule],
    sensors=[run_failure_alert_sensor],
)
