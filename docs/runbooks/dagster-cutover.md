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
