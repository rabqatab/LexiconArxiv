from src.core.snapshot.stats import PhaseSummary


def test_summary_to_log_line():
    s = PhaseSummary(phase="p1", scanned=100, matched=42, applied=42, duration_s=12.3)
    line = s.to_log_line()
    assert "p1" in line and "scanned=100" in line and "matched=42" in line


def test_summary_extra_appears_in_log():
    s = PhaseSummary(phase="p3", extra={"anchor_inject": 5, "concept_inject": 9})
    line = s.to_log_line()
    assert "anchor_inject=5" in line and "concept_inject=9" in line


def test_dagster_metadata_is_flat():
    s = PhaseSummary(phase="p1", scanned=1, matched=1, applied=1, extra={"foo": "bar"})
    md = s.to_dagster_metadata()
    assert md["scanned"] == 1
    assert md["foo"] == "bar"
