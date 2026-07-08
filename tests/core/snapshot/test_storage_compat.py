"""Regression: real QdrantStorage must expose every method the snapshot phase
modules + live_worker call. A latent divergence here means production runs error
out 100% of the way through the work loop without any test catching it (the
phases test against mock_storage; integration tests only exercise the
storage-extension methods directly, not the phase chain end-to-end).

When this test fires, either add the missing method to QdrantStorage or rename
the phase callsite to match real storage's existing API."""

from src.core.storage import QdrantStorage

PHASE_METHODS = (
    # P1
    "get_paper_by_id",
    "iter_all_real_papers_minimal",
    "batch_apply_field_fill",
    # P2
    "iter_stubs_for_resolution",
    "batch_promote_stubs",
    "ensure_identifier_indices",  # perf-critical: without these, P2 full-scans on every promotion
    # P3
    "build_referenced_openalex_id_set",
    "build_identifier_index_for_dedup",
    "batch_inject_papers",
    # P4
    "build_openalex_id_to_point_id_map",
    "batch_extend_external_cited_by",
)


def test_real_storage_has_every_method_phases_call():
    missing = [m for m in PHASE_METHODS if not hasattr(QdrantStorage, m)]
    assert not missing, (
        f"snapshot phase modules call methods that don't exist on real "
        f"QdrantStorage: {missing}. Add them to src/core/storage/base.py or "
        f"rename the phase callsite to match real storage's existing API."
    )
