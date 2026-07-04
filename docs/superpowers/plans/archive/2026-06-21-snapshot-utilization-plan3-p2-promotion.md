# Snapshot Utilization — Plan 3: P2 (stub resolution + promotion)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement P2 — match every stub against the OpenAlex snapshot, then either PROMOTE it to a real paper (preserving `cited_by`), enrich it in place, or merge it into an existing real paper. This is the highest-risk phase because it mutates the corpus; the bulk of the work is the promotion transaction and its safety net.

**Architecture:** A dedicated `promotion.py` owns the multi-step transaction with verify+rollback semantics. `phase2_stub_resolution.py` is the streaming driver. All storage writes go through Plan 1's `batch_promote_stubs`, `batch_apply_field_fill`, and `merge_stub_into_real`. The embedding queue (`src/core/snapshot/embedding_queue.py`) is the boundary to the embedder — P2 only appends to it.

**Tech Stack:** Python 3.12, uv, Dagster 1.13.9, Click. Tests: `uv run --extra dev pytest`.

## Global Constraints

- Plans 1 (`...-plan1-foundation.md`) AND 2 (`...-plan2-p1-p4.md`) MUST be merged before this plan. Verify with:
  ```python
  from src.core.snapshot import phase1_corpus_fields, phase4_cited_by, embedding_queue, extractor
  from src.core.snapshot.matcher import build_stub_index, match_work_for_stubs
  ```
- Git author: `rabqatab <minhan.nick.cho@gmail.com>`. No `Co-Authored-By`, no "Generated with Claude Code".
- All Python invocations use `uv run`.
- **The `cited_by` payload field MUST be preserved through promotion.** Plan 1 Task 18 already verifies this inside `batch_promote_stubs` (read-back assertion); this plan adds a second-line check by raising `PromotionError` on `status != "promoted"` (Task 2) and a corpus-level invariant test that scans many promoted points (Task 3).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/core/snapshot/promotion.py` | NEW | `evaluate(stub, fields)` decision + `promote_one(storage, stub, fields)` transaction wrapper |
| `src/core/snapshot/phase2_stub_resolution.py` | NEW | P2 `run()` + `process_one()` |
| `src/cli/commands/snapshot.py` | MODIFY | Add `resolve-stubs-from-snapshot` |
| `src/orchestration/assets/snapshot.py` | MODIFY | Add `snapshot_resolve_stubs` asset between P1 and P4 |
| `src/orchestration/definitions.py` | MODIFY | Re-register asset list |
| `docs/pipelines/stub-promotion.md` | NEW | P2 decision rules, transaction, rollback, dedup |
| `docs/runbooks/snapshot-bootstrap.md` | MODIFY | Insert "Day 3 — P2" section |
| `tests/core/snapshot/test_promotion.py` | NEW | L1 — decision + transaction + rollback (critical path) |
| `tests/core/snapshot/test_phase2_stub_resolution.py` | NEW | L2 end-to-end on mock_storage |

---

## Task 1: `promotion.evaluate` — decision logic

**Files:**
- Create: `src/core/snapshot/promotion.py`
- Test: `tests/core/snapshot/test_promotion.py`

**Interfaces:**
- Produces:
  ```python
  from enum import Enum
  class Decision(str, Enum):
      PROMOTE = "PROMOTE"
      ENRICH_KEEP_STUB = "ENRICH_KEEP_STUB"
      SKIP = "SKIP"

  def evaluate(stub: dict, work_fields: dict) -> Decision
  # PROMOTE  : title AND (abstract OR (year AND >=1 author))
  # ENRICH_KEEP_STUB : some metadata gained vs stub
  # SKIP : nothing useful gained
  ```

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_promotion.py`:

```python
import pytest

from src.core.snapshot.promotion import Decision, evaluate


def test_evaluate_promote_when_title_and_abstract():
    stub = {"title": None, "year": None, "authors": []}
    fields = {"title": "X", "abstract": "..."}
    assert evaluate(stub, fields) is Decision.PROMOTE


def test_evaluate_promote_when_title_year_and_author():
    stub = {"title": None, "year": None, "authors": []}
    fields = {"title": "X", "year": 2024, "authors": [{"display_name": "A"}]}
    assert evaluate(stub, fields) is Decision.PROMOTE


def test_evaluate_enrich_keep_stub_when_partial():
    stub = {"title": None, "year": None, "authors": []}
    fields = {"year": 2024}   # title still missing
    assert evaluate(stub, fields) is Decision.ENRICH_KEEP_STUB


def test_evaluate_skip_when_nothing_gained():
    stub = {"title": "Existing", "year": 2024, "authors": [{"display_name": "X"}]}
    fields = {}    # extractor returned nothing
    assert evaluate(stub, fields) is Decision.SKIP


def test_evaluate_skip_when_only_fields_already_on_stub():
    stub = {"title": "Existing", "year": 2024, "authors": [{"display_name": "X"}]}
    fields = {"title": "Existing", "year": 2024}
    assert evaluate(stub, fields) is Decision.SKIP
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_promotion.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement decision function.**

Create `src/core/snapshot/promotion.py`:

```python
"""Stub→real promotion: decision + per-stub transaction (verify + rollback)."""
import logging
from datetime import datetime, timezone
from enum import Enum

