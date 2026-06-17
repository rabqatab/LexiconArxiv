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
