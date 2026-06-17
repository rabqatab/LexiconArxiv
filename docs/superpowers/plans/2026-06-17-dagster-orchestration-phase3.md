# Dagster Orchestration — Phase 3 (Data-Quality Asset-Checks) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add data-quality (DQ) asset-checks (spec §3) to the Dagster DAG as **warn-only** observability — each check counts a coverage/sanity metric from Qdrant and emits a pass/warn `AssetCheckResult` with the numbers as metadata.

**Architecture:** DQ logic lives in plain, testable functions in `src/core/pipeline/dq.py` (each returns `{"passed": bool, "metadata": dict}` from Qdrant `client.count()` queries); thin `@asset_check` wrappers in `src/orchestration/checks.py` convert them to `AssetCheckResult(severity=WARN)` and attach to the relevant asset by name. Checks are registered via `Definitions(asset_checks=[...])`. No data store changes — pure reads.

**Tech Stack:** Python 3.12, uv, Dagster 1.13.9 (`asset_check`, `AssetCheckResult`, `AssetCheckSeverity`), Qdrant. Tests: `uv run --extra dev pytest`.

**Scope note:** This is the **warn-first calibration slice** of spec §3. Per the spec's own staged policy ("add DQ checks in warn-only first to calibrate thresholds, then flip search-critical checks #3/#6/#7 to ERROR + flagging"), the `dq_flags` quarantine field, `blocking=True` ERROR severity, and threshold tightening are an explicit **follow-up (Phase 3b)** done after observing real warn values — not built blind here (YAGNI). Builds on Phase 1+2 (merged, 13 assets). Spec: `docs/superpowers/specs/2026-06-03-dagster-orchestration-design.md` §3.

---

## Conventions (every task)
- Test command: `uv run --extra dev pytest <args>` (pytest is in the `dev` extra).
- TDD: failing test → confirm fail → implement → confirm pass → commit.
- Commits: `git commit --author="rabqatab <minhan.nick.cho@gmail.com>" -m "..."`. NEVER add `Co-Authored-By` / "Generated with Claude Code". Verify `git log -1 --format="%B" | grep -i co-authored` is empty. `tests/` is NOT gitignored (plain `git add`).
- DQ functions are pure reads (Qdrant `client.count`) returning `{"passed": bool, "metadata": dict[str,int|float|str]}`. Thresholds are module constants marked CALIBRATION (warn-only, no production gating yet).

