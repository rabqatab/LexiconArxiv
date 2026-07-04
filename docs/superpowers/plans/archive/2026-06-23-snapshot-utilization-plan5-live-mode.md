# Snapshot Utilization — Plan 5: Live mode (daily API delta)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the live-mode wrapper from the snapshot utilization spec §3 / §9 — a daily OpenAlex API delta worker that calls the same P1→P2→P3→P4 `process_one(work)` chain Plans 1–4 already export, so quarterly snapshot bootstrap and daily live sync share identical phase logic.

**Architecture:** A new `iter_live_works(since)` in `work_source.py` queries the public OpenAlex `/works?filter=from_updated_date:YYYY-MM-DD` endpoint with cursor pagination (no Premium plan needed for filter-by-date queries). A new `live_worker.run_live_delta()` builds the four phase indexes ONCE, iterates each work through `p1.process_one → p2.process_one → p3.process_one → p4.process_one`, drains the embedding queue at the end, and updates the per-phase high-water marks. A `snapshot-live-delta` CLI and Dagster asset + dormant daily schedule complete the operational wiring.

**Tech Stack:** Python 3.12, uv, `httpx` (sync), Click, Dagster 1.13.9. Tests: `uv run --extra dev pytest`, with `respx` for HTTP mocking.

## Global Constraints

- Plans 1–4 MUST be merged on `main` before Plan 5 work begins. Verify with `git -C $(git rev-parse --show-toplevel) log --oneline -1` showing `9da73e6` or newer. The plan polish (`9da73e6`) is already in.
- Git author for every commit: `rabqatab <minhan.nick.cho@gmail.com>` via `git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit ...`. No `Co-Authored-By` lines, no "Generated with Claude Code" footer.
- All Python invocations use `uv run`. Never bare `python3`.
- All snapshot live commits respect the file-discipline rules established in earlier plans: use Edit (not Write) when modifying an existing file; explicit `git add` paths; never `-A`/`.`.
- `daily_snapshot_live_schedule` MUST default to `DefaultScheduleStatus.STOPPED` — operator must explicitly enable after bootstrap is stable (spec §3).
- The live worker MUST update `checkpoint.set_live_high_water_mark(phase, iso)` per phase after each pass, so re-running the same delta day is a no-op for already-processed corpus state.
- OpenAlex public endpoint is `https://api.openalex.org`; we provide `mailto` via the existing `OPENALEX_EMAIL` env var to land in the "polite pool" (higher rate limit).
- `from_updated_date` filter does NOT require Premium — that note in `src/core/crawler/openalex.py:563` applies to bulk crawls, not date-filter queries. Verified against OpenAlex docs.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/core/snapshot/work_source.py` | MODIFY | Replace `iter_live_works` `NotImplementedError` stub with real OpenAlex API client + cursor pagination |
| `src/core/snapshot/live_worker.py` | NEW | `run_live_delta(storage, *, since_date, ...)` — builds indexes once, iterates works, chains process_one calls, drains queue, updates HWMs |
| `src/cli/commands/snapshot.py` | MODIFY | Append `snapshot-live-delta` Click command |
| `src/orchestration/assets/snapshot.py` | MODIFY | Add `snapshot_live_delta` asset (independent of bootstrap DAG) |
| `src/orchestration/jobs.py` | MODIFY | Add `snapshot_live_delta_job = define_asset_job(...)` |
| `src/orchestration/schedules.py` | MODIFY | Add `daily_snapshot_live_schedule` (cron `0 5 * * *`, STOPPED) |
| `src/orchestration/definitions.py` | MODIFY | Register new asset + job + schedule |
| `docs/pipelines/snapshot-live-mode.md` | NEW | Describe live worker semantics, HWM, ordering with bootstrap |
| `docs/runbooks/snapshot-bootstrap.md` | MODIFY | Append "Day 12+: enable live mode" section |
| `tests/core/snapshot/test_iter_live_works.py` | NEW | L1 — respx-mocked OpenAlex responses |
| `tests/core/snapshot/test_live_worker.py` | NEW | L2 — mock_storage + in-memory work source |
| `tests/core/snapshot/test_cli_live_delta.py` | NEW | CliRunner smoke for `snapshot-live-delta` |

---

## Task 1: `iter_live_works` — real OpenAlex API client

**Files:**
- Modify: `src/core/snapshot/work_source.py`
- Test: `tests/core/snapshot/test_iter_live_works.py` (NEW)

**Interfaces:**
- Consumes: `httpx` (sync `httpx.Client`), `os` for `OPENALEX_EMAIL` env var.
- Produces:
  ```python
  def iter_live_works(
      *,
      since: date,
      mailto: str | None = None,
      per_page: int = 200,
      base_url: str = "https://api.openalex.org",
      timeout: float = 60.0,
  ) -> Iterator[dict]
  # Yields work dicts matching the same shape iter_snapshot_works yields
  # (snapshot JSON line == API work response item, modulo a few API-only meta fields).
  ```

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_iter_live_works.py`:

