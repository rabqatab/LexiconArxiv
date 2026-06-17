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
