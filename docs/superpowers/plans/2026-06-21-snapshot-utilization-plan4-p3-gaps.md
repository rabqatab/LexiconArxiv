# Snapshot Utilization — Plan 4: P3 (gap discovery + injection) + operational commands

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement P3 — discover snapshot works not in the corpus that are either (a) referenced by ≥2 corpus papers or (b) AI-concept high-impact recent — and inject them as new real papers (queued for embedding). Plus the operational triad (`snapshot-status`, `snapshot-replay-failed`, `snapshot-reset`) and the `embed-papers --consume-snapshot-queue` extension that drains the queue produced by P2/P3.

**Architecture:** `gap_filter.py` holds the relevance classifier (ANCHOR_INJECT vs CONCEPT_INJECT vs REJECT) with thresholds as module constants. `phase3_gap_discovery.py` streams works, calls the filter, calls `batch_inject_papers`, and feeds the embedding queue. The operational commands read `checkpoint.py` state + `embedding_queue.depth()`. The embed extension wires `embedding_queue.drain()` into the existing embed loop.

**Tech Stack:** Python 3.12, uv, Dagster 1.13.9, Click. Tests: `uv run --extra dev pytest`.

## Global Constraints

- Plans 1, 2, AND 3 MUST be merged before this plan. Verify with:
  ```python
  from src.core.snapshot import phase1_corpus_fields, phase2_stub_resolution, phase4_cited_by
  from src.core.snapshot import embedding_queue, checkpoint
  ```
- Git author: `rabqatab <minhan.nick.cho@gmail.com>`. No `Co-Authored-By`.
- All Python invocations use `uv run`.
- AI taxonomy concept IDs are module constants in `gap_filter.AI_CONCEPT_IDS`. The initial list is hard-coded at implementation time (see Task 1 — exact OpenAlex concept IDs).
- Injection thresholds (`ANCHOR_MIN_CITERS=2`, `CONCEPT_MIN_RECENT=50`, `CONCEPT_MIN_OLD=200`, `CONCEPT_MIN_YEAR=2018`) are module constants overridable by CLI options.
- The `--max-injections N` safety cap MUST short-circuit the run when reached, with a clear log line and a non-zero `extra["capped"]=True` in the summary.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/core/snapshot/gap_filter.py` | NEW | `classify(work, anchor_set, taxonomy, thresholds) -> Classification` |
| `src/core/snapshot/phase3_gap_discovery.py` | NEW | P3 `run()` + `process_one()` |
| `src/cli/commands/snapshot.py` | MODIFY | `discover-corpus-gaps`, `snapshot-status`, `snapshot-replay-failed`, `snapshot-reset` |
| `src/cli/commands/embedding.py` | MODIFY | Add `--consume-snapshot-queue` to `embed-papers` |
| `src/orchestration/assets/snapshot.py` | MODIFY | Add `snapshot_discover_gaps`; update `snapshot_extend_cited_by` deps to include P3 |
| `src/orchestration/definitions.py` | MODIFY | Register new asset |
| `docs/pipelines/corpus-gap-discovery.md` | NEW | P3 hybrid rules, taxonomy, threshold tuning |
| `docs/runbooks/snapshot-bootstrap.md` | MODIFY | Insert Day 6 (P3) section |
| `docs/runbooks/snapshot-rollback.md` | NEW | Rollback procedures |
| `tests/core/snapshot/test_gap_filter.py` | NEW | L1 — every classification rule |
| `tests/core/snapshot/test_phase3_gap_discovery.py` | NEW | L2 end-to-end |
| `tests/core/snapshot/test_cli_p3_and_ops.py` | NEW | CLI smoke for the 4 new commands |

---

## Task 1: `gap_filter.py` — classification rules

**Files:**
- Create: `src/core/snapshot/gap_filter.py`
- Test: `tests/core/snapshot/test_gap_filter.py`

**Interfaces:**
- Produces:
  ```python
  from dataclasses import dataclass
  from enum import Enum

  class Classification(str, Enum):
      ANCHOR_INJECT = "ANCHOR_INJECT"
      CONCEPT_INJECT = "CONCEPT_INJECT"
      REJECT = "REJECT"

  @dataclass
  class Thresholds:
      anchor_min_citers: int = 2
      concept_min_recent: int = 50
      concept_min_old: int = 200
      concept_min_year: int = 2018
      recent_age_years: int = 5

  AI_CONCEPT_IDS: set[str] = {...}   # OpenAlex concept IDs (W-namespace "C...")

  def classify(work: dict, *, anchor_set: dict[str, int],
               taxonomy: set[str], thresholds: Thresholds,
               now_year: int) -> Classification
  ```

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_gap_filter.py`:

