"""Per-phase summary dataclass shared by all snapshot phases."""
from dataclasses import asdict, dataclass, field


@dataclass
class PhaseSummary:
    phase: str
    scanned: int = 0
    matched: int = 0
    applied: int = 0
    worker_errors: int = 0
    failed_batches: int = 0
    quarantined: int = 0
    duration_s: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_log_line(self) -> str:
        core = (
            f"{self.phase} Summary: scanned={self.scanned} matched={self.matched} "
            f"applied={self.applied} worker_errors={self.worker_errors} "
            f"failed_batches={self.failed_batches} quarantined={self.quarantined} "
            f"duration_s={self.duration_s:.1f}"
        )
        extra = " ".join(f"{k}={v}" for k, v in self.extra.items())
        return f"{core} {extra}".strip()

    def to_dagster_metadata(self) -> dict:
        d = asdict(self)
        d.pop("phase")
        extra = d.pop("extra")
        return {**d, **extra}