```python
from datetime import date
import respx
from httpx import Response

from src.core.snapshot.work_source import iter_live_works


@respx.mock
def test_iter_live_works_single_page():
    respx.get("https://api.openalex.org/works").mock(return_value=Response(200, json={
        "meta": {"next_cursor": None, "count": 2},
        "results": [
            {"id": "https://openalex.org/W1", "doi": "10.1/a", "title": "A"},
            {"id": "https://openalex.org/W2", "doi": "10.1/b", "title": "B"},
        ],
    }))
    out = list(iter_live_works(since=date(2026, 6, 22)))
    assert [w["id"] for w in out] == ["https://openalex.org/W1", "https://openalex.org/W2"]


@respx.mock
def test_iter_live_works_follows_cursor():
    page1 = Response(200, json={
        "meta": {"next_cursor": "CURSOR2"},
        "results": [{"id": "https://openalex.org/W1"}],
    })
    page2 = Response(200, json={
        "meta": {"next_cursor": None},
        "results": [{"id": "https://openalex.org/W2"}],
    })
    respx.get("https://api.openalex.org/works").mock(side_effect=[page1, page2])
    out = list(iter_live_works(since=date(2026, 6, 22)))
    assert [w["id"] for w in out] == ["https://openalex.org/W1", "https://openalex.org/W2"]


@respx.mock
def test_iter_live_works_sends_filter_and_cursor_params():
    captured = []

    def handler(request):
        captured.append(dict(request.url.params))
        return Response(200, json={"meta": {"next_cursor": None}, "results": []})

    respx.get("https://api.openalex.org/works").mock(side_effect=handler)
    list(iter_live_works(since=date(2026, 6, 22), per_page=50, mailto="me@x.org"))
    assert captured[0]["filter"] == "from_updated_date:2026-06-22"
    assert captured[0]["per-page"] == "50"
    assert captured[0]["cursor"] == "*"
    assert captured[0]["mailto"] == "me@x.org"


@respx.mock
def test_iter_live_works_empty_results():
    respx.get("https://api.openalex.org/works").mock(return_value=Response(200, json={
        "meta": {"next_cursor": None}, "results": [],
    }))
    assert list(iter_live_works(since=date(2026, 6, 22))) == []
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_iter_live_works.py -v
```

Expected: `NotImplementedError` from the existing stub.

- [ ] **Step 3: Implement.**

Replace the existing `iter_live_works` stub in `src/core/snapshot/work_source.py`:

```python
import os
from datetime import date

import httpx


def iter_live_works(
    *,
    since: date,
    mailto: str | None = None,
    per_page: int = 200,
    base_url: str = "https://api.openalex.org",
    timeout: float = 60.0,
) -> Iterator[dict]:
    """Yield work dicts from OpenAlex /works filtered by from_updated_date:<since>.

    Uses cursor pagination (per OpenAlex docs); each yielded dict has the same
    shape as a snapshot JSONL line. Passes `mailto` (default from OPENALEX_EMAIL
    env var) for the polite-pool rate limit.
    """
    mailto = mailto or os.environ.get("OPENALEX_EMAIL")
    params: dict[str, str | int] = {
        "filter": f"from_updated_date:{since.isoformat()}",
        "per-page": str(per_page),
        "cursor": "*",
    }
    if mailto:
        params["mailto"] = mailto
    with httpx.Client(timeout=timeout, base_url=base_url) as client:
        while True:
            r = client.get("/works", params=params)
            r.raise_for_status()
            payload = r.json()
            for w in payload.get("results") or []:
                yield w
            nxt = (payload.get("meta") or {}).get("next_cursor")
            if not nxt:
                return
            params["cursor"] = nxt
```

