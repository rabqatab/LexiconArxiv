"""Dagster schedules (dormant: default_status=STOPPED until the production cutover)."""

from dagster import DefaultScheduleStatus, ScheduleDefinition

from src.orchestration.jobs import core_job, maintenance_job, snapshot_live_delta_job

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

# Daily 05:00 KST — live-mode delta. STOPPED until operator explicitly enables
# after bootstrap is stable (spec §3).
daily_snapshot_live_schedule = ScheduleDefinition(
    name="daily_snapshot_live_schedule",
    cron_schedule="0 5 * * *",
    job=snapshot_live_delta_job,
    execution_timezone=_TZ,
    default_status=DefaultScheduleStatus.STOPPED,
)