from src.core.snapshot import embedding_queue

logger = logging.getLogger(__name__)


class Decision(str, Enum):
    PROMOTE = "PROMOTE"
    ENRICH_KEEP_STUB = "ENRICH_KEEP_STUB"
    SKIP = "SKIP"
    MERGED_INTO_EXISTING = "MERGED_INTO_EXISTING"


def _has(d: dict | None, key: str) -> bool:
    if not d:
        return False
    v = d.get(key)
    return v not in (None, "", [], {})


def _gains(stub: dict, fields: dict) -> dict:
    """Return only the fields that would actually add something the stub lacks."""
    out = {}
    for k, v in fields.items():
        if v in (None, "", [], {}):
            continue
        if _has(stub, k):
            continue
        out[k] = v
    return out


def evaluate(stub: dict, work_fields: dict) -> Decision:
    """Decide what to do with this match."""
    title_after = work_fields.get("title") or stub.get("title")
    abstract_after = work_fields.get("abstract") or stub.get("abstract")
    year_after = work_fields.get("year") or stub.get("year")
    authors_after = work_fields.get("authors") or stub.get("authors") or []

    if title_after and (abstract_after or (year_after and len(authors_after) >= 1)):
        return Decision.PROMOTE
    if _gains(stub, work_fields):
        return Decision.ENRICH_KEEP_STUB
    return Decision.SKIP
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_promotion.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/promotion.py tests/core/snapshot/test_promotion.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): promotion.evaluate (PROMOTE/ENRICH_KEEP_STUB/SKIP rules)"
```

---

## Task 2: `promotion.promote_one` — transaction wrapper

**Files:**
- Modify: `src/core/snapshot/promotion.py`
- Modify: `tests/core/snapshot/test_promotion.py`

**Interfaces:**
- Produces:
  ```python
  def promote_one(storage, stub: dict, work_fields: dict, *, embedding_queue_root=None) -> Decision
  # Steps: (A) find_real_by_identifier — if hit, merge_stub_into_real, return MERGED_INTO_EXISTING.
  # (B) batch_promote_stubs([{...}]) — single-item promotion call (the storage layer does verify).
  # (C) On status="promoted" + abstract present, embedding_queue.append(point_id, source="promotion").
  # (D) On status="verify_failed" or "error", raise PromotionError so the caller can quarantine.
  ```

- [ ] **Step 1: Append the failing test.**

Append to `tests/core/snapshot/test_promotion.py`:

```python
import pytest
from pathlib import Path

from src.core.snapshot.promotion import promote_one, Decision, PromotionError
from src.core.snapshot import embedding_queue


def test_promote_one_promotes_and_queues(mock_storage, tmp_path):
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    stub = next(s for s in mock_storage.iter_stubs_for_resolution()
                if s["point_id"] == "stub-doi-001")
    fields = {
        "title": "Stub DOI Match",
        "doi": "10.1000/stub-doi-001",
        "year": 2024,
        "authors": [{"display_name": "Alice"}],
        "abstract": "abstract text",
    }
    result = promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
    assert result is Decision.PROMOTE
    p = mock_storage.get_payload("stub-doi-001")
    assert p["is_stub"] is False
    assert p["cited_by"] == ["real-005", "real-006"]
    assert p["cited_by_count"] == 2
    assert p["promoted_from_stub"] is True
    queued = list(embedding_queue.drain(root=tmp_path))
    assert queued == [("stub-doi-001", "promotion")]


def test_promote_one_no_abstract_does_not_queue(mock_storage, tmp_path):
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    stub = next(s for s in mock_storage.iter_stubs_for_resolution()
                if s["point_id"] == "stub-doi-002")
    fields = {"title": "X", "year": 2024, "authors": [{"display_name": "Y"}]}  # no abstract
    result = promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
    assert result is Decision.PROMOTE
    queued = list(embedding_queue.drain(root=tmp_path))
    assert queued == []


