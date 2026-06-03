# Dagster Orchestration + Data-Quality Gates — Design

**Date:** 2026-06-03
**Status:** Approved design, pending implementation plan
**Author:** brainstormed with Claude Code

## 1. Motivation

The pipeline currently runs as a bash orchestrator (`scripts/run_incremental_pipeline.sh`) with `set -e` + an `ERR` trap + `pipeline_status.json`. The 2026-06-03 incremental exposed its limits: a single typo'd CLI command (`analyze-graph` vs `analyze-citation-graph`) plus two unguarded data conditions (null title, dangling graph node) took down a multi-hour run, and recovery required a hand-written `run_incremental_resume_<date>.sh`. There is no per-stage retry, no resume-from-failed, no data-quality gating, and no observability beyond grepping logs.

This design replaces the orchestration layer with **Dagster**, dispatching GPU-heavy stages to the **DGX Sparks via `sparkq`**, and adds **data-quality (DQ) gates** as first-class asset checks.

### Drivers (all four in scope)
1. **Robustness / resume** — per-stage retries, restart-from-failed without hand-written scripts.
2. **Data-quality gates** — assertions between stages that block or flag bad data.
3. **Scheduling / observability** — UI, run history, per-asset logs/durations, alerting, backfills.
4. **Parallelism / scale** — concurrent independent stages; heavy GPU steps offloaded to the Sparks.

## 2. Architecture

Dagster runs on **Node 1**, co-located with Qdrant (`localhost:6333`). Stages split into two execution modes:

- **Native assets** — in-process Python that calls `src/core/*` functions directly (ported from the CLI logic). Used for CPU/IO stages.
- **sparkq assets** — submit a command to the DGX Sparks via `sparkq`, poll to terminal, map status. Used for GPU-heavy stages.

GPU work must run on the Sparks (a separate process, possibly Node 2), so it cannot be "native in-process"; this is the deliberate exception to native porting.

### Asset graph

```
NATIVE ASSETS (in-process Python → src/core/*)
  collect_papers
    → enrich_abstracts → enrich_refs_s2 → enrich_refs_crossref
         ├─ extract_keywords      (parallel branch)
         └─ label_abstracts       (parallel branch)
    → resolve_refs → enrich_stubs → build_cited_by → analyze_graph (PageRank/HITS/communities)

SPARKQ ASSETS (submit cmd → poll status → success/fail)
  embed_papers          (GPU: Qwen3-Embedding-8B)      [definite]
  compute_similarity    (Qdrant-search bound)          [native-vs-sparkq TBD at plan time]
  compute_topics        (UMAP+HDBSCAN)                 [native-vs-sparkq TBD at plan time]
```

- Dependencies are declared by asset inputs; Dagster builds the DAG, runs independent branches (keywords ∥ labeling) concurrently, and on failure rematerializes only the failed asset + downstream.
- **Qdrant is the shared state** between native and sparkq assets. Asset returns are lightweight handles/counts, not data. sparkq jobs on Node 2 reach Qdrant at `192.168.200.12:6333` over the 200GbE; native assets use `localhost:6333`.

### Key components

- **`SparkqJob` resource** — encapsulates submit/poll/log: pre-creates output dirs, submits with `--if-not-running` (idempotent retries) + `--tag`/`--workdir`/`--gpu-mem`/`--eta`, polls `sparkq status <id>` to terminal, maps `completed`→success and `failed_final|cancelled|killed`→fail. On `killed`, inspects `sparkq log <id>` tail before failing (a killed job may have completed useful work).
- **Native stage functions** — extracted from `src/cli/commands/*` into importable `src/core/*` functions (much already lives there); the CLI and Dagster both call them.
- **`dq_flags` payload field** — new Qdrant payload list (e.g. `["missing_refs"]`) used to quarantine-by-tag rows that fail a DQ check (not deleted).

## 3. Data-Quality asset-checks

`@asset_check` runs after its asset materializes, returning pass / warn / fail. Severity: **ERROR** halts the downstream branch; **WARN** alerts but continues. Policy: **block + flag** — ERROR halts downstream and tags offending rows with `dq_flags`; WARN continues.