## Verified facts (from 2026-06-17 grounding)
- Imports: `from dagster import asset_check, AssetCheckResult, AssetCheckSeverity`. `@asset_check(asset="<asset_name>", name=..., description=...)` (asset accepts the asset's name string). Returns an `AssetChecksDefinition` (NOT a plain callable — so test the `dq.py` logic functions directly, not the decorated wrapper).
- `AssetCheckResult(passed=bool, severity=AssetCheckSeverity.WARN, metadata={...}, description=...)`.
- Register via `Definitions(assets=[...], asset_checks=[...])` — a SEPARATE arg; checks are NOT auto-collected.
- Count pattern: `storage.client.count(collection_name=storage.collection_name, count_filter=models.Filter(must=[...], must_not=[...]), exact=True).count`.
- Payload fields: `is_stub` (True on stubs; absent on real), `doi` (str, "" if none), `referenced_works` (list), `abstract` (str, "" if none), `pagerank` (float, absent until analyze_graph), `cluster_id` (int, -1=noise, absent until compute_topics), `title` (str), `source_id` (str; no bare `source` field), `fetched_at` (ISO str). Vector name: `"structured-abstract"` (`STRUCTURED_VECTOR_NAME` in `src/core/constants.py`).
- Filter conditions: `models.FieldCondition(key, match=models.MatchValue(value=...))`, `models.IsEmptyCondition(is_empty=models.PayloadField(key=...))` (null OR empty), `models.IsNullCondition(is_null=models.PayloadField(key=...))`, `models.HasVectorCondition(has_vector="structured-abstract")`.
- Existing helpers reusable: `storage.count_real_papers()` (non-stub total), `storage.get_data_quality_stats()` (returns `by_source` dict via scroll).

---

## File Structure
- Create `src/core/pipeline/dq.py` — DQ metric functions (pure reads)
- Create `src/orchestration/checks.py` — `@asset_check` wrappers
- Modify `src/orchestration/definitions.py` — add `asset_checks=[...]`
- Create `tests/core/test_dq.py` — unit tests for dq functions
- Modify `tests/orchestration/test_assets.py` — (optional) a validate smoke for checks

---

## Task 1: DQ metric functions — the 6 cheap count-based checks

**Files:** Create `src/core/pipeline/dq.py`; Test: `tests/core/test_dq.py`.

These 6 are single/double `client.count()` calls. Each returns `{"passed": bool, "metadata": {...}}`.

- [ ] **Step 1: Failing tests.** Create `tests/core/test_dq.py`:
```python
from unittest.mock import MagicMock, patch
from src.core.pipeline import dq


def _storage_with_counts(counts):
    """counts: list of ints returned by successive client.count(...).count calls."""
    storage = MagicMock()
    storage.collection_name = "c"
    results = [MagicMock(count=n) for n in counts]
    storage.client.count.side_effect = results
    return storage


def test_doi_papers_have_refs_pass():
    # total_doi=100, missing_refs=10 -> with_refs=90 -> 90% >= 80% threshold -> pass
    storage = _storage_with_counts([100, 10])
    r = dq.doi_papers_have_refs(storage)
    assert r["passed"] is True
    assert r["metadata"]["doi_papers"] == 100
    assert r["metadata"]["with_refs"] == 90


def test_doi_papers_have_refs_warn_below_threshold():
    storage = _storage_with_counts([100, 50])  # 50% < 80%
    r = dq.doi_papers_have_refs(storage)
    assert r["passed"] is False


def test_doi_papers_have_refs_zero_denominator_passes():
    storage = _storage_with_counts([0, 0])
    r = dq.doi_papers_have_refs(storage)
    assert r["passed"] is True  # nothing to check


def test_real_papers_have_titles_pass():
    storage = _storage_with_counts([0])  # 0 missing titles
    r = dq.real_papers_have_titles(storage)
    assert r["passed"] is True
    assert r["metadata"]["missing_titles"] == 0


def test_real_papers_have_titles_warn():
    storage = _storage_with_counts([5])
    r = dq.real_papers_have_titles(storage)
    assert r["passed"] is False
    assert r["metadata"]["missing_titles"] == 5


def test_graph_metrics_stored_pass():
    storage = _storage_with_counts([424000])
    r = dq.graph_metrics_stored(storage)
    assert r["passed"] is True
    assert r["metadata"]["papers_with_pagerank"] == 424000


def test_graph_metrics_stored_warn_when_zero():
    storage = _storage_with_counts([0])
    r = dq.graph_metrics_stored(storage)
    assert r["passed"] is False
```
(Add analogous tests for `abstract_coverage`, `embedding_coverage_complete`, `cluster_coverage` following the same shape — pass case, warn case, and zero-denominator-passes where applicable.)

- [ ] **Step 2: Run, confirm fail** (`ModuleNotFoundError: src.core.pipeline.dq`).

- [ ] **Step 3: Implement `src/core/pipeline/dq.py`:**
```python
"""Data-quality metric functions for Dagster asset-checks.

Each returns {"passed": bool, "metadata": dict}. Pure reads over Qdrant via
client.count(). Thresholds are CALIBRATION constants (warn-only phase) — tune
after observing real values, before any flip to blocking ERROR (Phase 3b).
"""

from qdrant_client import models

from src.core.storage import QdrantStorage
from src.core.constants import STRUCTURED_VECTOR_NAME

# CALIBRATION thresholds (warn-only)
MIN_DOI_REFS_RATIO = 0.80
MIN_ABSTRACT_COVERAGE = 0.80
MAX_CLUSTER_NOISE_RATIO = 0.40

_STUB = models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))


def _count(storage, must=None, must_not=None) -> int:
    return storage.client.count(
        collection_name=storage.collection_name,
        count_filter=models.Filter(must=must, must_not=must_not),
        exact=True,
    ).count


def doi_papers_have_refs(storage: QdrantStorage | None = None) -> dict:
    """Of non-stub papers WITH a DOI, what fraction have referenced_works."""
    storage = storage or QdrantStorage()
    no_doi = models.IsEmptyCondition(is_empty=models.PayloadField(key="doi"))
    total_doi = _count(storage, must_not=[_STUB, no_doi])
    missing_refs = _count(
        storage,
        must=[models.IsEmptyCondition(is_empty=models.PayloadField(key="referenced_works"))],
        must_not=[_STUB, no_doi],
    )
    with_refs = total_doi - missing_refs
    ratio = (with_refs / total_doi) if total_doi else 1.0
    return {
        "passed": ratio >= MIN_DOI_REFS_RATIO,
        "metadata": {"doi_papers": total_doi, "with_refs": with_refs,
                     "ratio": round(ratio, 4)},
    }


def abstract_coverage(storage: QdrantStorage | None = None) -> dict:
    """Fraction of non-stub papers with a non-empty abstract."""
    storage = storage or QdrantStorage()
    total = storage.count_real_papers()
    missing = _count(
        storage,
        must=[models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract"))],
        must_not=[_STUB],
    )
    with_abs = total - missing
    ratio = (with_abs / total) if total else 1.0
    return {
        "passed": ratio >= MIN_ABSTRACT_COVERAGE,
        "metadata": {"real_papers": total, "with_abstract": with_abs,
                     "ratio": round(ratio, 4)},
    }


def embedding_coverage_complete(storage: QdrantStorage | None = None) -> dict:
    """Of non-stub papers WITH an abstract, all should have the dense vector."""
    storage = storage or QdrantStorage()
    # non-stub, abstract non-empty, but missing the structured-abstract vector
    missing_vec = _count(
        storage,
        must_not=[
            _STUB,
            models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract")),
            models.HasVectorCondition(has_vector=STRUCTURED_VECTOR_NAME),
        ],
    )
    return {
        "passed": missing_vec == 0,
        "metadata": {"embeddable_missing_vector": missing_vec},
    }


def graph_metrics_stored(storage: QdrantStorage | None = None) -> dict:
    """Papers with a pagerank payload (graph metrics were stored)."""
    storage = storage or QdrantStorage()
    with_pr = _count(
        storage,
        must_not=[models.IsNullCondition(is_null=models.PayloadField(key="pagerank"))],
    )
    return {"passed": with_pr > 0, "metadata": {"papers_with_pagerank": with_pr}}


def cluster_coverage(storage: QdrantStorage | None = None) -> dict:
    """Clustered-paper count and noise fraction (cluster_id == -1)."""
    storage = storage or QdrantStorage()
    clustered = _count(
        storage,
        must_not=[models.IsNullCondition(is_null=models.PayloadField(key="cluster_id"))],
    )
    noise = _count(
        storage,
        must=[models.FieldCondition(key="cluster_id", match=models.MatchValue(value=-1))],
    )
    noise_ratio = (noise / clustered) if clustered else 0.0
    return {
        "passed": clustered > 0 and noise_ratio <= MAX_CLUSTER_NOISE_RATIO,
        "metadata": {"clustered": clustered, "noise": noise,
                     "noise_ratio": round(noise_ratio, 4)},
    }


def real_papers_have_titles(storage: QdrantStorage | None = None) -> dict:
    """Non-stub papers with a null/empty title (should be zero)."""
    storage = storage or QdrantStorage()
    missing = _count(
        storage,
        must=[models.IsEmptyCondition(is_empty=models.PayloadField(key="title"))],
        must_not=[_STUB],
    )
    return {"passed": missing == 0, "metadata": {"missing_titles": missing}}
```

- [ ] **Step 4: Run, confirm pass.** **Step 5: Commit** (`feat(dq): add core data-quality metric functions`).

> Execution note: confirm `storage.count_real_papers()` exists (grounding: `src/core/storage/stubs.py:406`) and `STRUCTURED_VECTOR_NAME` is importable from `src/core/constants.py`. If `count_real_papers` is absent, substitute `_count(storage, must_not=[_STUB])`.

---

## Task 2: DQ metric functions — the 2 scroll-based collection checks

**Files:** Modify `src/core/pipeline/dq.py`; Test: `tests/core/test_dq.py`.

`new_paper_count_sane` and `source_not_silently_zero` can't use `client.count` cheaply (`fetched_at` is an ISO string with no server-side range filter; there's no `source` field). Reuse the existing scroll-based `storage.get_data_quality_stats()` which returns `by_source` counts, and a recent-count via its totals.