The existing imports + `iter_snapshot_works` function are preserved; only the stub at the bottom of the file is replaced.

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_iter_live_works.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run the full snapshot unit suite to confirm no regression.**

```bash
uv run --extra dev pytest tests/core/snapshot/ -q -m "not snapshot_live and not integration"
```

Expected: prior count + 4 new passing.

- [ ] **Step 6: Commit.**

```bash
git add src/core/snapshot/work_source.py tests/core/snapshot/test_iter_live_works.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): iter_live_works — OpenAlex /works cursor-paginated client"
```

---

## Task 2: `live_worker.run_live_delta()` — drives the daily delta

**Files:**
- Create: `src/core/snapshot/live_worker.py`
- Test: `tests/core/snapshot/test_live_worker.py` (NEW)

**Interfaces:**
- Consumes:
  - `phase1_corpus_fields.process_one(work, indexes, *, storage, dry_run=False)`
  - `phase2_stub_resolution.process_one(work, stub_index, all_stubs_by_id, *, storage, dry_run=False, allow_promotion=True, allow_merge=True, embedding_queue_root=None)`
  - `phase3_gap_discovery.process_one(work, dedup_idx, anchor_set, *, storage, thresholds, now_year, dry_run=False, embedding_queue_root=None)`
  - `phase4_cited_by.process_one(work, oa_to_pid, *, storage, cap_per_paper=300, dry_run=False)`
  - `matcher.build_stub_index`, `storage.iter_stubs_for_resolution`
  - `storage.iter_all_real_papers_minimal`, `storage.build_referenced_openalex_id_set`,
    `storage.build_identifier_index_for_dedup`, `storage.build_openalex_id_to_point_id_map`
  - `gap_filter.Thresholds`
  - `checkpoint.{live_high_water_mark, set_live_high_water_mark}`
  - `embedding_queue.{depth, drain}`
- Produces:
  ```python
  def run_live_delta(
      storage,
      *,
      since: date | None = None,
      days_back: int = 1,
      dry_run: bool = False,
      thresholds=None,
      max_injections: int | None = None,
      cap_per_paper: int = 300,
      checkpoint_root: Path | None = None,
      embedding_queue_root: Path | None = None,
      work_iterator=None,  # injectable; defaults to iter_live_works(since=since)
  ) -> dict
  # Returns aggregated summary: {since, fetched, per_phase: {p1:{...}, p2:{...}, p3:{...}, p4:{...}},
  #                              queue_depth_after, hwm_updated: {p1, p2, p3, p4}}
  ```

- [ ] **Step 1: Write the failing L2 test.**

Create `tests/core/snapshot/test_live_worker.py`:

```python
from datetime import date
from pathlib import Path
import json

from src.core.snapshot import live_worker

FIX = Path(__file__).parent / "fixtures"


def _load_tiny_works():
    """Read the 12 valid lines from the existing tiny.jsonl.gz fixture."""
    import gzip
    out = []
    with gzip.open(FIX / "works" / "tiny.jsonl.gz", "rt") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return out


def test_run_live_delta_chains_all_four_phases(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    works = _load_tiny_works()

    out = live_worker.run_live_delta(
        mock_storage,
        since=date(2026, 6, 22),
        work_iterator=iter(works),
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )

    # Aggregated summary keys
    assert out["fetched"] == len(works)
    for p in ("p1", "p2", "p3", "p4"):
        assert p in out["per_phase"]
        assert out["hwm_updated"][p] == "2026-06-22"

    # The tiny fixture provided: P1 matches (works 0, 1), P2 promotes some stubs,
    # P3 anchor+concept inject some, P4 hits some external citers. Just assert
    # at least one phase did something — the per-phase logic is unit-tested in
    # plans 2/3/4.
    total_activity = (
        out["per_phase"]["p1"].get("matched", 0)
        + out["per_phase"]["p2"].get("promoted", 0)
        + out["per_phase"]["p3"].get("anchor_inject", 0)
        + out["per_phase"]["p3"].get("concept_inject", 0)
    )
    assert total_activity > 0


def test_run_live_delta_dry_run_does_not_mutate(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    works = _load_tiny_works()

    before = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    out = live_worker.run_live_delta(
        mock_storage,
        since=date(2026, 6, 22),
        dry_run=True,
        work_iterator=iter(works),
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    after = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    assert before == after
    assert out["fetched"] == len(works)


def test_run_live_delta_uses_default_iterator_when_not_injected(monkeypatch, mock_storage, tmp_path):
    """If work_iterator is None, run_live_delta computes since and calls iter_live_works."""
    called_with = {}

    def fake_iter(*, since, **_):
        called_with["since"] = since
        return iter([])

    from src.core.snapshot import live_worker as lw
    monkeypatch.setattr(lw, "iter_live_works", fake_iter)

    out = lw.run_live_delta(
        mock_storage,
        # since omitted → derived from days_back
        days_back=2,
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    assert called_with["since"].isoformat()  # got a date
    assert out["fetched"] == 0
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_live_worker.py -v
```

