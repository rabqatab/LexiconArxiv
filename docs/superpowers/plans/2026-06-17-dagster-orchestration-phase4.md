# Dagster Orchestration — Phase 4 (Jobs, Schedules, Failure Sensor) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Define the Dagster scheduling machinery — a daily **core** asset job, a weekly **maintenance** asset job, two schedules, and a run-failure sensor — so the full pipeline *can* run under Dagster on a cron. The machinery is installed **dormant** (`default_status=STOPPED`); the production cutover (enabling schedules, persistent daemon, retiring the bash orchestrator) is a separate, gated manual runbook (§ Cutover), NOT executed by this plan.

**Architecture:** `define_asset_job` with `AssetSelection.assets(...)` builds `core_job` (collect→…→embed) and `maintenance_job` (similarity/graph/topics). `ScheduleDefinition`s (STOPPED) target those jobs on daily/weekly crons. A `@run_failure_sensor` (STOPPED) logs failures (incl. ERROR asset-check failures, which fail the run). All registered via `Definitions(jobs=, schedules=, sensors=)`. **No asset code changes; no production cutover; bash stays live.**

**Tech Stack:** Python 3.12, uv, Dagster 1.13.9 (`define_asset_job`, `AssetSelection`, `ScheduleDefinition`, `DefaultScheduleStatus`, `run_failure_sensor`, `DefaultSensorStatus`). Tests: `uv run --extra dev pytest` + `dagster definitions validate`.

**Scope note:** Final phase of the migration (spec §5/§6 phase 5). Builds on Phases 1–3 (merged: 13 assets + 7 warn-only DQ checks). **Deliberately deferred:** daily partitions (DailyPartitionsDefinition — a separate asset-signature change; jobs/schedules work without it), the Slack/email alert channel (spec §8 — sensor logs for now), and **retiring the bash orchestrator** (gated on a proven full Dagster production run — see § Cutover). Spec: `docs/superpowers/specs/2026-06-03-dagster-orchestration-design.md` §5.

---

## Conventions (every task)
- Test command: `uv run --extra dev pytest <args>` (pytest in `dev` extra).
- TDD where there's logic; for pure wiring, the gate is `dagster definitions validate`.
- Commits: `git commit --author="rabqatab <minhan.nick.cho@gmail.com>" -m "..."`. NEVER add `Co-Authored-By`/"Generated with Claude Code". Verify `git log -1 --format="%B" | grep -i co-authored` empty.

## Verified facts (2026-06-17 grounding, dagster 1.13.9)
- `from dagster import define_asset_job, AssetSelection, ScheduleDefinition, DefaultScheduleStatus, run_failure_sensor, RunFailureSensorContext, DefaultSensorStatus, Definitions`.
- `define_asset_job(name, selection=AssetSelection.assets(*names))` → `UnresolvedAssetJobDefinition`. `AssetSelection.assets(*names)` auto-includes asset-checks targeting those assets. (Do NOT use deprecated `AssetSelection.keys` or `define_asset_job(partitions_def=...)`.)
- `ScheduleDefinition(name=, cron_schedule=, job=<asset job>, execution_timezone=, default_status=DefaultScheduleStatus.STOPPED|RUNNING)`. STOPPED is default (dormant until manually started).
- `@run_failure_sensor(name=, monitored_jobs=[...], default_status=DefaultSensorStatus.STOPPED)` → fn(context: RunFailureSensorContext). `context.dagster_run` (run_id, job_name, tags), `context.get_step_failure_events()` (step errors). ERROR-severity asset-check failures fail the run → caught here. No dedicated asset-check sensor in 1.13.9.
- Register: `Definitions(assets=, asset_checks=, jobs=[...], schedules=[...], sensors=[...])`.
- `dagster dev` runs webserver + daemon (local); production needs a persistent `dagster-daemon` + `DAGSTER_HOME`/`dagster.yaml`. None exist in the repo yet.
- Core asset names: collect_papers, enrich_abstracts, enrich_refs_s2, enrich_refs_crossref, extract_keywords, label_abstracts, resolve_refs, enrich_stubs, build_cited_by, embed_papers. Maintenance: compute_similarity, analyze_graph, compute_topics.