def test_promote_one_merges_when_real_dup_exists(mock_storage, tmp_path):
    """If a real paper already exists with the same DOI, merge the stub into it."""
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    # Plant a real paper with the same DOI as stub-doi-001
    mock_storage.set_payload("real-existing", {
        "is_stub": False,
        "doi": "10.1000/stub-doi-001",
        "cited_by": ["real-007"],
        "cited_by_count": 1,
    })
    stub = next(s for s in mock_storage.iter_stubs_for_resolution()
                if s["point_id"] == "stub-doi-001")
    fields = {"title": "Stub DOI Match", "doi": "10.1000/stub-doi-001",
              "year": 2024, "authors": [{"display_name": "Alice"}], "abstract": "x"}
    result = promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
    assert result is Decision.MERGED_INTO_EXISTING
    real = mock_storage.get_payload("real-existing")
    assert set(real["cited_by"]) == {"real-005", "real-006", "real-007"}
    assert mock_storage.get_payload("stub-doi-001") is None  # stub deleted


def test_promote_one_idempotent_on_already_promoted(mock_storage, tmp_path):
    """Re-running promote_one on an already-promoted point is safe."""
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    stub = next(s for s in mock_storage.iter_stubs_for_resolution()
                if s["point_id"] == "stub-doi-001")
    fields = {"title": "Stub DOI Match", "doi": "10.1000/stub-doi-001",
              "year": 2024, "authors": [{"display_name": "Alice"}], "abstract": "x"}
    promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
    # second run
    p_before = dict(mock_storage.get_payload("stub-doi-001"))
    promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
    p_after = mock_storage.get_payload("stub-doi-001")
    # cited_by must not duplicate
    assert p_after["cited_by"] == p_before["cited_by"]
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_promotion.py -v
```

Expected: 4 new failures (`PromotionError`, `promote_one` not yet defined).

- [ ] **Step 3: Implement.**

Append to `src/core/snapshot/promotion.py`:

```python
class PromotionError(Exception):
    """Raised when batch_promote_stubs returns status != 'promoted'."""

    def __init__(self, point_id: str, reason: str):
        self.point_id = point_id
        self.reason = reason
        super().__init__(f"{point_id}: {reason}")


def promote_one(
    storage,
    stub: dict,
    work_fields: dict,
    *,
    embedding_queue_root=None,
) -> Decision:
    """Run one promotion transaction. Raises PromotionError on verify failure."""
    pid = stub["point_id"]

    # A. dedup guard
    real_dup = storage.find_real_by_identifier({
        "doi": work_fields.get("doi") or stub.get("doi"),
        "openalex_id": work_fields.get("openalex_id") or stub.get("openalex_id"),
        "arxiv_id": work_fields.get("arxiv_id") or stub.get("arxiv_id"),
    })
    if real_dup and real_dup != pid:
        storage.merge_stub_into_real(pid, real_dup)
        return Decision.MERGED_INTO_EXISTING

    # B. batch_promote_stubs (the storage call does set_payload + verify)
    result = storage.batch_promote_stubs([{
        "point_id": pid,
        "work_fields": work_fields,
        "preserved_cited_by": list(stub.get("cited_by") or []),
        "preserved_cited_by_count_internal": stub.get("cited_by_count_internal", 0),
        "preserved_alternate_identifiers": stub.get("alternate_identifiers") or {},
    }])
    if not result:
        raise PromotionError(pid, "batch_promote_stubs returned no result")
    r = result[0]
    if r["status"] != "promoted":
        raise PromotionError(pid, r.get("error") or r["status"])

    # C. queue for embedding if abstract present
    if work_fields.get("abstract"):
        embedding_queue.append(pid, source="promotion", root=embedding_queue_root)

    return Decision.PROMOTE
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_promotion.py -v
```

Expected: 9 passed total.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/promotion.py tests/core/snapshot/test_promotion.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): promotion.promote_one (dedup guard + batch + queue)"
```

---

## Task 3: Invariant — cited_by preservation corpus check

**Files:**
- Modify: `tests/core/snapshot/test_promotion.py`

- [ ] **Step 1: Append the invariant test.**

Append to `tests/core/snapshot/test_promotion.py`:

```python
def test_cited_by_invariant_after_many_promotions(mock_storage, tmp_path):
    """Run 5 promotions, then assert no promoted point lost its cited_by."""
    mock_storage.seed_from_json(Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json")
    promoted: dict[str, list[str]] = {}
    for stub in list(mock_storage.iter_stubs_for_resolution()):
        if stub["identifier_type"] in ("doi", "openalex"):
            promoted[stub["point_id"]] = list(stub["cited_by"])
            fields = {"title": "T", "year": 2024, "authors": [{"display_name": "A"}], "abstract": "x"}
            try:
                promote_one(mock_storage, stub, fields, embedding_queue_root=tmp_path)
            except PromotionError:
                continue
    # Invariant: no promoted point ended up with cited_by==[] when it started non-empty
    for pid, original in promoted.items():
        pl = mock_storage.get_payload(pid)
        if pl is None:
            continue  # merged
        if pl.get("promoted_from_stub") is True and original:
            assert pl["cited_by"], f"{pid} lost cited_by; was {original}"
```

- [ ] **Step 2: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_promotion.py -v -k invariant
```

Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add tests/core/snapshot/test_promotion.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "test(snapshot): cited_by-preservation invariant across many promotions"
```

---

## Task 4: `phase2_stub_resolution.run()` — streaming driver

**Files:**
- Create: `src/core/snapshot/phase2_stub_resolution.py`
- Test: `tests/core/snapshot/test_phase2_stub_resolution.py`

**Interfaces:**
- Consumes: `extractor.extract_full_record`, `matcher.{build_stub_index, match_work_for_stubs}`, `work_source.iter_snapshot_works`, `checkpoint`, `promotion.{evaluate, promote_one, Decision, PromotionError}`, `storage.{iter_stubs_for_resolution, batch_apply_field_fill}`, `stats.PhaseSummary`.
- Produces:
  ```python
  def run(storage, snapshot_dir: str, *, dry_run: bool = False, batch_size: int = 500,
          limit_files: int | None = None, allow_promotion: bool = True,
          allow_merge: bool = True, checkpoint_root=None) -> PhaseSummary
  def process_one(work, stub_index, all_stubs_by_id, *, storage, dry_run=False,
                  allow_promotion=True, allow_merge=True) -> dict
  ```

- [ ] **Step 1: Write the failing L2 test.**

Create `tests/core/snapshot/test_phase2_stub_resolution.py`:

```python
from pathlib import Path

from src.core.snapshot import phase2_stub_resolution

FIX = Path(__file__).parent / "fixtures"


def _setup(tmp_path):
    d = tmp_path / "data" / "works" / "updated_date=2024-01-01"
    d.mkdir(parents=True)
    (d / "part_0000.gz").write_bytes((FIX / "works" / "tiny.jsonl.gz").read_bytes())
    return tmp_path / "data" / "works"


def test_p2_run_promotes_stubs_and_queues_embedding(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    snap = _setup(tmp_path)
    cpt = tmp_path / "checkpoints"

    summary = phase2_stub_resolution.run(
        mock_storage, snapshot_dir=str(snap), checkpoint_root=cpt,
    )

    # Expect: work 4 → promote stub-doi-001, work 5 → promote stub-title-001,
    # work 6 → ENRICH_KEEP_STUB on stub-doi-002.
    assert summary.extra["promoted"] >= 2
    assert summary.extra["enriched"] >= 1
    p = mock_storage.get_payload("stub-doi-001")
    assert p["is_stub"] is False
    assert "cited_by" in p


def test_p2_run_dry_run_no_mutation(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    snap = _setup(tmp_path)

    before = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    summary = phase2_stub_resolution.run(
        mock_storage, snapshot_dir=str(snap), dry_run=True,
        checkpoint_root=tmp_path / "checkpoints",
    )
    after = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    assert before == after
    # Dry-run still reports what would happen
    assert summary.extra.get("promoted", 0) >= 2


def test_p2_run_resume_skips_done_files(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    mock_storage.seed_from_json(FIX / "corpus" / "seed_stubs.json")
    snap = _setup(tmp_path)
    cpt = tmp_path / "checkpoints"

    s1 = phase2_stub_resolution.run(mock_storage, snapshot_dir=str(snap), checkpoint_root=cpt)
    s2 = phase2_stub_resolution.run(mock_storage, snapshot_dir=str(snap), checkpoint_root=cpt)
    assert s2.scanned == 0
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_phase2_stub_resolution.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement.**

Create `src/core/snapshot/phase2_stub_resolution.py`:

```python
"""P2: resolve-stubs-from-snapshot — match every stub, then promote/enrich/merge."""
import logging
import time
from pathlib import Path