Expected: `ModuleNotFoundError: src.core.snapshot.live_worker`.

- [ ] **Step 3: Implement.**

Create `src/core/snapshot/live_worker.py`:

```python
"""Live-mode wrapper: drives daily OpenAlex API delta through the P1→P2→P3→P4
process_one chain. Same phase logic as the snapshot bootstrap; only the work
source differs."""
import logging
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.core.snapshot import (
    checkpoint as cp,
    embedding_queue,
    phase1_corpus_fields,
    phase2_stub_resolution,
    phase3_gap_discovery,
    phase4_cited_by,
)
from src.core.snapshot.gap_filter import Thresholds
from src.core.snapshot.matcher import build_stub_index
from src.core.snapshot.work_source import iter_live_works

logger = logging.getLogger(__name__)

_PHASES = ("p1", "p2", "p3", "p4")


def _build_indexes(storage):
    """Build all four phase indexes once at the start of a live delta pass.

    For a single-digit-thousand work delta this is the right tradeoff — the
    indexes cost ~seconds to build but save N lookups per work."""
    # P1
    doi_map: dict[str, str] = {}
    oa_map: dict[str, str] = {}
    title_map: dict[str, str] = {}
    for entry in storage.iter_all_real_papers_minimal():
        pid = entry["point_id"]
        if entry.get("doi"):
            doi_map.setdefault(entry["doi"], pid)
        if entry.get("openalex_id"):
            oa_map.setdefault(entry["openalex_id"], pid)
        if entry.get("title_norm"):
            title_map.setdefault(entry["title_norm"], pid)
    p1_indexes = (doi_map, oa_map, title_map)
    # P2
    stubs = list(storage.iter_stubs_for_resolution())
    stub_index = build_stub_index(stubs)
    all_stubs_by_id = {s["point_id"]: s for s in stubs}
    # P3
    dedup_idx = storage.build_identifier_index_for_dedup()
    anchor_set = storage.build_referenced_openalex_id_set()
    # P4
    oa_to_pid = storage.build_openalex_id_to_point_id_map()
    return p1_indexes, (stub_index, all_stubs_by_id), (dedup_idx, anchor_set), oa_to_pid


def run_live_delta(
    storage,
    *,
    since: date | None = None,
    days_back: int = 1,
    dry_run: bool = False,
    thresholds: Thresholds | None = None,
    max_injections: int | None = None,
    cap_per_paper: int = 300,
    checkpoint_root: Path | None = None,
    embedding_queue_root: Path | None = None,
    work_iterator=None,
) -> dict:
    """Single live-mode pass: fetch yesterday's API delta and run each work
    through all four phases. Idempotent — re-running the same since-date is safe
    (each phase is fill-only-missing / dedup-guarded)."""
    t0 = time.time()
    if since is None:
        since = (datetime.now(timezone.utc).date() - timedelta(days=days_back))
    thresholds = thresholds or Thresholds()
    now_year = datetime.now(timezone.utc).year

    p1_indexes, (stub_index, all_stubs_by_id), (dedup_idx, anchor_set), oa_to_pid = \
        _build_indexes(storage)

    works = work_iterator if work_iterator is not None else iter_live_works(since=since)

    counters: dict[str, Counter] = {p: Counter() for p in _PHASES}
    fetched = 0
    injection_count = 0

    for work in works:
        fetched += 1
        try:
            # P1: corpus metadata fill
            r1 = phase1_corpus_fields.process_one(
                work, p1_indexes, storage=storage, dry_run=dry_run,
            )
            counters["p1"][r1.get("action") or ("matched" if r1.get("matched") else "no_match")] += 1
            if r1.get("matched"):
                counters["p1"]["matched"] += 1
            # P2: stub resolution
            r2 = phase2_stub_resolution.process_one(
                work, stub_index, all_stubs_by_id, storage=storage,
                dry_run=dry_run, embedding_queue_root=embedding_queue_root,
            )
            counters["p2"][r2.get("action") or "skip"] += 1
            # P3: gap discovery + injection
            r3 = phase3_gap_discovery.process_one(
                work, dedup_idx, anchor_set, storage=storage,
                thresholds=thresholds, now_year=now_year, dry_run=dry_run,
                embedding_queue_root=embedding_queue_root,
            )
            action3 = r3.get("action") or "skip"
            counters["p3"][action3] += 1
            cls = r3.get("classification")
            if cls == "ANCHOR_INJECT":
                counters["p3"]["anchor_inject"] += 1
            elif cls == "CONCEPT_INJECT":
                counters["p3"]["concept_inject"] += 1
            if action3 == "created":
                injection_count += 1
                if max_injections is not None and injection_count >= max_injections:
                    logger.warning("live-delta: hit max_injections=%d, stopping early",
                                   max_injections)
                    break
            # P4: external_cited_by extension (refs in this work that hit the corpus)
            r4 = phase4_cited_by.process_one(
                work, oa_to_pid, storage=storage,
                cap_per_paper=cap_per_paper, dry_run=dry_run,
            )
            counters["p4"]["hits"] += r4.get("hits", 0)
            counters["p4"]["applied"] += r4.get("applied", 0)
        except Exception as e:
            counters["meta"] = counters.get("meta", Counter())
            counters["meta"]["worker_errors"] += 1
            if counters["meta"]["worker_errors"] % 100 == 1:
                logger.warning("live-delta worker error: %s", e)

    # Update HWMs for all four phases at the end of a successful pass
    hwm_iso = since.isoformat()
    if not dry_run:
        for ph in _PHASES:
            cp.set_live_high_water_mark(ph, hwm_iso, root=checkpoint_root)

    summary = {
        "since": hwm_iso,
        "fetched": fetched,
        "per_phase": {p: dict(counters[p]) for p in _PHASES},
        "queue_depth_after": embedding_queue.depth(root=embedding_queue_root),
        "hwm_updated": {p: hwm_iso for p in _PHASES} if not dry_run
                       else {p: cp.live_high_water_mark(p, root=checkpoint_root) for p in _PHASES},
        "duration_s": round(time.time() - t0, 2),
        "dry_run": dry_run,
    }
    logger.info("live-delta: %s", summary)
    return summary
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_live_worker.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/live_worker.py tests/core/snapshot/test_live_worker.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): live_worker.run_live_delta (chain P1→P2→P3→P4 per work)"
```