---

## File Structure
- Create `src/orchestration/jobs.py` — `core_job`, `maintenance_job` + the name lists
- Create `src/orchestration/schedules.py` — `daily_core_schedule`, `weekly_maintenance_schedule` (STOPPED)
- Create `src/orchestration/sensors.py` — `run_failure_alert_sensor` (STOPPED)
- Modify `src/orchestration/definitions.py` — register `jobs=`, `schedules=`, `sensors=`
- Create `tests/orchestration/test_schedules.py` — assert jobs/selections/schedules/sensor exist & are correct
- Create `docs/runbooks/dagster-cutover.md` — the gated production-cutover runbook

---

## Task 1: Core & maintenance asset jobs

**Files:** Create `src/orchestration/jobs.py`; Test: `tests/orchestration/test_schedules.py`.

- [ ] **Step 1: Failing test.** Create `tests/orchestration/test_schedules.py`:
```python
from src.orchestration.jobs import core_job, maintenance_job, CORE_ASSETS, MAINTENANCE_ASSETS


def test_job_asset_lists_partition_the_dag():
    # 10 core + 3 maintenance = the 13 assets, no overlap
    assert len(CORE_ASSETS) == 10
    assert set(MAINTENANCE_ASSETS) == {"compute_similarity", "analyze_graph", "compute_topics"}
    assert set(CORE_ASSETS).isdisjoint(MAINTENANCE_ASSETS)
    assert len(set(CORE_ASSETS) | set(MAINTENANCE_ASSETS)) == 13


def test_jobs_have_names():
    assert core_job.name == "core_pipeline_job"
    assert maintenance_job.name == "maintenance_pipeline_job"
```

- [ ] **Step 2: Run, confirm fail** (`ModuleNotFoundError: src.orchestration.jobs`).

- [ ] **Step 3: Implement `src/orchestration/jobs.py`:**
```python
"""Dagster asset jobs: daily core pipeline + weekly maintenance."""

from dagster import AssetSelection, define_asset_job

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
```

- [ ] **Step 4: Run, confirm pass.** **Step 5: Commit** (`feat(orchestration): core + maintenance asset jobs`).

---

## Task 2: Schedules (dormant) + run-failure sensor (dormant)

**Files:** Create `src/orchestration/schedules.py`, `src/orchestration/sensors.py`; Test: append to `tests/orchestration/test_schedules.py`.

- [ ] **Step 1: Failing test.** Append:
```python
def test_schedules_are_stopped_with_expected_crons():
    from dagster import DefaultScheduleStatus
    from src.orchestration.schedules import daily_core_schedule, weekly_maintenance_schedule
    assert daily_core_schedule.cron_schedule == "0 2 * * *"
    assert weekly_maintenance_schedule.cron_schedule == "0 4 * * 0"
    # Dormant until manual cutover
    assert daily_core_schedule.default_status == DefaultScheduleStatus.STOPPED
    assert weekly_maintenance_schedule.default_status == DefaultScheduleStatus.STOPPED


def test_failure_sensor_is_stopped():
    from dagster import DefaultSensorStatus
    from src.orchestration.sensors import run_failure_alert_sensor
    assert run_failure_alert_sensor.default_status == DefaultSensorStatus.STOPPED
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement `src/orchestration/schedules.py`:**
```python
"""Dagster schedules (dormant: default_status=STOPPED until the production cutover)."""

from dagster import DefaultScheduleStatus, ScheduleDefinition

from src.orchestration.jobs import core_job, maintenance_job

_TZ = "Asia/Seoul"

