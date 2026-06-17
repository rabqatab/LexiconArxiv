"""Warn-only data-quality asset-checks (spec §3). Thin wrappers over src.core.pipeline.dq."""

from dagster import AssetCheckResult, AssetCheckSeverity, asset_check

from src.core.pipeline import dq

_WARN = AssetCheckSeverity.WARN


def _result(payload: dict) -> AssetCheckResult:
    return AssetCheckResult(passed=payload["passed"], severity=_WARN, metadata=payload["metadata"])


@asset_check(asset="enrich_refs_crossref", name="doi_papers_have_refs",
             description="Of DOI papers, fraction with referenced_works (warn-only)")
def doi_papers_have_refs_check() -> AssetCheckResult:
    return _result(dq.doi_papers_have_refs())


@asset_check(asset="enrich_abstracts", name="abstract_coverage",
             description="Fraction of real papers with an abstract (warn-only)")
def abstract_coverage_check() -> AssetCheckResult:
    return _result(dq.abstract_coverage())


@asset_check(asset="embed_papers", name="embedding_coverage_complete",
             description="Embeddable papers missing the dense vector (warn-only)")
def embedding_coverage_check() -> AssetCheckResult:
    return _result(dq.embedding_coverage_complete())


@asset_check(asset="analyze_graph", name="graph_metrics_stored",
             description="Papers with stored pagerank (warn-only)")
def graph_metrics_stored_check() -> AssetCheckResult:
    return _result(dq.graph_metrics_stored())


@asset_check(asset="compute_topics", name="cluster_coverage",
             description="Clustered count + noise fraction (warn-only)")
def cluster_coverage_check() -> AssetCheckResult:
    return _result(dq.cluster_coverage())


@asset_check(asset="collect_papers", name="real_papers_have_titles",
             description="Non-stub papers with empty/null title (warn-only)")
def real_papers_have_titles_check() -> AssetCheckResult:
    return _result(dq.real_papers_have_titles())


@asset_check(asset="collect_papers", name="source_not_silently_zero",
             description="No source has a zero count (warn-only)")
def source_not_silently_zero_check() -> AssetCheckResult:
    return _result(dq.source_not_silently_zero())


ALL_CHECKS = [
    doi_papers_have_refs_check, abstract_coverage_check, embedding_coverage_check,
    graph_metrics_stored_check, cluster_coverage_check, real_papers_have_titles_check,
    source_not_silently_zero_check,
]
