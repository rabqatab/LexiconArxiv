"""Checkpoint mixin for enrichers and processors.

Provides reusable checkpoint loading/saving functionality for any class
that needs to track progress across restarts.
"""

import json
import logging
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

# Default checkpoint directory
DEFAULT_CHECKPOINT_DIR = Path("data/core/checkpoints")

# Type variable for progress dataclasses
T = TypeVar("T")


class CheckpointMixin:
    """Mixin providing checkpoint save/load functionality.

    Classes using this mixin should define:
    - checkpoint_dir: Path - directory for checkpoint files
    - A method _get_checkpoint_file() -> Path that returns the checkpoint file path
    - A Progress dataclass type for the progress tracking

    Example usage:
        class MyEnricher(CheckpointMixin):
            def __init__(self, checkpoint_dir: Path | str | None = None):
                self.checkpoint_dir = Path(checkpoint_dir or DEFAULT_CHECKPOINT_DIR)

            def _get_checkpoint_file(self) -> Path:
                return self.checkpoint_dir / "my_enrichment.json"

            def run(self):
                progress = self._load_checkpoint(MyProgress)
                # ... do work ...
                self._save_checkpoint(progress)
    """

    checkpoint_dir: Path

    def _load_checkpoint(self, progress_class: type[T], **extra_fields) -> T:
        """Load checkpoint from file.

        Args:
            progress_class: The dataclass type to instantiate.
            **extra_fields: Additional fields to update on loaded progress.

        Returns:
            Loaded progress or new instance if no checkpoint exists.
        """
        checkpoint_file = self._get_checkpoint_file()

        if checkpoint_file.exists():
            try:
                with open(checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Handle processed_point_ids conversion from list to set
                if "processed_point_ids" in data and isinstance(
                    data["processed_point_ids"], list
                ):
                    data["processed_point_ids"] = set(data["processed_point_ids"])

                # Get valid field names from the dataclass
                valid_fields = {f.name for f in fields(progress_class)}

                # Filter data to only valid fields
                filtered_data = {k: v for k, v in data.items() if k in valid_fields}

                progress = progress_class(**filtered_data)
                logger.info(
                    f"Loaded checkpoint from {checkpoint_file}: "
                    f"{progress.processed}/{progress.total_to_process} processed"
                )
                return progress

            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning(f"Failed to load checkpoint {checkpoint_file}: {e}")

        # Return new progress instance
        return progress_class(**extra_fields)

    def _save_checkpoint(self, progress: Any) -> None:
        """Save checkpoint to file.

        Args:
            progress: Progress dataclass instance to save.
        """
        if not is_dataclass(progress):
            raise TypeError(f"progress must be a dataclass, got {type(progress)}")

        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_file = self._get_checkpoint_file()

        data = asdict(progress)

        # Convert set to list for JSON serialization
        if "processed_point_ids" in data and isinstance(
            data["processed_point_ids"], set
        ):
            data["processed_point_ids"] = list(data["processed_point_ids"])

        # Update last_updated timestamp
        data["last_updated"] = datetime.now(timezone.utc).isoformat()

        with open(checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.debug(f"Saved checkpoint to {checkpoint_file}")

    def _get_checkpoint_file(self) -> Path:
        """Get the checkpoint file path.

        Override this method to customize the checkpoint file location.

        Returns:
            Path to the checkpoint file.
        """
        raise NotImplementedError(
            "Subclasses must implement _get_checkpoint_file() to return the checkpoint file path"
        )

    def clear_checkpoint(self) -> bool:
        """Clear the checkpoint file.

        Returns:
            True if checkpoint was cleared, False if it didn't exist.
        """
        checkpoint_file = self._get_checkpoint_file()
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            logger.info(f"Cleared checkpoint: {checkpoint_file}")
            return True
        return False