# Daily (Mon–Sun) 02:00 — core pipeline with its 3-day rolling lookback.
daily_core_schedule = ScheduleDefinition(
    name="daily_core_schedule",
    cron_schedule="0 2 * * *",
    job=core_job,
    execution_timezone=_TZ,
    default_status=DefaultScheduleStatus.STOPPED,
)

# Weekly Sunday 04:00 — maintenance analytics, after Sunday's core run.
weekly_maintenance_schedule = ScheduleDefinition(
    name="weekly_maintenance_schedule",
    cron_schedule="0 4 * * 0",
    job=maintenance_job,
    execution_timezone=_TZ,
    default_status=DefaultScheduleStatus.STOPPED,
)
```

Create `src/orchestration/sensors.py`:
```python
"""Run-failure sensor (dormant). Logs failures incl. ERROR asset-check failures.

Alert-channel wiring (Slack/email) is deferred (spec §8); this logs for now.
"""

from dagster import DefaultSensorStatus, RunFailureSensorContext, run_failure_sensor

from src.orchestration.jobs import core_job, maintenance_job


@run_failure_sensor(
    name="run_failure_alert_sensor",
    monitored_jobs=[core_job, maintenance_job],
    default_status=DefaultSensorStatus.STOPPED,
)
def run_failure_alert_sensor(context: RunFailureSensorContext) -> None:
    run = context.dagster_run
    steps = context.get_step_failure_events()
    failed_steps = ", ".join(e.step_key or "?" for e in steps) or "(run-level)"
    context.log.error(
        f"[DQ/PIPELINE ALERT] run {run.run_id} of '{run.job_name}' FAILED. "
        f"Failed steps: {failed_steps}. Tags: {dict(run.tags)}"
    )
    # TODO(spec §8): forward to Slack/email here once the alert channel is chosen.
```

- [ ] **Step 4: Run, confirm pass.** **Step 5: Commit** (`feat(orchestration): dormant daily/weekly schedules + run-failure sensor`).

---

## Task 3: Register in Definitions + validate

**Files:** Modify `src/orchestration/definitions.py`; Test: validate + suite.

- [ ] **Step 1: Update `definitions.py`** — add imports and the new kwargs (keep existing `assets=`, `asset_checks=`):
```python
from src.orchestration.jobs import core_job, maintenance_job
from src.orchestration.schedules import daily_core_schedule, weekly_maintenance_schedule
from src.orchestration.sensors import run_failure_alert_sensor

defs = Definitions(
    assets=[...],                # unchanged
    asset_checks=ALL_CHECKS,     # unchanged
    jobs=[core_job, maintenance_job],
    schedules=[daily_core_schedule, weekly_maintenance_schedule],
    sensors=[run_failure_alert_sensor],
)
```

- [ ] **Step 2: Validate.**
`uv run dagster definitions validate -m src.orchestration.definitions`
Expected: "Validation successful" — 13 assets, 7 checks, 2 jobs, 2 schedules, 1 sensor all load; the schedule→job and sensor→job references resolve, and the job asset selections resolve to real assets (a wrong asset name fails here).

- [ ] **Step 3: Full suite.**
`uv run --extra dev pytest tests/orchestration tests/core -q` — all pass.

- [ ] **Step 4: Confirm schedules are dormant (safety).**
`uv run dagster definitions validate -m src.orchestration.definitions` already loads them; confirm in code review that BOTH schedules and the sensor are `STOPPED` (no accidental `RUNNING` — that would auto-start production materializations when a daemon runs).

- [ ] **Step 5: Commit** (`feat(orchestration): register jobs/schedules/sensor in Definitions`).

---

## Task 4: Cutover runbook (documentation only — no execution)

**Files:** Create `docs/runbooks/dagster-cutover.md`.

- [ ] **Step 1: Write the runbook** documenting the gated, manual production cutover. It MUST state the precondition and steps without performing them:

```markdown
# Dagster Production Cutover Runbook (GATED — do not run until precondition met)

