# Snapshot Utilization Tests

Layered model — match the design spec `docs/superpowers/specs/2026-06-21-snapshot-utilization-design.md` §8.

| Layer | Range | Marker | When |
|---|---|---|---|
| L1 unit | one pure function, mocked storage | (none) | every commit |
| L2 integration | one phase end-to-end against in-memory storage stub + tiny fixture | (none) | every commit |
| L3 live-smoke | real Qdrant + real `~30k`-work `.gz` | `snapshot_live` | manual: `pytest -m snapshot_live` |

Fixtures live in `fixtures/`. See `fixtures/README.md` for the scenario catalogue.

The in-memory storage stub is `mock_storage` in `conftest.py`. Extend it whenever a phase needs a method that does not yet exist — add the method, write a unit test for it, then use it in the phase test.

CI default: `uv run --extra dev pytest -m "not snapshot_live"`.