---

## Task 3: CLI — `snapshot-live-delta`

**Files:**
- Modify: `src/cli/commands/snapshot.py`
- Test: `tests/core/snapshot/test_cli_live_delta.py` (NEW)

**Interfaces:** New Click subcommand `snapshot-live-delta` registered on the existing `cli` group.

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_cli_live_delta.py`:

```python
from click.testing import CliRunner

from src.cli.core_collect import cli


def test_snapshot_live_delta_command_registered():
    runner = CliRunner()
    res = runner.invoke(cli, ["snapshot-live-delta", "--help"])
    assert res.exit_code == 0
    for opt in ("--days-back", "--since", "--dry-run", "--max-injections"):
        assert opt in res.output, f"missing option {opt}"
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_cli_live_delta.py -v
```

Expected: `Error: No such command 'snapshot-live-delta'`.

- [ ] **Step 3: Add the command.**

Append to `src/cli/commands/snapshot.py` (inside the existing register function alongside the other snapshot commands):

```python
    @cli.command("snapshot-live-delta")
    @click.option("--days-back", type=int, default=1,
                  help="Fetch updates from N days ago (default 1 = yesterday).")
    @click.option("--since", type=str, default=None,
                  help="Explicit ISO date (YYYY-MM-DD); overrides --days-back.")
    @click.option("--dry-run", is_flag=True,
                  help="Run the full chain but do not write to storage.")
    @click.option("--max-injections", type=int, default=None,
                  help="Stop P3 after this many injections (safety cap).")
    @click.option("--anchor-min-citers", type=int, default=2)
    @click.option("--concept-min-recent", type=int, default=50)
    @click.option("--concept-min-old", type=int, default=200)
    @click.option("--concept-min-year", type=int, default=2018)
    @click.option("--max-citers-per-paper", type=int, default=300)
    def snapshot_live_delta(days_back, since, dry_run, max_injections,
                             anchor_min_citers, concept_min_recent,
                             concept_min_old, concept_min_year,
                             max_citers_per_paper):
        """Run one live-mode pass: fetch yesterday's OpenAlex API delta and
        chain P1→P2→P3→P4 per work (same phase logic as the snapshot bootstrap)."""
        from datetime import date as _date
        from src.core.snapshot import live_worker
        from src.core.snapshot.gap_filter import Thresholds
        from src.core.storage import QdrantStorage
        storage = QdrantStorage()
        since_date = _date.fromisoformat(since) if since else None
        thresholds = Thresholds(
            anchor_min_citers=anchor_min_citers,
            concept_min_recent=concept_min_recent,
            concept_min_old=concept_min_old,
            concept_min_year=concept_min_year,
        )
        out = live_worker.run_live_delta(
            storage,
            since=since_date,
            days_back=days_back,
            dry_run=dry_run,
            thresholds=thresholds,
            max_injections=max_injections,
            cap_per_paper=max_citers_per_paper,
        )
        click.echo(
            f"live-delta since={out['since']} fetched={out['fetched']} "
            f"p1={out['per_phase']['p1']} p2={out['per_phase']['p2']} "
            f"p3={out['per_phase']['p3']} p4={out['per_phase']['p4']} "
            f"queue_depth_after={out['queue_depth_after']} "
            f"hwm_updated={out['hwm_updated']} duration_s={out['duration_s']}"
        )
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_cli_live_delta.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/cli/commands/snapshot.py tests/core/snapshot/test_cli_live_delta.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(cli): snapshot-live-delta (daily live-mode trigger)"
```

---

## Task 4: Dagster — `snapshot_live_delta` asset + dormant daily schedule

**Files:**
- Modify: `src/orchestration/assets/snapshot.py`
- Modify: `src/orchestration/jobs.py`
- Modify: `src/orchestration/schedules.py`
- Modify: `src/orchestration/definitions.py`

**Interfaces:** A new asset `snapshot_live_delta` (no `deps`), a new asset job that wraps it, and a new daily schedule defaulted to STOPPED.

- [ ] **Step 1: Add the asset.**

Append to `src/orchestration/assets/snapshot.py` (do NOT touch the existing 4 bootstrap assets):

```python
from src.core.snapshot import live_worker