- [ ] **Step 1: Failing tests.** Append to `tests/core/test_dq.py`:
```python
def test_source_not_silently_zero_pass():
    storage = MagicMock()
    storage.get_data_quality_stats.return_value = {
        "by_source": {"openalex": 100, "acl": 50, "dblp": 30, "openreview": 200, "aaai": 10}}
    r = dq.source_not_silently_zero(storage)
    assert r["passed"] is True
    assert r["metadata"]["zero_sources"] == 0


def test_source_not_silently_zero_warn_on_zero_source():
    storage = MagicMock()
    storage.get_data_quality_stats.return_value = {
        "by_source": {"openalex": 100, "acl": 0, "dblp": 30}}
    r = dq.source_not_silently_zero(storage)
    assert r["passed"] is False
    assert "acl" in r["metadata"]["zero_source_names"]
```

- [ ] **Step 2: Run, confirm fail.**
- [ ] **Step 3: Implement.** Append to `dq.py`:
```python
def source_not_silently_zero(storage: QdrantStorage | None = None) -> dict:
    """No known source has a zero count in the corpus (a collector broke silently)."""
    storage = storage or QdrantStorage()
    by_source = storage.get_data_quality_stats().get("by_source", {})
    zero = sorted(name for name, n in by_source.items() if n == 0)
    return {
        "passed": len(zero) == 0,
        "metadata": {"sources": len(by_source), "zero_sources": len(zero),
                     "zero_source_names": ", ".join(zero) or "none"},
    }
```
> Execution note: confirm the exact shape of `get_data_quality_stats()` (`src/core/storage/statistics.py`). If `by_source` keys are source-id prefixes rather than friendly names, that is fine — the check still flags a zero. `new_paper_count_sane` is intentionally DEFERRED to Phase 3b (needs a rolling baseline persisted across runs to define "within band"; a single point-in-time count can't judge "sane" without history). Document this in the check module, do not stub it.

- [ ] **Step 4: Run, confirm pass.** **Step 5: Commit** (`feat(dq): add source_not_silently_zero metric`).

---

## Task 3: `@asset_check` wrappers + register in Definitions

**Files:** Create `src/orchestration/checks.py`; Modify `src/orchestration/definitions.py`; Test: command-line validate.

- [ ] **Step 1: Implement `src/orchestration/checks.py`** (7 warn-only checks; thin wrappers over `dq`):
```python
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
```

- [ ] **Step 2: Register in `definitions.py`.** Add `from src.orchestration.checks import ALL_CHECKS` and pass `asset_checks=ALL_CHECKS` to `Definitions(...)`.

- [ ] **Step 3: Validate.**
`uv run dagster definitions validate -m src.orchestration.definitions`
Expected: "Validation successful" — 13 assets + 7 asset checks load, every `asset="<name>"` resolves to a real asset (a typo'd asset name fails here).

- [ ] **Step 4: Full suite.**
`uv run --extra dev pytest tests/core/test_dq.py tests/orchestration tests/core/test_pipeline_stages.py -v` — all pass.

- [ ] **Step 5: Commit** (`feat(orchestration): warn-only DQ asset-checks + register`).

---

## Task 4: Optional live smoke (read-only, safe)

**Files:** none.

- [ ] **Step 1:** With Qdrant up, sanity-run the dq functions against the live corpus to confirm the filters return sane numbers (read-only):
```bash
uv run python -c "
from src.core.pipeline import dq
for f in ['doi_papers_have_refs','abstract_coverage','embedding_coverage_complete','graph_metrics_stored','cluster_coverage','real_papers_have_titles','source_not_silently_zero']:
    print(f, getattr(dq, f)())
"
```
Expected: each prints `{passed, metadata}` with plausible counts (e.g. abstract_coverage ratio ~0.84, embedding_coverage embeddable_missing_vector ~0). Use these real numbers to record initial CALIBRATION baselines (comment in dq.py) for the eventual Phase 3b threshold tightening. Read-only — no commit unless thresholds are adjusted.

---

## Self-Review
- **Spec §3 coverage:** 7 of 9 checks implemented warn-only (doi_papers_have_refs #3, abstract_coverage #4, embedding_coverage_complete #6, graph_metrics_stored #7, cluster_coverage #8, real_papers_have_titles #9, source_not_silently_zero #2). **Deferred to Phase 3b with documented reasons:** #1 `new_paper_count_sane` (needs persisted rolling baseline), #5 `no_dangling_graph_nodes` (no post-hoc Qdrant query; needs `build_cited_by` to persist its build-time `skipped_missing` count). Also Phase 3b: `dq_flags` quarantine field + flip #3/#6/#7 to `blocking=True` ERROR after warn-data calibration (spec's stated staging).
- **Placeholder scan:** complete code for all dq functions + checks; "Execution notes" are signature confirmations, not stubs.
- **Type consistency:** every `dq.*` returns `{"passed": bool, "metadata": dict}`; every check wraps via `_result(...)` → `AssetCheckResult(severity=WARN)`; `asset="<name>"` strings match real asset function names; registered via `Definitions(asset_checks=ALL_CHECKS)`.

## Out of scope → next plans
- **Phase 3b:** `new_paper_count_sane` + `no_dangling_graph_nodes` (persist build-time dangling count); `dq_flags` payload + flip search-critical checks (#3/#6/#7) to `blocking=True` ERROR with row flagging, after calibrating thresholds from warn data.
- **Plan 4:** daily/weekly schedules + partitions + run-failure/check-failure sensor; retire bash orchestrator.