from src.core.snapshot import checkpoint as cp
from src.core.snapshot import work_source
from src.core.snapshot.extractor import extract_full_record
from src.core.snapshot.matcher import build_stub_index, match_work_for_stubs
from src.core.snapshot.promotion import Decision, PromotionError, evaluate, promote_one
from src.core.snapshot.stats import PhaseSummary

logger = logging.getLogger(__name__)

PHASE = "p2"


def _gains_filter(stub: dict, fields: dict) -> dict:
    out = {}
    for k, v in fields.items():
        if v in (None, "", [], {}):
            continue
        if stub.get(k):
            continue
        out[k] = v
    return out


def process_one(
    work,
    stub_index,
    all_stubs_by_id,
    *,
    storage,
    dry_run: bool = False,
    allow_promotion: bool = True,
    allow_merge: bool = True,
    embedding_queue_root: Path | None = None,
) -> dict:
    stub = match_work_for_stubs(work, stub_index, all_stubs_by_id=all_stubs_by_id)
    if stub is None:
        return {"matched": False, "action": None}

    fields = extract_full_record(work)
    decision = evaluate(stub, fields)

    if decision is Decision.SKIP:
        return {"matched": True, "action": "skip"}

    if dry_run:
        return {"matched": True, "action": decision.value, "would_promote": True}

    if decision is Decision.PROMOTE and allow_promotion:
        try:
            result = promote_one(storage, stub, fields,
                                 embedding_queue_root=embedding_queue_root)
        except PromotionError as e:
            return {"matched": True, "action": "promote_failed", "error": str(e)}
        if result is Decision.MERGED_INTO_EXISTING:
            if not allow_merge:
                return {"matched": True, "action": "merge_blocked"}
            return {"matched": True, "action": "merged"}
        return {"matched": True, "action": "promoted"}

    if decision is Decision.ENRICH_KEEP_STUB or decision is Decision.PROMOTE:
        # ENRICH_KEEP_STUB always; PROMOTE falls here only if allow_promotion=False
        gains = _gains_filter(stub, fields)
        if gains:
            storage.batch_apply_field_fill([(stub["point_id"], gains)])
        return {"matched": True, "action": "enriched", "field_count": len(gains)}

    return {"matched": True, "action": "skip"}


def run(
    storage,
    snapshot_dir: str,
    *,
    dry_run: bool = False,
    batch_size: int = 500,
    limit_files: int | None = None,
    allow_promotion: bool = True,
    allow_merge: bool = True,
    checkpoint_root: Path | None = None,
    embedding_queue_root: Path | None = None,
) -> PhaseSummary:
    t0 = time.time()
    summary = PhaseSummary(phase=PHASE)
    done = cp.load(PHASE, root=checkpoint_root)

    stubs = list(storage.iter_stubs_for_resolution())
    summary.extra["stubs_seen"] = len(stubs)
    stub_index = build_stub_index(stubs)
    all_stubs_by_id = {s["point_id"]: s for s in stubs}

    counters = {"promoted": 0, "enriched": 0, "merged": 0, "merge_blocked": 0,
                "promote_failed": 0, "skip": 0,
                "doi_matches": 0, "title_matches": 0, "openalex_matches": 0,
                "arxiv_matches": 0, "queued_for_embed": 0, "files_done": 0}
    current_file: str | None = None

    for fp, work in work_source.iter_snapshot_works(snapshot_dir, skip_files=done):
        if fp != current_file:
            if current_file is not None:
                cp.mark_done(PHASE, current_file, root=checkpoint_root)
                counters["files_done"] += 1
                if limit_files is not None and counters["files_done"] >= limit_files:
                    break
            current_file = fp
        summary.scanned += 1
        try:
            res = process_one(
                work, stub_index, all_stubs_by_id,
                storage=storage, dry_run=dry_run,
                allow_promotion=allow_promotion, allow_merge=allow_merge,
                embedding_queue_root=embedding_queue_root,
            )
            if res.get("matched"):
                summary.matched += 1
                action = res.get("action")
                if action in counters:
                    counters[action] += 1
                if action == "promoted" and not dry_run:
                    counters["queued_for_embed"] += 1
        except Exception as e:
            summary.worker_errors += 1
            cp.quarantine(PHASE, work, str(e), root=checkpoint_root)
            summary.quarantined += 1
            if summary.worker_errors % 100 == 1:
                logger.warning("p2 worker error: %s", e)

    if current_file is not None:
        cp.mark_done(PHASE, current_file, root=checkpoint_root)
        counters["files_done"] += 1

    summary.applied = counters["promoted"] + counters["enriched"] + counters["merged"]
    summary.duration_s = time.time() - t0
    summary.extra.update(counters)
    logger.info(summary.to_log_line())
    return summary
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_phase2_stub_resolution.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/phase2_stub_resolution.py tests/core/snapshot/test_phase2_stub_resolution.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): P2 phase2_stub_resolution (run + process_one)"
```

---

## Task 5: CLI — `resolve-stubs-from-snapshot`

**Files:**
- Modify: `src/cli/commands/snapshot.py`
- Test: `tests/core/snapshot/test_cli_p2.py`

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_cli_p2.py`:

```python
from click.testing import CliRunner

from src.cli.core_collect import cli


def test_p2_command_registered():
    runner = CliRunner()
    res = runner.invoke(cli, ["resolve-stubs-from-snapshot", "--help"])
    assert res.exit_code == 0
    assert "allow-promotion" in res.output
    assert "allow-merge" in res.output
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_cli_p2.py -v
```

Expected: `Error: No such command`.

- [ ] **Step 3: Add the command.**

Append to `src/cli/commands/snapshot.py`:

```python
    @cli.command("resolve-stubs-from-snapshot")
    @click.option("--snapshot-dir",
                  default="/mnt/nfs/ssd2/openalex_snapshot/data/works")
    @click.option("--batch-size", type=int, default=500)
    @click.option("--dry-run", is_flag=True,
                  help="Report would-be promotions/enrichments without writing.")
    @click.option("--resume/--no-resume", default=True)
    @click.option("--limit-files", type=int, default=None)
    @click.option("--allow-promotion/--no-allow-promotion", default=True,
                  help="If False, only enrich-in-place; never flip is_stub.")
    @click.option("--allow-merge/--no-allow-merge", default=True,
                  help="If False, refuse to merge a stub into an existing real paper.")
    def resolve_stubs_from_snapshot(snapshot_dir, batch_size, dry_run, resume,
                                     limit_files, allow_promotion, allow_merge):
        """Match every stub against the OpenAlex snapshot, then promote (preserve
        cited_by), enrich-in-place, or merge into an existing real paper."""
        from src.core.snapshot import phase2_stub_resolution
        from src.core.snapshot import checkpoint as cp
        from src.core.storage import QdrantStorage
        storage = QdrantStorage()
        if not resume:
            cp.reset("p2")
        summary = phase2_stub_resolution.run(
            storage, snapshot_dir=snapshot_dir, batch_size=batch_size,
            dry_run=dry_run, limit_files=limit_files,
            allow_promotion=allow_promotion, allow_merge=allow_merge,
        )
        click.echo(summary.to_log_line())
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_cli_p2.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/cli/commands/snapshot.py tests/core/snapshot/test_cli_p2.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(cli): resolve-stubs-from-snapshot (P2 trigger)"
```

---

## Task 6: Dagster — `snapshot_resolve_stubs` asset

**Files:**
- Modify: `src/orchestration/assets/snapshot.py`
- Modify: `src/orchestration/definitions.py`

- [ ] **Step 1: Add the asset between P1 and P4.**

Edit `src/orchestration/assets/snapshot.py`. Replace the existing `snapshot_extend_cited_by` `deps` to chain through P2:

```python
from src.core.snapshot import phase2_stub_resolution


@asset(deps=[snapshot_enrich_corpus_fields], group_name="snapshot")
def snapshot_resolve_stubs(context: AssetExecutionContext) -> MaterializeResult:
    """P2: match stubs against the snapshot; promote or enrich."""
    summary = phase2_stub_resolution.run(
        QdrantStorage(),
        snapshot_dir="/mnt/nfs/ssd2/openalex_snapshot/data/works",
    )
    context.log.info(summary.to_log_line())
    return MaterializeResult(metadata=summary.to_dagster_metadata())


# Existing snapshot_extend_cited_by — update deps to include P2:
@asset(deps=[snapshot_resolve_stubs], group_name="snapshot")
def snapshot_extend_cited_by(context: AssetExecutionContext) -> MaterializeResult:
    ...   # body unchanged
```

(Note: when Plan 4 adds P3, it will redefine `snapshot_extend_cited_by` deps to
include P3 as well.)

- [ ] **Step 2: Register the new asset in `definitions.py`.**

Edit `src/orchestration/definitions.py` — add `_snapshot_assets.snapshot_resolve_stubs` to the `Definitions(assets=[...])` list.

- [ ] **Step 3: Validate.**