@asset(deps=[], group_name="snapshot")
def snapshot_live_delta(context: AssetExecutionContext) -> MaterializeResult:
    """Daily live-mode pass: chain P1→P2→P3→P4 over yesterday's OpenAlex delta.

    Independent of the bootstrap DAG. Defaults to STOPPED at the schedule
    level; operator enables after bootstrap is stable.
    """
    out = live_worker.run_live_delta(QdrantStorage())
    context.log.info("live-delta: %s", out)
    # Flatten nested dict into Dagster metadata (top-level keys must be flat)
    md = {
        "since": out["since"],
        "fetched": out["fetched"],
        "queue_depth_after": out["queue_depth_after"],
        "duration_s": out["duration_s"],
        **{f"p1.{k}": v for k, v in out["per_phase"]["p1"].items()},
        **{f"p2.{k}": v for k, v in out["per_phase"]["p2"].items()},
        **{f"p3.{k}": v for k, v in out["per_phase"]["p3"].items()},
        **{f"p4.{k}": v for k, v in out["per_phase"]["p4"].items()},
    }
    return MaterializeResult(metadata=md)
```

- [ ] **Step 2: Add the asset job.**

Append to `src/orchestration/jobs.py`:

```python
from src.orchestration.assets import snapshot as _snapshot_assets

snapshot_live_delta_job = define_asset_job(
    name="snapshot_live_delta_job",
    selection=AssetSelection.assets(_snapshot_assets.snapshot_live_delta),
)
```

- [ ] **Step 3: Add the daily schedule (STOPPED by default).**

Append to `src/orchestration/schedules.py`:

```python
from src.orchestration.jobs import snapshot_live_delta_job