```python
from src.core.snapshot.gap_filter import (
    AI_CONCEPT_IDS,
    Classification,
    Thresholds,
    classify,
)


def _work(**kwargs) -> dict:
    base = {
        "id": "https://openalex.org/W0",
        "publication_year": 2024,
        "cited_by_count": 0,
        "concepts": [],
    }
    base.update(kwargs)
    return base


def test_anchor_inject_when_citers_meets_threshold():
    work = _work(id="https://openalex.org/W42")
    cls = classify(work, anchor_set={"W42": 5},
                   taxonomy=AI_CONCEPT_IDS, thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.ANCHOR_INJECT


def test_anchor_inject_rejected_below_threshold():
    work = _work(id="https://openalex.org/W42")
    cls = classify(work, anchor_set={"W42": 1},
                   taxonomy=AI_CONCEPT_IDS, thresholds=Thresholds(), now_year=2026)
    # not anchor; falls through to concept check; no AI concepts → REJECT
    assert cls is Classification.REJECT


def test_concept_inject_recent_meets_threshold():
    ai_concept = next(iter(AI_CONCEPT_IDS))
    work = _work(
        publication_year=2024, cited_by_count=60,
        concepts=[{"id": f"https://openalex.org/{ai_concept}", "display_name": "AI"}],
    )
    cls = classify(work, anchor_set={}, taxonomy=AI_CONCEPT_IDS,
                   thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.CONCEPT_INJECT


def test_concept_reject_recent_below_threshold():
    ai_concept = next(iter(AI_CONCEPT_IDS))
    work = _work(
        publication_year=2024, cited_by_count=10,
        concepts=[{"id": f"https://openalex.org/{ai_concept}", "display_name": "AI"}],
    )
    cls = classify(work, anchor_set={}, taxonomy=AI_CONCEPT_IDS,
                   thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.REJECT


def test_concept_reject_too_old_year():
    ai_concept = next(iter(AI_CONCEPT_IDS))
    work = _work(
        publication_year=2015, cited_by_count=1000,
        concepts=[{"id": f"https://openalex.org/{ai_concept}", "display_name": "AI"}],
    )
    cls = classify(work, anchor_set={}, taxonomy=AI_CONCEPT_IDS,
                   thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.REJECT


def test_anchor_wins_over_concept():
    """When both rules pass, ANCHOR is the recorded classification."""
    ai_concept = next(iter(AI_CONCEPT_IDS))
    work = _work(
        id="https://openalex.org/W42",
        publication_year=2024, cited_by_count=100,
        concepts=[{"id": f"https://openalex.org/{ai_concept}", "display_name": "AI"}],
    )
    cls = classify(work, anchor_set={"W42": 5}, taxonomy=AI_CONCEPT_IDS,
                   thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.ANCHOR_INJECT


def test_concept_reject_when_no_ai_concept():
    work = _work(
        publication_year=2024, cited_by_count=1000,
        concepts=[{"id": "https://openalex.org/C0000000", "display_name": "Other"}],
    )
    cls = classify(work, anchor_set={}, taxonomy=AI_CONCEPT_IDS,
                   thresholds=Thresholds(), now_year=2026)
    assert cls is Classification.REJECT
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_gap_filter.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement.**

Create `src/core/snapshot/gap_filter.py`:

```python
"""P3 hybrid relevance filter: ANCHOR_INJECT | CONCEPT_INJECT | REJECT.

Thresholds and taxonomy live as module constants. Override per-run via the CLI
options that wrap Thresholds.
"""
from dataclasses import dataclass
from enum import Enum


class Classification(str, Enum):
    ANCHOR_INJECT = "ANCHOR_INJECT"
    CONCEPT_INJECT = "CONCEPT_INJECT"
    REJECT = "REJECT"


@dataclass
class Thresholds:
    anchor_min_citers: int = 2
    concept_min_recent: int = 50
    concept_min_old: int = 200
    concept_min_year: int = 2018
    recent_age_years: int = 5


# OpenAlex concept IDs for AI/ML and adjacent. Update this set as the taxonomy
# evolves (the OpenAlex concepts API returns the canonical tree). These are
# the C-namespace IDs that appear in each work's `concepts[].id` (after the
# https://openalex.org/ prefix is stripped).
#
# Selected at implementation time (2026-06-21) from
# https://api.openalex.org/concepts?filter=level:1,ancestors.id:C154945302 .
AI_CONCEPT_IDS: set[str] = {
    "C154945302",  # Artificial intelligence
    "C119857082",  # Machine learning
    "C108583219",  # Deep learning
    "C204321447",  # Natural language processing
    "C31972630",   # Computer vision
    "C97541855",   # Reinforcement learning
    "C50644808",   # Artificial neural network
    "C2780451532", # Generative model
    "C2780641677", # Transformer (machine learning model)
    "C188441475",  # Knowledge graph
    "C23123220",   # Information retrieval
    "C2776760102", # Recommender system
    "C107457646",  # Robotics
    "C13280743",   # Speech recognition
    "C2776401178", # Federated learning
    "C2776194310", # Multi-agent system
    "C140779682",  # Foundation model
}


def _normalize_concept_id(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.rsplit("/", 1)[-1]


def _has_ai_concept(work: dict, taxonomy: set[str]) -> bool:
    for c in work.get("concepts") or []:
        cid = _normalize_concept_id(c.get("id"))
        if cid and cid in taxonomy:
            return True
    return False


def classify(
    work: dict,
    *,
    anchor_set: dict[str, int],
    taxonomy: set[str],
    thresholds: Thresholds,
    now_year: int,
) -> Classification:
    """Return ANCHOR_INJECT / CONCEPT_INJECT / REJECT for a single work."""
    wid = (work.get("id") or "").rsplit("/", 1)[-1]

    # Anchor path
    if wid and anchor_set.get(wid, 0) >= thresholds.anchor_min_citers:
        return Classification.ANCHOR_INJECT

    # Concept path
    if not _has_ai_concept(work, taxonomy):
        return Classification.REJECT
    year = work.get("publication_year") or 0
    if year < thresholds.concept_min_year:
        return Classification.REJECT
    citations = work.get("cited_by_count") or 0
    age = now_year - year
    if age <= thresholds.recent_age_years:
        return (
            Classification.CONCEPT_INJECT
            if citations >= thresholds.concept_min_recent
            else Classification.REJECT
        )
    return (
        Classification.CONCEPT_INJECT
        if citations >= thresholds.concept_min_old
        else Classification.REJECT
    )
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_gap_filter.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/gap_filter.py tests/core/snapshot/test_gap_filter.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): gap_filter (ANCHOR / CONCEPT / REJECT classifier + 17 AI concepts)"
```

---

## Task 2: `phase3_gap_discovery.run()`

**Files:**
- Create: `src/core/snapshot/phase3_gap_discovery.py`
- Test: `tests/core/snapshot/test_phase3_gap_discovery.py`

**Interfaces:**
- Consumes: `gap_filter.{Classification, Thresholds, AI_CONCEPT_IDS, classify}`, `extractor.extract_full_record`, `work_source`, `checkpoint`, `embedding_queue`, `storage.{build_referenced_openalex_id_set, build_identifier_index_for_dedup, batch_inject_papers}`.
- Produces:
  ```python
  def run(storage, snapshot_dir: str, *, dry_run=False, batch_size=500,
          limit_files=None, max_injections: int | None = None,
          thresholds: Thresholds | None = None, now_year: int | None = None,
          checkpoint_root=None, embedding_queue_root=None) -> PhaseSummary
  def process_one(work, dedup_idx, anchor_set, *, storage, thresholds, now_year,
                  dry_run=False, embedding_queue_root=None) -> dict
  ```

- [ ] **Step 1: Write the failing L2 test.**

Create `tests/core/snapshot/test_phase3_gap_discovery.py`:

```python
from pathlib import Path