| # | Check (asset) | Sev | Asserts | Catches |
|---|---------------|-----|---------|---------|
| 1 | `new_paper_count_sane` (collect) | WARN | New count within rolling band; flag 0 or >3× baseline | Surge detection (2026-06-03: 5,691 = 3.6× baseline, 94% OpenReview) |
| 2 | `source_not_silently_zero` (collect) | WARN | No source returns 0 across an N-run window | A collector breaking quietly (pattern drift) |
| 3 | `doi_papers_have_refs` (enrich_refs) | ERROR | Of new papers **with a DOI**, ≥X% got `referenced_works` | Real ref gaps, without false-alarming on DOI-less OpenReview |
| 4 | `abstract_coverage` (enrich_abstracts) | WARN | New papers with abstracts ≥ threshold | Abstract-source regressions |
| 5 | `no_dangling_graph_nodes` (build_cited_by) | WARN→ERROR | Dangling-target fraction ≤ threshold (2026-06-03: 370/424K ≈ 0.09%) | Dangling-node condition (today's bug #3), trended over time |
| 6 | `embedding_coverage_complete` (embed_papers) | ERROR | 100% of new non-stub papers have a dense vector | Silent embed skips → search gaps |
| 7 | `graph_metrics_stored` (analyze_graph) | ERROR | metrics stored for ≈ node count (within dangling tol.) | "ran but stored nothing" (the `--store` without `--all` case) |
| 8 | `cluster_coverage` (compute_topics) | WARN | Embedded papers got `cluster_id`; noise fraction in band | UMAP/HDBSCAN degenerating |
| 9 | `real_papers_have_titles` (collect/enrich) | WARN | Non-stub papers have non-null titles | Surfaces the data condition behind today's bug #2 |

**Scope note:** asset-checks catch *data* problems. The two *code* bugs from 2026-06-03 are handled by construction: the command-name typo class vanishes under native porting (no command string to mistype), and the `None[:60]` crash class is covered by unit tests on the ported functions (null-title fixture). Check #9 keeps the triggering data condition visible.

## 4. Error handling & resume

- **Per-asset `RetryPolicy`** with exponential backoff for transient failures (OpenAlex 429, Qdrant connection-reset, network); mirrors current CLI retry behavior, now declarative.
- **Resume-from-failed is default** — rematerialize the failed asset + downstream from the UI. Retires the dated `run_incremental_resume_*.sh` pattern.
- **sparkq assets** — `--if-not-running` idempotent retries; on `killed`, inspect `sparkq log` tail before failing; RetryPolicy can resubmit.
- **DQ ERROR failure** blocks downstream; the run shows which check failed.

## 5. Scheduling & partitions

- **`DailyPartitionsDefinition`** keyed by date → each day's incremental is a partition; enables backfills and per-day surge attribution.
- Two schedules (quarterly tier removed — topics moved to weekly):
  - **Daily (Mon–Sat)** → core assets `collect_papers … embed_papers`
  - **Weekly (Sun)** → + `compute_similarity`, `analyze_graph`, `compute_topics`
- **Run-failure / check-failure sensor** → alert (Slack/email) on ERROR check or asset failure.

## 6. Migration (incremental; bash orchestrator stays as fallback until the final phase)

1. **Stand up Dagster** alongside (Docker: webserver + daemon, **SQLite** run store to start; Postgres only if scaling). No cutover.
2. **Port CPU/IO stages** as native assets → run one full incremental for a known date via Dagster, diff results against a bash run.
3. **Add DQ checks** in *warn-only* first to calibrate thresholds, then flip search-critical checks (#3, #6, #7) to ERROR + flagging.
4. **Route GPU assets** (embed/similarity/topics) through the `sparkq` resource.
5. **Enable schedules**, retire cron + bash orchestrator + dated resume scripts.

Phases 1–2 deliver observability + DQ value before any GPU/sparkq work.

## 7. Testing

- Unit tests on ported stage functions (extend `tests/`), incl. the null-title fixture from today's bug #2.
- Asset-check tests with fixtures: dangling-node, zero-collection, DOI-paper-missing-refs.
- A **smoke partition** (small `--limit`) before full runs (per sparkq lessons: smoke-test first, pre-create output dirs).

## 8. Deferred decisions (resolve in the implementation plan)

- **GPU need for `compute_similarity` / `compute_topics`** — similarity is Qdrant-search-bound (likely native); topics' UMAP could be CPU or cuML-GPU. Decides native-vs-sparkq for those two. `embed_papers` is unambiguously sparkq/GPU.
- **Run store**: SQLite (single-box default) vs Postgres (if/when scaling).
- **Alert channel** for the failure sensor (Slack vs email).