**Precondition (hard gate):** A full `core_pipeline_job` + `maintenance_pipeline_job`
materialization has completed successfully end-to-end against production Qdrant and
produced results equivalent to `scripts/run_incremental_pipeline.sh` (compare corpus
counts + a `search_papers` hybrid query). Until then, the **bash orchestrator
(`scripts/run_incremental_pipeline.sh` via cron) remains the live pipeline.**

## 1. Persistent Dagster instance
- Set `DAGSTER_HOME=/home/alphabridge/.dagster` (export in the service env / .env).
- Create `$DAGSTER_HOME/dagster.yaml` (SQLite run/event/schedule storage is fine — see spec §8;
  Postgres only if many concurrent runs are needed). This persists schedule/sensor tick state.

## 2. Run the daemon + webserver as services
- `dagster-daemon run` (evaluates schedule + sensor ticks — REQUIRED for firing).
- `dagster-webserver -m src.orchestration.definitions` (UI).
- (Local equivalent: `dagster dev -m src.orchestration.definitions` runs both.)

## 3. Prove one full run (still gated)
- In the UI, materialize `core_pipeline_job` once manually; confirm success + DQ checks (warn-only).
- Then materialize `maintenance_pipeline_job`; confirm analyze_graph/similarity/topics.
- Diff outcomes vs a bash `--dry-run` projection.

## 4. Enable schedules
- Flip `daily_core_schedule` and `weekly_maintenance_schedule` to RUNNING (UI toggle, or change
  `default_status=DefaultScheduleStatus.RUNNING` in `schedules.py` and redeploy).
- Enable `run_failure_alert_sensor`.

## 5. Retire bash (only after ≥1 week of clean Dagster runs)
- Comment out / remove the cron entry for `scripts/run_incremental_pipeline.sh`.
- Keep the bash script in-repo as a fallback for one release cycle, then archive.
- Wire the alert channel (spec §8) into `sensors.py` (Slack/email) before relying on it.

## Rollback
- Set schedules back to STOPPED (or stop the daemon) and re-enable the bash cron.
```

- [ ] **Step 2: Commit** (`docs(runbook): gated Dagster production-cutover runbook`).

---

## Self-Review
- **Spec §5 coverage:** daily core schedule + weekly maintenance schedule (Sunday) over the correct asset subsets; run-failure sensor catching failures incl. ERROR asset-checks. **Deferred (documented):** DailyPartitionsDefinition (separate asset change; jobs/schedules function without it), the Slack/email alert channel (spec §8), and retiring the bash orchestrator (gated runbook — bash stays live until a proven Dagster run).
- **Safety:** all schedules + sensor ship `STOPPED` — installing this plan changes NO runtime behavior (no daemon runs in CI/dev unless `dagster dev` is started, and even then schedules are dormant). The cutover is a separate human-gated runbook. This is the key risk control: Dagster is unproven for full production materialization, so nothing auto-cuts-over.
- **Placeholder scan:** complete code for jobs/schedules/sensor; the runbook is intentionally documentation (no code). Asset-selection names match the 13 real assets.
- **Type consistency:** `define_asset_job(... selection=AssetSelection.assets(*names))` → jobs; `ScheduleDefinition(job=<job>, default_status=STOPPED)`; `@run_failure_sensor(monitored_jobs=[...], default_status=STOPPED)`; registered via `Definitions(jobs=, schedules=, sensors=)`.

## Out of scope → follow-ups
- **Cutover execution** (the runbook) — when the team is ready to make Dagster the live orchestrator.
- **Daily partitions** + `build_schedule_from_partitioned_job` for backfill/history (spec §5) — additive later.
- **Phase 3b** (from Plan 3): `dq_flags` + flip search-critical checks to blocking ERROR; `new_paper_count_sane` + `no_dangling_graph_nodes`.
- **Alert channel** (Slack/email) wiring in `sensors.py` (spec §8).