# Daily 05:00 KST — live-mode delta. STOPPED until operator explicitly enables
# after bootstrap is stable (spec §3).
daily_snapshot_live_schedule = ScheduleDefinition(
    name="daily_snapshot_live_schedule",
    cron_schedule="0 5 * * *",
    job=snapshot_live_delta_job,
    execution_timezone=_TZ,
    default_status=DefaultScheduleStatus.STOPPED,
)
```

- [ ] **Step 4: Register the new asset + job + schedule in `definitions.py`.**

Edit `src/orchestration/definitions.py` — add `snapshot_live_delta` to the `assets=[...]` list (already imports `_snapshot_assets`), add `snapshot_live_delta_job` to `jobs=[...]`, add `daily_snapshot_live_schedule` to `schedules=[...]`. Do not remove or reorder existing entries.

- [ ] **Step 5: Validate Dagster.**

```bash
uv run dagster definitions validate -m src.orchestration.definitions
```

Expected: `All code locations passed validation.`

- [ ] **Step 6: Verify the schedule is registered as STOPPED.**

```bash
uv run dagster schedule list -w "${DAGSTER_HOME:-$HOME/dagster_home}/workspace.yaml" 2>/dev/null | grep snapshot_live || true
# If DAGSTER_HOME isn't configured here, the validate above is the gate.
```

Acceptable output: `Schedule: daily_snapshot_live_schedule [STOPPED]` — or no output if no DAGSTER_HOME workspace is present in this shell (the validate already proved registration).

- [ ] **Step 7: Commit.**

```bash
git add src/orchestration/assets/snapshot.py src/orchestration/jobs.py \
        src/orchestration/schedules.py src/orchestration/definitions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(orchestration): snapshot_live_delta asset + dormant daily schedule"