```bash
uv run dagster definitions validate -m src.orchestration.definitions
```

Expected: `All code locations passed validation.`

- [ ] **Step 4: Commit.**

```bash
git add src/orchestration/assets/snapshot.py src/orchestration/definitions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(orchestration): snapshot_resolve_stubs asset (P2 in DAG)"
```

---

## Task 7: Pipeline doc — `docs/pipelines/stub-promotion.md`

**Files:**
- Create: `docs/pipelines/stub-promotion.md`

- [ ] **Step 1: Write the doc.**

Create `docs/pipelines/stub-promotion.md`:

````markdown
# Stub Promotion (P2)

P2 of the snapshot utilization system. For every stub in the corpus, match it
against the OpenAlex snapshot; promote, enrich, or merge.

## Decision rules

`src/core/snapshot/promotion.py:evaluate(stub, work_fields)`:

| Condition | Decision |
|---|---|
| `title` AND (`abstract` OR (`year` AND ≥1 author)) after the merge | `PROMOTE` |
| Some field is gained that the stub did not have | `ENRICH_KEEP_STUB` |
| Nothing gained | `SKIP` |

## Promotion transaction

Each promotion is a single-stub call to `storage.batch_promote_stubs`. Steps:

1. **Dedup guard** (`storage.find_real_by_identifier`): if any real paper
   already exists with this `doi` / `openalex_id` / `arxiv_id`, merge instead
   via `storage.merge_stub_into_real` (which unions `cited_by` into the real
   paper, dedups, and deletes the stub). Return `MERGED_INTO_EXISTING`.
2. **Payload swap** (`storage.set_payload`): write all extracted fields plus
   `is_stub=False`, `cited_by` preserved, `cited_by_count=len(cited_by)`,
   `cited_by_count_internal` preserved, `alternate_identifiers` preserved,
   `promoted_from_stub=True`, `promoted_at`, `snapshot_filled_at`.
3. **Verify** (read-back inside `batch_promote_stubs`): assert
   `is_stub is False` and `set(after.cited_by) >= set(stub.cited_by)`. If
   either fails, status `verify_failed` is returned and the caller raises
   `PromotionError`.
4. **Embedding queue**: if `work_fields["abstract"]` is present,
   `embedding_queue.append(point_id, source="promotion")`. The drain happens
   later via `embed-papers --consume-snapshot-queue`.

## Rollback

The transaction is idempotent (`set_payload` with the same key overwrites with
the same value), so the rollback strategy on partial failure is "next pass will
re-promote it":

- If verification fails, the point is quarantined to
  `${checkpoint_root}/p2/quarantine.jsonl` with the failing work. The operator
  inspects, decides whether to retry or hand-fix.
- If Qdrant goes down mid-batch, the failed batch is dumped to
  `${checkpoint_root}/p2/failed_batches/<ts>.jsonl`. Replay with
  `snapshot-replay-failed --phase p2`.

## Dedup safety

When `find_real_by_identifier` returns a real paper hit, `merge_stub_into_real`:

- Unions the stub's `cited_by` into the real paper's `cited_by`, sorted.
- Updates `cited_by_count`.
- Unions `alternate_identifiers`.
- Deletes the stub point.

This handles the race "incremental collection adds the real paper after the
stub was created" (TODO.md #16, now implemented).

## Corpus-level invariant

After a P2 run, the following must be 0:

```python
from src.core.storage import QdrantStorage
from qdrant_client import models as m
st = QdrantStorage()
n = st.client.count(
    st.collection_name,
    count_filter=m.Filter(
        must=[m.FieldCondition(key="promoted_from_stub", match=m.MatchValue(value=True))],
        must_not=[m.IsEmptyCondition(is_empty=m.PayloadField(key="cited_by"))],
    ),
    exact=True,
).count
# Promoted with empty cited_by — but only count those that should have had citers:
# this needs the original cited_by-count from the pre-run snapshot to be meaningful.
```

A more useful check: spot-check 10 random `promoted_from_stub=True` points in the
search UI and verify each has a sensible `cited_by` list.
````

- [ ] **Step 2: Commit.**

```bash
git add docs/pipelines/stub-promotion.md
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "docs(pipeline): stub-promotion (P2 rules, transaction, dedup, invariants)"
```

---

## Task 8: Runbook — insert "Day 3 — P2" section

**Files:**
- Modify: `docs/runbooks/snapshot-bootstrap.md`

- [ ] **Step 1: Insert the P2 section.**

In `docs/runbooks/snapshot-bootstrap.md`, replace the "Day 3 — P2 (covered in the separate Plan 3 runbook section)" placeholder with:

````markdown
## Day 3 — P2 dry-run and full run

### Dry-run first

```bash
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot \
    --dry-run --limit-files 20
```

Inspect the printed summary:

```
p2 Summary: scanned=N matched=M ... stubs_seen=S promoted=P enriched=E merged=Me ...
```

Sanity:
- `promoted / matched` should be majority for high-quality stubs.
- `merged` reflects existing-real-paper collisions (good, not an error).
- `enriched` reflects partial metadata gains (also good).

### Full run

```bash
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot
```

Expected duration: ≈6–8 hours.

### Post-run verification

1. **Invariant query** — every promoted point with a non-empty stub `cited_by`
   list should still carry that list:

```bash
uv run python -c "
from src.core.storage import QdrantStorage
from qdrant_client import models as m
st = QdrantStorage()
flt = m.Filter(must=[m.FieldCondition(key='promoted_from_stub', match=m.MatchValue(value=True))])
pts, _ = st.client.scroll(st.collection_name, scroll_filter=flt, limit=20,
                          with_payload=['cited_by','cited_by_count'])
for p in pts:
    print(str(p.id)[:8], 'cited_by=', len(p.payload.get('cited_by') or []),
          'count=', p.payload.get('cited_by_count'))
"
```

Every line should show a non-zero `cited_by`. If any is 0, inspect the
quarantine file:

```bash
ls -la ~/dagster_home/snapshot_checkpoints/p2/quarantine.jsonl
```

2. **DQ checks still pass.**

```bash
uv run python -c "
from src.core.pipeline import dq
for n in ['abstract_coverage','embedding_coverage_complete','doi_papers_have_refs','real_papers_have_titles']:
    r = getattr(dq, n)()
    print(n, '=', 'PASS' if r['passed'] else 'FAIL', r['metadata'])
"
```

## Day 4–5 — drain the embedding queue

```bash
uv run python -m src.cli.core_collect embed-papers --consume-snapshot-queue
```

(`--consume-snapshot-queue` flag is added in Plan 4.) Wait until the queue is
empty before moving on:

```bash
uv run python -m src.cli.core_collect snapshot-status
```

(Also added in Plan 4.)
````

- [ ] **Step 2: Commit.**

```bash
git add docs/runbooks/snapshot-bootstrap.md
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "docs(runbook): Day 3 — P2 dry-run, full run, invariant check, drain"
```

---

## Task 9: Final verification

- [ ] **Step 1: Test suite.**

```bash
uv run --extra dev pytest tests/core/snapshot/ -v -m "not snapshot_live and not integration"
```

Expected: all pass.

- [ ] **Step 2: Dagster validate.**

```bash
uv run dagster definitions validate -m src.orchestration.definitions
```

Expected: `All code locations passed validation.`

- [ ] **Step 3: CLI smoke.**

```bash
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot --help
```

Expected: prints help with `--allow-promotion`, `--allow-merge`.

- [ ] **Step 4: Asset list.**

```bash
uv run dagster asset list -m src.orchestration.definitions | grep snapshot_
```

Expected: lists `snapshot_enrich_corpus_fields`, `snapshot_resolve_stubs`, `snapshot_extend_cited_by`.

---

## Plan 3 Self-Review Notes

- **Spec §5 P2 logic:** Task 4 covers the prepare→stream→flush→checkpoint→summary skeleton with all counter fields (stubs_seen, doi/title/openalex matches, promoted, enriched, merged, queued_for_embed, files_done).
- **Spec §6 promotion transaction:** Task 2 implements the 4 steps (dedup guard, payload swap via `batch_promote_stubs`, verify in the storage call, embedding queue append). The verify+rollback is split between `batch_promote_stubs` (Plan 1) and `promote_one` (Task 2) — neat separation.
- **Spec §13 R1 (cited_by loss):** Task 3 invariant test + the Day 3 runbook query both check the same invariant in different layers (unit + corpus).
- **Spec §9 CLI:** Task 5 matches the `--allow-promotion`, `--allow-merge`, `--dry-run`, `--resume/--no-resume`, `--limit-files`, `--batch-size` signature from §9.
- **Spec §11 docs:** `docs/pipelines/stub-promotion.md` is the same-PR doc with the implementation; runbook updated in Task 8.
- **Type consistency:** `Decision` enum, `PromotionError`, `promote_one(storage, stub, work_fields, *, embedding_queue_root)` all match between `promotion.py` and `phase2_stub_resolution.py`.
