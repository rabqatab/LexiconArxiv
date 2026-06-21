"""In-memory storage stub for L1/L2 snapshot tests."""
import json
from pathlib import Path

import pytest


class _MockStorage:
    """In-memory dict-backed storage stub.

    Methods cover every storage call the snapshot phases make. New methods
    are added here as storage extensions land in Plan 1 Tasks 10-20.
    """

    def __init__(self) -> None:
        self._payloads: dict[str, dict] = {}
        self._vectors: set[str] = set()

    # core
    def set_payload(self, point_id: str, payload: dict) -> None:
        existing = self._payloads.get(point_id, {})
        existing.update(payload)
        self._payloads[point_id] = existing

    def get_payload(self, point_id: str) -> dict | None:
        return self._payloads.get(point_id)

    def scroll_payloads(self) -> list[tuple[str, dict]]:
        return list(self._payloads.items())

    def seed_from_json(self, path: Path) -> None:
        for entry in json.loads(path.read_text()):
            self._payloads[entry["point_id"]] = dict(entry["payload"])

    def has_vector(self, point_id: str) -> bool:
        return point_id in self._vectors

    def vector_set(self, point_id: str) -> None:
        self._vectors.add(point_id)

    def count_with_filter(
        self,
        *,
        must_not_is_stub: bool = False,
        must_is_stub: bool = False,
        missing_field: str | None = None,
    ) -> int:
        n = 0
        for _, p in self._payloads.items():
            if must_not_is_stub and p.get("is_stub") is True:
                continue
            if must_is_stub and p.get("is_stub") is not True:
                continue
            if missing_field is not None and p.get(missing_field):
                continue
            n += 1
        return n


@pytest.fixture
def mock_storage() -> _MockStorage:
    return _MockStorage()
