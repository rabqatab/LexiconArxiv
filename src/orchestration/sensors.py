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