from src.core.snapshot import phase3_gap_discovery
from src.core.snapshot import embedding_queue

FIX = Path(__file__).parent / "fixtures"


def _setup(tmp_path):
    d = tmp_path / "data" / "works" / "updated_date=2024-01-01"
    d.mkdir(parents=True)
    (d / "part_0000.gz").write_bytes((FIX / "works" / "tiny.jsonl.gz").read_bytes())
    return tmp_path / "data" / "works"


def test_p3_injects_anchor_and_concept_gaps(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    snap = _setup(tmp_path)
    summary = phase3_gap_discovery.run(
        mock_storage, snapshot_dir=str(snap), now_year=2026,
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    # Work 7 (W1000000008) is the anchor; work 8 + 9 are concept-passes.
    assert summary.extra["anchor_inject"] >= 1
    assert summary.extra["concept_inject"] >= 1
    assert summary.extra["rejected"] >= 1
    # Injection appears in mock storage
    assert any(pl.get("injected_from_snapshot") for _, pl in mock_storage.scroll_payloads())


def test_p3_max_injections_caps(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    snap = _setup(tmp_path)
    summary = phase3_gap_discovery.run(
        mock_storage, snapshot_dir=str(snap), max_injections=1, now_year=2026,
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    assert summary.extra["anchor_inject"] + summary.extra["concept_inject"] == 1
    assert summary.extra["capped"] is True


def test_p3_dry_run_does_not_mutate(mock_storage, tmp_path):
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    snap = _setup(tmp_path)
    before = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    phase3_gap_discovery.run(
        mock_storage, snapshot_dir=str(snap), dry_run=True, now_year=2026,
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    after = {p: dict(pl) for p, pl in mock_storage.scroll_payloads()}
    assert before == after


def test_p3_skips_already_in_corpus(mock_storage, tmp_path):
    """If we already have a real paper with the same openalex_id, skip it."""
    mock_storage.seed_from_json(FIX / "corpus" / "seed_papers.json")
    # Plant the anchor work as an existing real paper
    mock_storage.set_payload("real-anchor", {
        "is_stub": False, "openalex_id": "W1000000008", "title": "anchor",
    })
    snap = _setup(tmp_path)
    summary = phase3_gap_discovery.run(
        mock_storage, snapshot_dir=str(snap), now_year=2026,
        checkpoint_root=tmp_path / "checkpoints",
        embedding_queue_root=tmp_path / "checkpoints",
    )
    # anchor inject must NOT happen — W1000000008 already in corpus
    assert summary.extra["anchor_inject"] == 0
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_phase3_gap_discovery.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement.**

Create `src/core/snapshot/phase3_gap_discovery.py`:

```python
"""P3: discover-corpus-gaps — inject hybrid-classified missing works as new real papers."""
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.core.snapshot import checkpoint as cp
from src.core.snapshot import embedding_queue
from src.core.snapshot import work_source
from src.core.snapshot.extractor import extract_full_record
from src.core.snapshot.gap_filter import (
    AI_CONCEPT_IDS,
    Classification,
    Thresholds,
    classify,
)
from src.core.snapshot.stats import PhaseSummary

logger = logging.getLogger(__name__)

PHASE = "p3"


def _wid(work: dict) -> str:
    return (work.get("id") or "").rsplit("/", 1)[-1]


def _already_in_corpus(work: dict, dedup_idx: dict[str, set[str]]) -> bool:
    wid = _wid(work)
    if wid and wid in dedup_idx["openalex_id"]:
        return True
    from src.core.snapshot.extractor import _norm_doi
    doi = _norm_doi(work.get("doi"))
    if doi and doi in dedup_idx["doi"]:
        return True
    return False


def process_one(
    work,
    dedup_idx,
    anchor_set,
    *,
    storage,
    thresholds: Thresholds,
    now_year: int,
    dry_run: bool = False,
    embedding_queue_root: Path | None = None,
) -> dict:
    if _already_in_corpus(work, dedup_idx):
        return {"action": "skip_existing"}

    cls = classify(work, anchor_set=anchor_set, taxonomy=AI_CONCEPT_IDS,
                   thresholds=thresholds, now_year=now_year)
    if cls is Classification.REJECT:
        return {"action": "reject"}

    if dry_run:
        return {"action": "would_inject", "classification": cls.value}

    fields = extract_full_record(work)
    if not fields.get("openalex_id"):
        return {"action": "no_oa_id"}
    result = storage.batch_inject_papers([{
        "openalex_id": fields["openalex_id"],
        "work_fields": fields,
        "injection_path": "anchor" if cls is Classification.ANCHOR_INJECT else "concept",
    }])
    r = result[0]
    if r["status"] == "created":
        # update in-process dedup index so a same-pass duplicate is caught
        dedup_idx["openalex_id"].add(fields["openalex_id"])
        if fields.get("abstract") and r.get("point_id"):
            embedding_queue.append(r["point_id"], source="injection",
                                   root=embedding_queue_root)
    return {"action": r["status"], "classification": cls.value,
            "point_id": r.get("point_id")}


def run(
    storage,
    snapshot_dir: str,
    *,
    dry_run: bool = False,
    batch_size: int = 500,
    limit_files: int | None = None,
    max_injections: int | None = None,
    thresholds: Thresholds | None = None,
    now_year: int | None = None,
    checkpoint_root: Path | None = None,
    embedding_queue_root: Path | None = None,
) -> PhaseSummary:
    t0 = time.time()
    summary = PhaseSummary(phase=PHASE)
    done = cp.load(PHASE, root=checkpoint_root)
    thresholds = thresholds or Thresholds()
    now_year = now_year or datetime.now(timezone.utc).year

    dedup_idx = storage.build_identifier_index_for_dedup()
    anchor_set = storage.build_referenced_openalex_id_set()

    counters = Counter()
    year_counter = Counter()
    concept_counter = Counter()
    current_file: str | None = None
    files_done = 0
    capped = False

    for fp, work in work_source.iter_snapshot_works(snapshot_dir, skip_files=done):
        if fp != current_file:
            if current_file is not None:
                cp.mark_done(PHASE, current_file, root=checkpoint_root)
                files_done += 1
                if limit_files is not None and files_done >= limit_files:
                    break
            current_file = fp
        summary.scanned += 1
        try:
            res = process_one(
                work, dedup_idx, anchor_set,
                storage=storage, thresholds=thresholds, now_year=now_year,
                dry_run=dry_run, embedding_queue_root=embedding_queue_root,
            )
            action = res.get("action")
            cls = res.get("classification")

            if action == "skip_existing":
                counters["skip_existing"] += 1
            elif action == "reject":
                counters["rejected"] += 1
            elif action == "created" or action == "would_inject":
                if cls == "ANCHOR_INJECT":
                    counters["anchor_inject"] += 1
                else:
                    counters["concept_inject"] += 1
                if year := work.get("publication_year"):
                    year_counter[year] += 1
                for c in work.get("concepts") or []:
                    cid = (c.get("id") or "").rsplit("/", 1)[-1]
                    if cid and cid in AI_CONCEPT_IDS:
                        concept_counter[c.get("display_name") or cid] += 1
                if action == "created":
                    summary.applied += 1
                total_inject = counters["anchor_inject"] + counters["concept_inject"]
                if max_injections is not None and total_inject >= max_injections:
                    capped = True
                    break
            elif action in ("skipped_dup", "failed", "no_oa_id"):
                counters[action] += 1
        except Exception as e:
            summary.worker_errors += 1
            cp.quarantine(PHASE, work, str(e), root=checkpoint_root)
            summary.quarantined += 1
            if summary.worker_errors % 100 == 1:
                logger.warning("p3 worker error: %s", e)

    if current_file is not None and not capped:
        cp.mark_done(PHASE, current_file, root=checkpoint_root)
        files_done += 1

    summary.matched = counters["anchor_inject"] + counters["concept_inject"]
    summary.duration_s = time.time() - t0
    summary.extra = {
        "files_done": files_done,
        "anchor_inject": counters["anchor_inject"],
        "concept_inject": counters["concept_inject"],
        "rejected": counters["rejected"],
        "skip_existing": counters["skip_existing"],
        "skipped_dup": counters["skipped_dup"],
        "failed": counters["failed"],
        "no_oa_id": counters["no_oa_id"],
        "queued_for_embed": summary.applied,
        "year_distribution": dict(year_counter.most_common(20)),
        "top_concepts": dict(concept_counter.most_common(10)),
        "capped": capped,
    }
    logger.info(summary.to_log_line())
    return summary
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_phase3_gap_discovery.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/phase3_gap_discovery.py tests/core/snapshot/test_phase3_gap_discovery.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): P3 phase3_gap_discovery (anchor+concept injection, cap-able)"
```

---

## Task 3: CLI — `discover-corpus-gaps`

**Files:**
- Modify: `src/cli/commands/snapshot.py`
- Test: `tests/core/snapshot/test_cli_p3_and_ops.py`

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_cli_p3_and_ops.py`:

```python
from click.testing import CliRunner

from src.cli.core_collect import cli


def test_p3_command_registered():
    runner = CliRunner()
    res = runner.invoke(cli, ["discover-corpus-gaps", "--help"])
    assert res.exit_code == 0
    for opt in ("anchor-min-citers", "concept-min-recent", "concept-min-old",
                "concept-min-year", "max-injections"):
        assert opt in res.output, f"missing option {opt}"
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_cli_p3_and_ops.py::test_p3_command_registered -v
```

Expected: `Error: No such command`.

- [ ] **Step 3: Add the command.**

Append to `src/cli/commands/snapshot.py`:

```python
    @cli.command("discover-corpus-gaps")
    @click.option("--snapshot-dir",
                  default="/mnt/nfs/ssd2/openalex_snapshot/data/works")
    @click.option("--batch-size", type=int, default=500)
    @click.option("--dry-run", is_flag=True)
    @click.option("--resume/--no-resume", default=True)
    @click.option("--limit-files", type=int, default=None)
    @click.option("--anchor-min-citers", type=int, default=2)
    @click.option("--concept-min-recent", type=int, default=50)
    @click.option("--concept-min-old", type=int, default=200)
    @click.option("--concept-min-year", type=int, default=2018)
    @click.option("--max-injections", type=int, default=None,
                  help="Stop after this many injections (safety cap).")
    def discover_corpus_gaps(snapshot_dir, batch_size, dry_run, resume, limit_files,
                              anchor_min_citers, concept_min_recent, concept_min_old,
                              concept_min_year, max_injections):
        """Discover snapshot works missing from the corpus, classify as
        anchor-citation or AI-concept-high-impact, inject as new real papers."""
        from src.core.snapshot import phase3_gap_discovery
        from src.core.snapshot import checkpoint as cp
        from src.core.snapshot.gap_filter import Thresholds
        from src.core.storage import QdrantStorage
        storage = QdrantStorage()
        if not resume:
            cp.reset("p3")
        thresholds = Thresholds(
            anchor_min_citers=anchor_min_citers,
            concept_min_recent=concept_min_recent,
            concept_min_old=concept_min_old,
            concept_min_year=concept_min_year,
        )
        summary = phase3_gap_discovery.run(
            storage, snapshot_dir=snapshot_dir, batch_size=batch_size,
            dry_run=dry_run, limit_files=limit_files,
            max_injections=max_injections, thresholds=thresholds,
        )
        click.echo(summary.to_log_line())
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_cli_p3_and_ops.py::test_p3_command_registered -v
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/cli/commands/snapshot.py tests/core/snapshot/test_cli_p3_and_ops.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(cli): discover-corpus-gaps (P3 trigger, threshold + cap options)"
```

---

## Task 4: Operational CLI — `snapshot-status`, `snapshot-reset`, `snapshot-replay-failed`

**Files:**
- Modify: `src/cli/commands/snapshot.py`
- Modify: `tests/core/snapshot/test_cli_p3_and_ops.py`

- [ ] **Step 1: Append failing tests.**

Append to `tests/core/snapshot/test_cli_p3_and_ops.py`:

```python
def test_snapshot_status_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["snapshot-status", "--help"])
    assert res.exit_code == 0


def test_snapshot_reset_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["snapshot-reset", "--help"])
    assert res.exit_code == 0
    assert "--phase" in res.output
    assert "--confirm" in res.output


def test_snapshot_replay_failed_help():
    runner = CliRunner()
    res = runner.invoke(cli, ["snapshot-replay-failed", "--help"])
    assert res.exit_code == 0
    assert "--phase" in res.output
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_cli_p3_and_ops.py -v
```

Expected: 3 new failures.

- [ ] **Step 3: Add the three commands.**

Append to `src/cli/commands/snapshot.py`:

```python
    @cli.command("snapshot-status")
    def snapshot_status():
        """Print checkpoint progress + embedding queue depth for all 4 phases."""
        from src.core.snapshot import checkpoint as cp
        from src.core.snapshot import embedding_queue
        import json
        for phase in ("p1", "p2", "p3", "p4"):
            done = cp.load(phase)
            click.echo(f"{phase}: {len(done)} files done")
            # Surface last_summary.json if it exists
            from pathlib import Path
            import os
            root = Path(os.environ.get("DAGSTER_HOME", str(Path.home()/"dagster_home"))) \
                   / "snapshot_checkpoints" / phase
            ls = root / "last_summary.json"
            if ls.exists():
                click.echo(f"  last: {ls.read_text().strip()}")
            q = root / "quarantine.jsonl"
            if q.exists():
                click.echo(f"  quarantine: {sum(1 for _ in q.open())} entries")
        click.echo(f"embedding_queue depth: {embedding_queue.depth()}")


    @cli.command("snapshot-reset")
    @click.option("--phase", type=click.Choice(["p1","p2","p3","p4"]), required=True)
    @click.option("--confirm", is_flag=True, help="Required to actually delete.")
    def snapshot_reset(phase, confirm):
        """Delete the per-phase checkpoint directory. Data is not touched (phases are idempotent)."""
        if not confirm:
            click.echo("Add --confirm to actually delete.", err=True)
            raise click.exceptions.Exit(1)
        from src.core.snapshot import checkpoint as cp
        cp.reset(phase)
        click.echo(f"reset {phase}")


    @cli.command("snapshot-replay-failed")
    @click.option("--phase", type=click.Choice(["p1","p2","p3","p4"]), required=True)
    @click.option("--quarantine", is_flag=True, help="Also replay quarantine.jsonl items.")
    def snapshot_replay_failed(phase, quarantine):
        """Re-attempt the failed_batches (and optionally quarantine) of a phase."""
        import json
        from pathlib import Path
        import os
        root = Path(os.environ.get("DAGSTER_HOME", str(Path.home()/"dagster_home"))) \
               / "snapshot_checkpoints" / phase
        d = root / "failed_batches"
        n = 0
        if d.exists():
            for f in sorted(d.glob("*.jsonl")):
                lines = f.read_text().splitlines()
                # We do not auto-reapply here — surface the items and let the operator
                # decide. (Auto-replay is too risky without root-cause analysis.)
                click.echo(f"{f.name}: {len(lines)} items")
                n += len(lines)
        if quarantine:
            qf = root / "quarantine.jsonl"
            if qf.exists():
                n_q = sum(1 for _ in qf.open())
                click.echo(f"quarantine.jsonl: {n_q} items")
                n += n_q
        click.echo(f"total items needing operator review: {n}")
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_cli_p3_and_ops.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add src/cli/commands/snapshot.py tests/core/snapshot/test_cli_p3_and_ops.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(cli): snapshot-status / -reset / -replay-failed (operational triad)"
```

---

## Task 5: `embed-papers --consume-snapshot-queue`

**Files:**
- Modify: `src/cli/commands/embedding.py`
- Test: `tests/core/snapshot/test_consume_snapshot_queue.py`

**Interfaces:** Adds option `--consume-snapshot-queue` (flag) to the existing `embed-papers` command. When set, the embedder pulls point IDs from `embedding_queue.drain()` instead of (or in addition to, before falling back to) the default `get_papers_for_embedding(skip_embedded=True)` scroll.

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_consume_snapshot_queue.py`:

```python
from click.testing import CliRunner

from src.cli.core_collect import cli


def test_embed_papers_consume_snapshot_queue_option():
    runner = CliRunner()
    res = runner.invoke(cli, ["embed-papers", "--help"])
    assert res.exit_code == 0
    assert "--consume-snapshot-queue" in res.output
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_consume_snapshot_queue.py -v
```

Expected: option not in output.

- [ ] **Step 3: Add the option + wiring.**

In `src/cli/commands/embedding.py`, locate the `embed_papers` command (around line 60) and:

1. Add the option decorator:
   ```python
   @click.option("--consume-snapshot-queue", is_flag=True,
                 help="Drain points queued by P2/P3 first; then fall through to the default scroll.")
   ```
2. Add `consume_snapshot_queue` to the function signature.
3. Inside the async `run()` body, before the existing `while True:` loop, insert:

```python
                if consume_snapshot_queue:
                    from src.core.snapshot import embedding_queue
                    queued = list(embedding_queue.drain())
                    if queued:
                        click.echo(f"Consuming {len(queued)} points from snapshot queue...")
                        # Build papers list by fetching payloads
                        pids = [pid for pid, _ in queued]
                        # Use storage to scroll specifically these points
                        from qdrant_client import models as m
                        pts, _ = storage.client.scroll(
                            collection_name=storage.collection_name,
                            scroll_filter=m.Filter(must=[m.HasIdCondition(has_id=pids)]),
                            with_payload=["title", "abstract", "abstract_structure"],
                            with_vectors=False, limit=len(pids),
                        )
                        papers = [(str(p.id), p.payload or {}) for p in pts]
                        if papers:
                            await embedder.embed_and_upsert_batch(
                                papers=papers, storage=storage,
                                embed_batch_size=embed_batch_size,
                            )
                            total_embedded += len(papers)
                            click.echo(f"  embedded {len(papers)} from queue")
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_consume_snapshot_queue.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/cli/commands/embedding.py tests/core/snapshot/test_consume_snapshot_queue.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(embedding): --consume-snapshot-queue (drain P2/P3 queue before default scroll)"
```

---

## Task 6: Dagster — `snapshot_discover_gaps` + reorder deps

**Files:**
- Modify: `src/orchestration/assets/snapshot.py`
- Modify: `src/orchestration/definitions.py`

- [ ] **Step 1: Edit `snapshot.py`.**

Add the asset and update P4's deps:

```python
from src.core.snapshot import phase3_gap_discovery


@asset(deps=[snapshot_resolve_stubs], group_name="snapshot")
def snapshot_discover_gaps(context: AssetExecutionContext) -> MaterializeResult:
    """P3: discover and inject hybrid-classified gap papers."""
    summary = phase3_gap_discovery.run(
        QdrantStorage(),
        snapshot_dir="/mnt/nfs/ssd2/openalex_snapshot/data/works",
    )
    context.log.info(summary.to_log_line())
    return MaterializeResult(metadata=summary.to_dagster_metadata())


# Update existing snapshot_extend_cited_by to depend on P3 too:
@asset(deps=[snapshot_discover_gaps], group_name="snapshot")
def snapshot_extend_cited_by(context: AssetExecutionContext) -> MaterializeResult:
    ...   # body unchanged
```

- [ ] **Step 2: Register in `definitions.py`.**

Add `_snapshot_assets.snapshot_discover_gaps` to the `assets=[...]` list.

- [ ] **Step 3: Validate.**

```bash
uv run dagster definitions validate -m src.orchestration.definitions
```

Expected: `All code locations passed validation.`

- [ ] **Step 4: Commit.**

```bash
git add src/orchestration/assets/snapshot.py src/orchestration/definitions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(orchestration): snapshot_discover_gaps asset (P3 in DAG)"
```

---

## Task 7: Pipeline doc — `docs/pipelines/corpus-gap-discovery.md`

**Files:**
- Create: `docs/pipelines/corpus-gap-discovery.md`

- [ ] **Step 1: Write the doc.**

Create `docs/pipelines/corpus-gap-discovery.md`:

````markdown
# Corpus Gap Discovery (P3)

P3 of the snapshot utilization system. Find OpenAlex works that are NOT in our
corpus but should be, and inject them as new real papers.

## Hybrid relevance — two paths

`src/core/snapshot/gap_filter.py:classify`:

| Path | Condition | Rationale |
|---|---|---|
| **ANCHOR_INJECT** | The work's OpenAlex ID appears in our corpus's `referenced_works` of ≥ `anchor_min_citers` (default 2) papers | Papers we already cite are by definition relevant to our research domain |
| **CONCEPT_INJECT** | The work has at least one `concepts[].id` in `AI_CONCEPT_IDS` AND `publication_year ≥ concept_min_year` (default 2018) AND `cited_by_count` meets the age-scaled threshold (default ≥50 for ≤5-year-old papers, ≥200 otherwise) | Cast a wider net: high-impact AI papers in venues we don't crawl |
| **REJECT** | Neither path matches | |

When both paths qualify, ANCHOR wins (recorded `injection_path = "anchor"`).

## AI concept taxonomy

`AI_CONCEPT_IDS` is a 17-element set of OpenAlex C-namespace IDs (Artificial
intelligence, Machine learning, Deep learning, NLP, Computer vision,
Reinforcement learning, Neural network, Generative model, Transformer,
Knowledge graph, Information retrieval, Recommender system, Robotics, Speech
recognition, Federated learning, Multi-agent system, Foundation model).

To update: fetch the latest tree under `C154945302` (Artificial intelligence)
from `https://api.openalex.org/concepts?filter=ancestors.id:C154945302` and
expand `AI_CONCEPT_IDS` with any new high-level IDs.

## Thresholds — how to tune

Defaults (in `Thresholds`):
- `anchor_min_citers = 2`
- `concept_min_recent = 50` (papers ≤ 5 years old)
- `concept_min_old = 200`
- `concept_min_year = 2018`

These are surfaced as CLI options. Bootstrap procedure:

```bash
# Day 6 dry-run with defaults
uv run python -m src.cli.core_collect discover-corpus-gaps --dry-run --limit-files 30
```

The dry-run prints `anchor_inject`, `concept_inject`, `rejected`,
`year_distribution`, and `top_concepts` — review:

- If `concept_inject / scanned` is too high (e.g. > 0.5%), raise
  `--concept-min-recent` to 100 and `--concept-min-old` to 400 and re-dry-run.
- If `anchor_inject` looks low, lower `--anchor-min-citers 1` (every paper we
  cite, even once).

Then run with `--max-injections 5000` for a first real pass to validate, then
without the cap for the full pass.

## Safety: the `--max-injections` cap

Always pass `--max-injections N` on the first real run. The phase
**short-circuits** when the cap is reached and records `extra["capped"]=True` in
the summary. Re-running without the cap will continue from the checkpoint of
the next unprocessed `.gz`.

## In-pass dedup

Each `process_one` checks against `dedup_idx` (built from the corpus at the
start) AND updates it after every successful injection. So a same-pass second
occurrence of the same DOI/openalex_id is skipped as `skipped_dup`.

## Provenance

Every injected point receives:

```
{
  "is_stub": false,
  "injected_from_snapshot": true,
  "injection_path": "anchor" | "concept",
  "injected_at": "<UTC ISO>",
  "snapshot_filled_at": "<UTC date>"
}
```

This makes it trivial to roll back a bad run by filtering on
`injected_from_snapshot=true AND injected_at >= <date>`.

## Cleanup procedure (bad run)

See `docs/runbooks/snapshot-rollback.md` for the script to remove a recent
batch of injections.
````

- [ ] **Step 2: Commit.**

```bash
git add docs/pipelines/corpus-gap-discovery.md
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "docs(pipeline): corpus-gap-discovery (hybrid rules, taxonomy, tuning, safety)"
```

---

## Task 8: Rollback runbook

**Files:**
- Create: `docs/runbooks/snapshot-rollback.md`

- [ ] **Step 1: Write the file.**

Create `docs/runbooks/snapshot-rollback.md`:

````markdown
# Snapshot Utilization — Rollback Runbook

When a phase produced wrong results and you need to undo it.

## Scenario 1 — wrong P2 promotions

Symptom: promoted points lack expected cited_by, or wrong stubs were promoted.

```bash
# Reset the phase checkpoint
uv run python -m src.cli.core_collect snapshot-reset --phase p2 --confirm

# Identify promoted points from the affected window
uv run python -c "
from src.core.storage import QdrantStorage
from qdrant_client import models as m
st = QdrantStorage()
flt = m.Filter(must=[m.FieldCondition(key='promoted_from_stub', match=m.MatchValue(value=True))])
pts, _ = st.client.scroll(st.collection_name, scroll_filter=flt, limit=10000,
                          with_payload=['promoted_at','cited_by','title'])
for p in pts:
    print(str(p.id), p.payload.get('promoted_at'), p.payload.get('title'))
" > /tmp/promoted_audit.tsv
```

Manual review of `/tmp/promoted_audit.tsv`. To re-stub a wrong promotion
(restore `is_stub=True`, clear `promoted_from_stub`):

```python
storage.client.set_payload(
    collection_name=storage.collection_name,
    payload={"is_stub": True, "promoted_from_stub": False},
    points=[bad_point_id],
)
```

(Note: this is destructive at the payload level. Take a Qdrant snapshot first.)

## Scenario 2 — P3 injection runaway

Symptom: thousands of low-quality injections in the last run.

```bash
# Identify the bad batch by date
uv run python -c "
from src.core.storage import QdrantStorage
from qdrant_client import models as m
st = QdrantStorage()
flt = m.Filter(must=[
    m.FieldCondition(key='injected_from_snapshot', match=m.MatchValue(value=True)),
    m.FieldCondition(key='injected_at', range=m.Range(gte='2026-06-21T00:00:00Z')),
])
pts, _ = st.client.scroll(st.collection_name, scroll_filter=flt, limit=10000,
                          with_payload=False)
print('to_delete:', len(pts))
ids = [str(p.id) for p in pts]
print(ids[:5])
" 
```

Then delete:

```python
storage.client.delete(
    collection_name=storage.collection_name,
    points_selector=models.PointIdsList(points=ids),
)
```

Re-run P3 with stricter thresholds:

```bash
uv run python -m src.cli.core_collect snapshot-reset --phase p3 --confirm
uv run python -m src.cli.core_collect discover-corpus-gaps \
    --concept-min-recent 100 --concept-min-old 400 --max-injections 3000
```

## Scenario 3 — Qdrant data corruption

All snapshot phases are idempotent (`fill-only-missing` + provenance + dedup).
After restoring the Qdrant snapshot:

```bash
uv run python -m src.cli.core_collect snapshot-reset --phase p1 --confirm
uv run python -m src.cli.core_collect snapshot-reset --phase p2 --confirm
uv run python -m src.cli.core_collect snapshot-reset --phase p3 --confirm
uv run python -m src.cli.core_collect snapshot-reset --phase p4 --confirm
# Now rerun in order
uv run python -m src.cli.core_collect enrich-corpus-fields
uv run python -m src.cli.core_collect resolve-stubs-from-snapshot
uv run python -m src.cli.core_collect discover-corpus-gaps
uv run python -m src.cli.core_collect embed-papers --consume-snapshot-queue
uv run python -m src.cli.core_collect extend-cited-by-from-snapshot
```

## Scenario 4 — embedding queue lost

If the on-disk `embedding_queue.jsonl` was deleted/corrupted, reconstruct from
the corpus state:

```bash
uv run python -c "
from src.core.storage import QdrantStorage
from src.core.snapshot import embedding_queue
from qdrant_client import models as m
st = QdrantStorage()
flt = m.Filter(
    should=[
        m.FieldCondition(key='promoted_from_stub', match=m.MatchValue(value=True)),
        m.FieldCondition(key='injected_from_snapshot', match=m.MatchValue(value=True)),
    ],
    must_not=[
        m.HasVectorCondition(has_vector='structured-abstract'),
        m.IsEmptyCondition(is_empty=m.PayloadField(key='abstract')),
    ],
)
pts, _ = st.client.scroll(st.collection_name, scroll_filter=flt, limit=10000,
                          with_payload=False)
for p in pts:
    embedding_queue.append(str(p.id), source='reconstructed')
print('requeued:', len(pts))
"
```
````

- [ ] **Step 2: Commit.**

```bash
git add docs/runbooks/snapshot-rollback.md
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "docs(runbook): snapshot-rollback (4 scenarios — promotion, injection, corruption, queue)"
```

---

## Task 9: Bootstrap runbook — Day 6 P3 section + Day 7-9 drain note

**Files:**
- Modify: `docs/runbooks/snapshot-bootstrap.md`

- [ ] **Step 1: Replace the Day 6 placeholder.**

In `docs/runbooks/snapshot-bootstrap.md`, replace the "Day 6 — P3 (covered in the separate Plan 4 runbook section)" line with:

````markdown
## Day 6 — P3 dry-run + staged real run

### Dry-run on a slice

```bash
uv run python -m src.cli.core_collect discover-corpus-gaps \
    --dry-run --limit-files 30
```

Inspect:
- `anchor_inject / scanned` — should be a small fraction of a percent
- `concept_inject / scanned` — likewise; tune `--concept-min-recent` / `--concept-min-old`
  if too high
- `year_distribution` — heavy 2022–2025 expected, very few pre-2018 (the floor)
- `top_concepts` — should match your AI focus

### Capped real run

```bash
uv run python -m src.cli.core_collect discover-corpus-gaps --max-injections 5000
```

Review the summary line and verify a sample of injected points in the search UI.

### Full run (after the capped run looks healthy)

```bash
uv run python -m src.cli.core_collect snapshot-reset --phase p3 --confirm
uv run python -m src.cli.core_collect discover-corpus-gaps
```

Expected duration: ≈4–8 hours.

## Day 7-9 — drain P3 embedding queue

Same procedure as Day 4-5 after P2:

```bash
uv run python -m src.cli.core_collect snapshot-status   # check queue depth
uv run python -m src.cli.core_collect embed-papers --consume-snapshot-queue
```
````

- [ ] **Step 2: Commit.**

```bash
git add docs/runbooks/snapshot-bootstrap.md
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "docs(runbook): Day 6 P3 (dry-run, capped, full) + Day 7-9 drain"
```

---

## Task 10: Final verification

- [ ] **Step 1: Full test suite.**

```bash
uv run --extra dev pytest tests/core/snapshot/ -v -m "not snapshot_live and not integration"
```

Expected: all pass.

- [ ] **Step 2: Integration tests (if Qdrant available).**

```bash
uv run --extra dev pytest tests/core/snapshot/ -v -m integration
```

Expected: pass or graceful skip.

- [ ] **Step 3: Dagster validate.**

```bash
uv run dagster definitions validate -m src.orchestration.definitions
```

Expected: `All code locations passed validation.`

- [ ] **Step 4: CLI smoke for all new commands.**

```bash
for cmd in discover-corpus-gaps snapshot-status snapshot-reset snapshot-replay-failed; do
    uv run python -m src.cli.core_collect $cmd --help >/dev/null && echo "$cmd: OK" || echo "$cmd: FAIL"
done
uv run python -m src.cli.core_collect embed-papers --help | grep -q consume-snapshot-queue \
    && echo "embed-papers --consume-snapshot-queue: OK" || echo "FAIL"
```

Expected: all OK.

- [ ] **Step 5: Asset list — all 4 snapshot assets registered.**

```bash
uv run dagster asset list -m src.orchestration.definitions | grep snapshot_
```

Expected: 4 lines.

- [ ] **Step 6: Final smoke — run a small slice end-to-end against mock_storage to confirm the pipes connect.**

```bash
uv run --extra dev pytest tests/core/snapshot/ -v
```

Expected: all pass.

---

## Plan 4 Self-Review Notes

- **Spec §5 P3 logic:** Task 2 implements the full prepare→stream→classify→inject→cap→summary skeleton with `year_distribution` and `top_concepts` extras. In-pass dedup updates `dedup_idx` after each successful injection.
- **Spec §9 CLI:** Task 3 matches the option signatures from §9. Task 4 adds the operational triad (`snapshot-status`, `snapshot-reset`, `snapshot-replay-failed`).
- **Spec §9 embed-papers extension:** Task 5 adds `--consume-snapshot-queue` to drain P2/P3-queued points before the default scroll.
- **Spec §9 Dagster:** Task 6 adds `snapshot_discover_gaps` between P2 and P4 in the DAG.
- **Spec §11 docs:** `docs/pipelines/corpus-gap-discovery.md` (Task 7) + `docs/runbooks/snapshot-rollback.md` (Task 8) + bootstrap Day 6 section (Task 9) satisfy the same-PR documentation rule.
- **Spec §13 R2 (injection runaway):** `--max-injections N` short-circuits the run, records `extra["capped"]=True`. Rollback procedure documented in Task 8.
- **Spec §14 open question (taxonomy IDs):** answered with 17 hardcoded OpenAlex C-namespace IDs in Task 1 (with the update procedure documented in Task 7).
- **Type consistency:** `Classification` enum, `Thresholds` dataclass, and `process_one`/`run` signatures match between `gap_filter.py`, `phase3_gap_discovery.py`, and the CLI command.
- **Cross-plan consistency:** all 4 phases (`p1`/`p2`/`p3`/`p4`) share the same `PhaseSummary` shape (Plan 1), same `checkpoint` module (Plan 1), same `embedding_queue` module (Plan 1), same `process_one(work, ...)` shape for the future live-mode worker (Plan 5).