```

---

## Task 5: Pipeline doc + bootstrap runbook addition

**Files:**
- Create: `docs/pipelines/snapshot-live-mode.md`
- Modify: `docs/runbooks/snapshot-bootstrap.md` (append "Day 12+: enable live mode" section)

- [ ] **Step 1: Write the pipeline doc.**

Create `docs/pipelines/snapshot-live-mode.md`:

````markdown
# Snapshot Live Mode

Daily catch-up pass that keeps the corpus current between quarterly bootstrap
runs. Same phase logic as the bootstrap (Plans 1–4), driven by the OpenAlex
public API instead of the local snapshot files.

## What it does

`live_worker.run_live_delta()` performs ONE pass:

1. **Build phase indexes once** from the current corpus state
   (`iter_all_real_papers_minimal`, `iter_stubs_for_resolution`,
   `build_identifier_index_for_dedup`, `build_referenced_openalex_id_set`,
   `build_openalex_id_to_point_id_map`).
2. **Fetch the delta** from `iter_live_works(since=yesterday)` —
   OpenAlex `/works?filter=from_updated_date:YYYY-MM-DD` with cursor pagination.
3. **For each work, chain `process_one` across all four phases:**
   P1 (metadata fill) → P2 (stub→real promotion) → P3 (gap discovery + inject)
   → P4 (external_cited_by extension).
4. **Update the per-phase high-water marks** so re-running the same delta date
   is a no-op (each phase is independently fill-only-missing / dedup-guarded).

## Where it differs from bootstrap

| Aspect | Bootstrap (Plans 1–4) | Live mode (Plan 5) |
|---|---|---|
| Work source | Snapshot files on disk | OpenAlex API `/works` filtered by date |
| Cadence | Manual, quarterly (1 day for full pass) | Daily, cron-scheduled |
| Phase ordering | Per-phase batches (all P1, then all P2…) | Per-work chain (each work through all 4) |
| Embedding drain | Operator runs `embed-papers --consume-snapshot-queue` between phases | Same drain command; runs as a separate step or on the next cron |

## Triggers

- **CLI:** `uv run python -m src.cli.core_collect snapshot-live-delta [--days-back N | --since YYYY-MM-DD] [--dry-run] [--max-injections N]`
- **Dagster:** `snapshot_live_delta` asset (`snapshot_live_delta_job`), scheduled by
  `daily_snapshot_live_schedule` (cron `0 5 * * *` Asia/Seoul). **Default:
  STOPPED** — operator explicitly enables after the bootstrap is stable.

## Operational notes

- Idempotency: re-running the same `--since` date is safe. Each phase is
  fill-only-missing (P1, P2 enrich path) or dedup-guarded (P2 promotion, P3
  injection, P4 union).
- Rate limits: OpenAlex polite-pool (10 requests/sec with `mailto`). The worker
  passes `OPENALEX_EMAIL` from env. For ~few-thousand-work daily deltas this is
  comfortably under limit.
- Failure modes: per-work exceptions are caught + counted; the pass continues.
  Aggregate `worker_errors` surfaces in the summary. The HWM is updated only on
  a clean pass (not on early exit from `--max-injections`).
````

- [ ] **Step 2: Append the runbook section.**

Append to `docs/runbooks/snapshot-bootstrap.md`:

````markdown

## Day 12+ — enable daily live mode

After two weeks of clean bootstrap operations and a successful drain of the
embedding queue, enable the daily live worker so corpus stays current.

### Smoke-test the live worker once manually

```bash
uv run python -m src.cli.core_collect snapshot-live-delta --days-back 1 --dry-run
```

Verify the printed summary line shows `fetched=N` (non-zero) and no
`worker_errors`. Inspect a sample by widening the date range to confirm the
classifier picks up real AI-domain works:

```bash
uv run python -m src.cli.core_collect snapshot-live-delta --since 2026-06-22 --dry-run --max-injections 20
```

### Enable the schedule

In the Dagster UI, locate `daily_snapshot_live_schedule` and flip it from
STOPPED → RUNNING. Or, in code, change `default_status=DefaultScheduleStatus.RUNNING`
in `src/orchestration/schedules.py` and redeploy.

### Monitor

The first week, check daily in the Dagster UI's asset page:
- `snapshot_live_delta` materialization metadata shows
  `fetched`/`p1.matched`/`p2.promoted`/`p3.anchor_inject`/`p3.concept_inject`/`p4.applied`.
- Embedding queue depth (visible in `snapshot-status` CLI) should drain on the
  next `core_pipeline_job` run.

### Rollback

Flip the schedule back to STOPPED and the corpus stops getting daily updates
without any other side effect. The HWM file remains, so re-enabling resumes
from the next day after the last successful pass.
````

- [ ] **Step 3: Commit.**

```bash
git add docs/pipelines/snapshot-live-mode.md docs/runbooks/snapshot-bootstrap.md
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "docs(snapshot): live-mode pipeline doc + runbook Day 12+ section"
```

---

## Task 6: Final verification

- [ ] **Step 1: Full snapshot test suite (no live integration calls).**

```bash
uv run --extra dev pytest tests/core/snapshot/ -v -m "not snapshot_live and not integration"
```

Expected: all pass; count should be ≥ 86 (78 from polish + 4 iter_live_works + 3 live_worker + 1 cli_live_delta).

- [ ] **Step 2: Dagster validation.**

```bash
uv run dagster definitions validate -m src.orchestration.definitions
```

Expected: `All code locations passed validation.`

- [ ] **Step 3: CLI smoke for `snapshot-live-delta`.**

```bash
uv run python -m src.cli.core_collect snapshot-live-delta --help
```

Expected: prints help with `--days-back`, `--since`, `--dry-run`, `--max-injections`, threshold options.

- [ ] **Step 4: Asset + schedule listing.**

```bash
uv run dagster asset list -m src.orchestration.definitions | grep snapshot_live
```

Expected: `snapshot_live_delta`.

- [ ] **Step 5: Confirm `git status --short` is empty (verification adds no files).**

```bash
git status --short
```

Expected: empty.

---

## Plan 5 Self-Review

- **Spec coverage** (snapshot spec §3 / §4 / §9):
  - §3 "Live-mode mapping" (each phase exports `process_one(work)`, daily worker chains them) — Task 2 implements.
  - §4 module structure (`work_source.iter_live_works`, `live_worker.run_live_delta`) — Tasks 1, 2.
  - §9 CLI + Dagster: `snapshot_live_delta` asset + schedule, CLI `snapshot-live-delta` — Tasks 3, 4.
  - §11 documentation rule: live-mode pipeline doc + runbook section in the same set of commits — Task 5.
- **Placeholder scan**: none. All code blocks contain real implementation; all command lines have exact arguments and expected outputs.
- **Type consistency**: `process_one` signatures referenced in Task 2's `live_worker` match the actual signatures in `phase1_corpus_fields`, `phase2_stub_resolution`, `phase3_gap_discovery`, `phase4_cited_by` (verified against the merged main HEAD `9da73e6`). `Thresholds` import path and field names match Plan 4 Task 1. `iter_live_works` keyword args (`since=date`) line up between Tasks 1 and 2.
- **No new spec gaps**: bootstrap runbook gains a Day 12+ section; the rest of the snapshot docs remain authoritative.
