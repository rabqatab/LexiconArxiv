"""Data-quality asset-checks (spec §3). Thin wrappers over src.core.pipeline.dq.

Phase 3b: the three search-critical checks the spec marks for gating are now
BLOCKING ERROR — observed live values pass cleanly: #3 doi_papers_have_refs=0.97
(>0.80), #6 embedding_coverage_complete=0 missing, #7 graph_metrics_stored=full
corpus. The remaining checks stay WARN (coverage metrics that legitimately
fluctuate). #6 only became trustworthy after fixing the dq filter to treat
empty-string abstracts as "no abstract" (Qdrant IsEmpty does not match ""); it
had falsely reported ~27k embeddable-missing-vector papers that are in fact the
no-abstract floor.
"""

from dagster import AssetCheckResult, AssetCheckSeverity, asset_check

from src.core.pipeline import dq

_WARN = AssetCheckSeverity.WARN
_ERROR = AssetCheckSeverity.ERROR


def _result(payload: dict, severity: AssetCheckSeverity = _WARN) -> AssetCheckResult:
    return AssetCheckResult(passed=payload["passed"], severity=severity, metadata=payload["metadata"])


@asset_check(asset="enrich_refs_crossref", name="doi_papers_have_refs", blocking=True,
             description="Of DOI papers, fraction with referenced_works (BLOCKING ERROR, spec #3)")
def doi_papers_have_refs_check() -> AssetCheckResult:
    return _result(dq.doi_papers_have_refs(), _ERROR)


@asset_check(asset="enrich_abstracts", name="abstract_coverage",
             description="Fraction of real papers with an abstract (warn-only)")
def abstract_coverage_check() -> AssetCheckResult:
    return _result(dq.abstract_coverage())


@asset_check(asset="embed_papers", name="embedding_coverage_complete", blocking=True,
             description="Embeddable papers missing the dense vector (BLOCKING ERROR, spec #6)")
def embedding_coverage_check() -> AssetCheckResult:
    return _result(dq.embedding_coverage_complete(), _ERROR)


@asset_check(asset="analyze_graph", name="graph_metrics_stored", blocking=True,
             description="Papers with stored pagerank (BLOCKING ERROR, spec #7: 'ran but stored nothing')")
def graph_metrics_stored_check() -> AssetCheckResult:
    return _result(dq.graph_metrics_stored(), _ERROR)


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


@asset_check(asset="label_abstracts", name="abstract_labeling_gap",
             description="Real papers with abstract but no abstract_structure (warn-only, 2026-07-04 gap signal)")
def abstract_labeling_gap_check() -> AssetCheckResult:
    return _result(dq.abstract_labeling_gap())


@asset_check(asset="discover_gaps", name="nontarget_topic_share",
             description="Non-stub papers outside the Wave 4c topic whitelist (warn-only gate-drift signal)")
def nontarget_topic_share_check() -> AssetCheckResult:
    return _result(dq.nontarget_topic_share())


@asset_check(asset="discover_gaps", name="no_primary_topic_share",
             description="Non-stub papers with no primary_topic (warn-only, Wave 4c)")
def no_primary_topic_share_check() -> AssetCheckResult:
    return _result(dq.no_primary_topic_share())


ALL_CHECKS = [
    doi_papers_have_refs_check, abstract_coverage_check, embedding_coverage_check,
    graph_metrics_stored_check, cluster_coverage_check, real_papers_have_titles_check,
    source_not_silently_zero_check, abstract_labeling_gap_check,
    nontarget_topic_share_check, no_primary_topic_share_check,
]
