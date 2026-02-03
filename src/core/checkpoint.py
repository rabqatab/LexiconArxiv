"""Checkpoint management for resumable collection.

Persists collection state to JSON files for resume after interruption.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default checkpoint directory
DEFAULT_CHECKPOINT_DIR = Path("data/core/checkpoints")


@dataclass
class VenueProgress:
    """Progress state for a single venue."""

    venue_name: str
    source_id: str | None = None
    cursor: str | None = None  # OpenAlex pagination cursor
    papers_collected: int = 0
    last_updated: str | None = None
    is_complete: bool = False
    error: str | None = None

    def mark_updated(self) -> None:
        """Update the last_updated timestamp."""
        self.last_updated = datetime.now(timezone.utc).isoformat()


@dataclass
class CollectionCheckpoint:
    """Full checkpoint state for collection run."""

    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_updated: str | None = None
    since_year: int = 2020
    venues: dict[str, VenueProgress] = field(default_factory=dict)
    total_papers: int = 0
    total_api_calls: int = 0

    def get_venue_progress(self, venue_name: str) -> VenueProgress | None:
        """Get progress for a specific venue."""
        return self.venues.get(venue_name.lower())

    def set_venue_progress(self, progress: VenueProgress) -> None:
        """Set progress for a venue."""
        self.venues[progress.venue_name.lower()] = progress
        self.last_updated = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "started_at": self.started_at,
            "last_updated": self.last_updated,
            "since_year": self.since_year,
            "total_papers": self.total_papers,
            "total_api_calls": self.total_api_calls,
            "venues": {k: asdict(v) for k, v in self.venues.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CollectionCheckpoint":
        """Create from dictionary."""
        checkpoint = cls(
            started_at=data.get("started_at", datetime.now(timezone.utc).isoformat()),
            last_updated=data.get("last_updated"),
            since_year=data.get("since_year", 2020),
            total_papers=data.get("total_papers", 0),
            total_api_calls=data.get("total_api_calls", 0),
        )

        venues_data = data.get("venues", {})
        for venue_name, venue_data in venues_data.items():
            checkpoint.venues[venue_name] = VenueProgress(**venue_data)

        return checkpoint


class CheckpointManager:
    """Manages checkpoint persistence for collection runs."""

    def __init__(
        self,
        checkpoint_dir: Path | str | None = None,
        checkpoint_name: str = "collection",
    ):
        """Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory to store checkpoints.
            checkpoint_name: Base name for checkpoint file.
        """
        self.checkpoint_dir = Path(checkpoint_dir or DEFAULT_CHECKPOINT_DIR)
        self.checkpoint_name = checkpoint_name
        self.checkpoint_file = self.checkpoint_dir / f"{checkpoint_name}.json"

        # Ensure directory exists
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> CollectionCheckpoint:
        """Load checkpoint from file, or create new if not exists.

        Returns:
            The loaded or new checkpoint.
        """
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file) as f:
                    data = json.load(f)
                checkpoint = CollectionCheckpoint.from_dict(data)
                logger.info(
                    f"Loaded checkpoint: {checkpoint.total_papers} papers, "
                    f"{len(checkpoint.venues)} venues"
                )
                return checkpoint
            except Exception as e:
                logger.warning(f"Failed to load checkpoint, creating new: {e}")
                return CollectionCheckpoint()
        else:
            logger.info("No existing checkpoint, starting fresh")
            return CollectionCheckpoint()

    def save(self, checkpoint: CollectionCheckpoint) -> None:
        """Save checkpoint to file.

        Args:
            checkpoint: The checkpoint to save.
        """
        try:
            with open(self.checkpoint_file, "w") as f:
                json.dump(checkpoint.to_dict(), f, indent=2)
            logger.debug(f"Saved checkpoint to {self.checkpoint_file}")
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
            raise

    def update_venue(
        self,
        checkpoint: CollectionCheckpoint,
        venue_name: str,
        source_id: str | None = None,
        cursor: str | None = None,
        papers_collected: int | None = None,
        is_complete: bool = False,
        error: str | None = None,
    ) -> None:
        """Update progress for a venue and save.

        Args:
            checkpoint: The checkpoint to update.
            venue_name: Name of the venue.
            source_id: OpenAlex Source ID.
            cursor: Current pagination cursor.
            papers_collected: Total papers collected for this venue.
            is_complete: Whether collection is complete.
            error: Error message if collection failed.
        """
        progress = checkpoint.get_venue_progress(venue_name) or VenueProgress(
            venue_name=venue_name
        )

        if source_id is not None:
            progress.source_id = source_id
        if cursor is not None:
            progress.cursor = cursor
        if papers_collected is not None:
            progress.papers_collected = papers_collected
        progress.is_complete = is_complete
        progress.error = error
        progress.mark_updated()

        checkpoint.set_venue_progress(progress)
        self.save(checkpoint)

    def clear(self) -> None:
        """Remove the checkpoint file."""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
            logger.info(f"Cleared checkpoint: {self.checkpoint_file}")

    def get_resume_cursor(self, checkpoint: CollectionCheckpoint, venue_name: str) -> str | None:
        """Get the cursor to resume from for a venue.

        Args:
            checkpoint: The checkpoint to check.
            venue_name: Name of the venue.

        Returns:
            The cursor to resume from, or None to start fresh.
        """
        progress = checkpoint.get_venue_progress(venue_name)
        if progress and not progress.is_complete:
            return progress.cursor
        return None

    def is_venue_complete(self, checkpoint: CollectionCheckpoint, venue_name: str) -> bool:
        """Check if a venue has been fully collected.

        Args:
            checkpoint: The checkpoint to check.
            venue_name: Name of the venue.

        Returns:
            True if collection is complete for this venue.
        """
        progress = checkpoint.get_venue_progress(venue_name)
        return progress is not None and progress.is_complete
