# OpenAlex Snapshot — Offline Resolution & Enrichment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bulk-enrich the existing corpus backlog (abstracts, `referenced_works`, metadata) from a local OpenAlex `works` snapshot via a single resumable streaming pass, eliminating the rate-limited `/works?search=` dependency for the backlog.

**Architecture:** A streaming-join batch: build an in-memory index of corpus papers that need enrichment (keyed by DOI and normalized title), stream the snapshot's gzip-JSONL `works` files line-by-line, match each work (DOI = trusted; title = gated by year/author corroboration), and **fill-only-missing** the matched paper's fields in Qdrant with a provenance tag. Pure matching logic is isolated and unit-tested; the streaming orchestrator handles I/O, checkpointing, and writes.

**Tech Stack:** Python 3.12, uv, Qdrant, the OpenAlex public S3 snapshot (`aws s3 sync --no-sign-request`), pytest. Tests: `uv run --extra dev pytest`.

**Scope note:** Implements spec `docs/superpowers/specs/2026-06-18-openalex-snapshot-offline-resolution-design.md`. Non-stub real papers only (the title-search bottleneck was real no-DOI papers; stubs are enriched by the un-throttled by-ID `enrich-8`). `works` entity only. No persistent index, no fuzzy matching. A Dagster asset wrapper is a trivial later add (the module entry function is the shared callable).

---

## Conventions (every task)
- Test command: `uv run --extra dev pytest <args>` (pytest is in the `dev` extra; plain `uv run pytest` fails).
- TDD: write the failing test, run it (confirm the expected failure), implement, run (confirm pass), commit.
- Commits: `git commit --author="rabqatab <minhan.nick.cho@gmail.com>" -m "..."`. NEVER add a `Co-Authored-By` trailer or "Generated with Claude Code" line. Verify after: `git log -1 --format="%B" | grep -i "co-authored"` returns nothing. `tests/` is NOT gitignored (plain `git add`).
- DRY / YAGNI: reuse the verified existing helpers below; don't rebuild them.

## Verified facts (2026-06-18 grounding)
- **Title normalization:** `from src.core.deduplication import Deduplicator` → `Deduplicator.normalize_title(title) -> str` (`src/core/deduplication.py:134`). This is the SAME normalization the resolver uses for title→point_id, so snapshot keys will match corpus keys. Use it for all `title_norm`.
- **Abstract reconstruction:** `_reconstruct_abstract(self, inverted_index)` exists at `src/core/crawler/openalex.py:692` as a method — Task 1 refactors it to a module-level `reconstruct_abstract(inverted_index)` for reuse.
- **Writer helpers:** `src/core/storage/writer.py` has `batch_update_abstracts`, `batch_update_referenced_works` (and others). Task 4 adds `batch_apply_snapshot_enrichment` for a single fill+provenance write per point.
- **Counts/scroll:** `storage.count_real_papers()` exists (`src/core/storage/stubs.py:406`). Reader getters like `get_papers_missing_abstracts` / `get_papers_without_doi_missing_references` exist; Task 2 adds a focused `iter_enrichment_candidates()` scroll.
- **Checkpointing:** `from src.core.checkpoint_mixin import CheckpointMixin` (`src/core/checkpoint_mixin.py`) — `_load_checkpoint(ProgressClass)` / `_save_checkpoint(progress)`; subclass sets `checkpoint_dir` + `_get_checkpoint_file()`.
- **Snapshot source:** `aws s3 sync "s3://openalex/data/works" <dest>/data/works --no-sign-request` (anonymous, no creds). Layout: `works/manifest` + `updated_date=YYYY-MM-DD/NNNN_part_NN.gz` (gzip JSON Lines, one work per line). Store under `/mnt/nfs/ssd2/openalex_snapshot/` (1.7 TB free). **`aws` CLI is NOT installed** — Task 6 installs it via `uv tool install awscli`.
- **Payload field names:** `doi`, `title`, `abstract`, `referenced_works`, `publication_year`/`year`, `authorships`/authors, `is_stub`. (Confirm `year` vs `publication_year` on our payloads when implementing Task 2.)

---

## File Structure
- Create `src/core/snapshot/__init__.py`
- Create `src/core/snapshot/matcher.py` — `Candidate`, `build_candidate_index`, `match_work`, `extract_enrichment` (pure, unit-tested)
- Create `src/core/snapshot/runner.py` — `run_snapshot_enrichment(...)` streaming orchestrator (the shared entry function)
- Modify `src/core/crawler/openalex.py` — extract module-level `reconstruct_abstract(inverted_index)`; method delegates
- Modify `src/core/storage/reader.py` — add `iter_enrichment_candidates()`
- Modify `src/core/storage/writer.py` — add `batch_apply_snapshot_enrichment()`
- Create `src/cli/commands/snapshot.py` — `enrich-from-openalex-snapshot` CLI command (registered like other command modules)
- Create `scripts/snapshot/fetch_openalex_snapshot.sh` — `aws s3 sync` works only
- Tests: `tests/core/snapshot/__init__.py`, `tests/core/snapshot/test_matcher.py`, `tests/core/snapshot/test_runner.py`

---

## Task 1: Extract a reusable `reconstruct_abstract` helper

**Files:** Modify `src/core/crawler/openalex.py`; Test: `tests/core/snapshot/__init__.py`, `tests/core/snapshot/test_matcher.py` (start the file).

- [ ] **Step 1: Write the failing test.** Create `tests/core/snapshot/__init__.py` (empty) and `tests/core/snapshot/test_matcher.py`:
```python
from src.core.crawler.openalex import reconstruct_abstract


def test_reconstruct_abstract_from_inverted_index():
    inv = {"Hello": [0], "world": [1], "foo": [2]}
    assert reconstruct_abstract(inv) == "Hello world foo"


def test_reconstruct_abstract_none():
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None
```

- [ ] **Step 2: Run, confirm fail** (`ImportError: cannot import name 'reconstruct_abstract'`):
`uv run --extra dev pytest tests/core/snapshot/test_matcher.py -k reconstruct -v`

- [ ] **Step 3: Refactor.** In `src/core/crawler/openalex.py`, add a module-level function (top level, near the other module functions) and make the existing method delegate. Read the current method body at `_reconstruct_abstract` (line ~692) and move its logic verbatim into:
```python
def reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Reconstruct plain-text abstract from an OpenAlex abstract_inverted_index."""
    if not inverted_index:
        return None
    try:
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        return " ".join(word for _, word in word_positions)
    except Exception:
        return None
```
Then change the method to delegate:
```python
    def _reconstruct_abstract(self, inverted_index: dict | None) -> str | None:
        """Reconstruct abstract from OpenAlex inverted index format."""
        return reconstruct_abstract(inverted_index)
```
> Execution note: copy the EXACT existing body (it may differ slightly from above — read lines 692–710 first and preserve its exact behavior). The point is one shared implementation.

- [ ] **Step 4: Run, confirm pass.** Also run the crawler's existing tests if any reference abstract reconstruction: `uv run --extra dev pytest tests/ -k abstract -q` (no regressions).

- [ ] **Step 5: Commit** (`refactor(openalex): extract reusable reconstruct_abstract helper`).

---

## Task 2: `iter_enrichment_candidates` reader scroll

**Files:** Modify `src/core/storage/reader.py`; Test: `tests/core/snapshot/test_runner.py` (start the file).

Scroll non-stub papers that are missing an abstract OR missing referenced_works, yielding the fields the matcher needs.

- [ ] **Step 1: Write the failing test.** Create `tests/core/snapshot/test_runner.py`:
```python
from unittest.mock import MagicMock
from src.core.storage.reader import QdrantReaderMixin  # adjust to actual class if different


def test_iter_enrichment_candidates_yields_fields(monkeypatch):
    # Two scroll pages then empty; each point has payload we care about
    pt = MagicMock()
    pt.id = "p1"
    pt.payload = {"doi": "10.1/x", "title": "A Title", "year": 2020,
                  "authorships": [{"author": {"display_name": "Jane Doe"}}],
                  "abstract": "", "referenced_works": []}
    storage = MagicMock()
    storage.client.scroll.side_effect = [([pt], "off1"), ([], None)]
    storage.collection_name = "c"

    rows = list(QdrantReaderMixin.iter_enrichment_candidates(storage, batch_size=10))
    assert rows[0]["point_id"] == "p1"
    assert rows[0]["doi"] == "10.1/x"
    assert rows[0]["title"] == "A Title"
    assert rows[0]["missing_abstract"] is True
    assert rows[0]["missing_refs"] is True
```
> Execution note: FIRST read `src/core/storage/reader.py` to get the exact mixin/class name and the existing scroll pattern (how other getters call `storage.client.scroll` with filter + offset). Match that pattern exactly; adapt the test's class reference and the scroll-return shape to the real qdrant-client API used in the file (it may return `(points, next_offset)`).

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement** `iter_enrichment_candidates` in `reader.py`, following the existing scroll idiom in that file. It scrolls non-stub papers where (`abstract` IsEmpty OR `referenced_works` IsEmpty) and yields a dict per paper:
```python
def iter_enrichment_candidates(self, batch_size: int = 1000):
    """Yield non-stub papers missing an abstract and/or referenced_works.

    Yields dicts: {point_id, doi, title, year, first_author, missing_abstract, missing_refs}.
    """
    flt = models.Filter(
        must_not=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))],
        should=[
            models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract")),
            models.IsEmptyCondition(is_empty=models.PayloadField(key="referenced_works")),
        ],
    )
    offset = None
    while True:
        points, offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=flt,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break
        for pt in points:
            p = pt.payload or {}
            abstract = p.get("abstract") or ""
            refs = p.get("referenced_works") or []
            first_author = _first_author_surname(p)   # helper below
            yield {
                "point_id": str(pt.id),
                "doi": p.get("doi") or None,
                "title": p.get("title") or "",
                "year": p.get("year") or p.get("publication_year"),
                "first_author": first_author,
                "missing_abstract": not abstract,
                "missing_refs": not refs,
            }
        if offset is None:
            break
```
Add a small module-level helper `_first_author_surname(payload)` that extracts the first author's surname from whatever author shape our payloads use (read an existing paper's payload to confirm the shape — `authors` list of names, or `authorships`). Keep it defensive (return None if absent).
> Execution note: confirm `models` is imported in reader.py (it is — used by other getters). Confirm `should=[IsEmpty, IsEmpty]` semantics (OR) on this qdrant-client version; if `should` needs `min_should`, set it. Confirm the real author payload field by reading one stored paper.

- [ ] **Step 4: Run, confirm pass.** **Step 5: Commit** (`feat(storage): iter_enrichment_candidates scroll for snapshot matching`).

---

## Task 3: Matcher — candidate index, work matching, corroboration

**Files:** Create `src/core/snapshot/__init__.py`, `src/core/snapshot/matcher.py`; Test: `tests/core/snapshot/test_matcher.py` (append).

- [ ] **Step 1: Write the failing tests.** Append to `tests/core/snapshot/test_matcher.py`:
```python
from src.core.snapshot.matcher import (
    Candidate, build_candidate_index, match_work, extract_enrichment,
)


def _cands():
    return [
        {"point_id": "d1", "doi": "10.1/x", "title": "Deep Nets", "year": 2019,
         "first_author": "smith", "missing_abstract": True, "missing_refs": False},
        {"point_id": "t1", "doi": None, "title": "Graph Models", "year": 2021,
         "first_author": "lee", "missing_abstract": True, "missing_refs": True},
    ]


def test_doi_match_is_trusted():
    doi_map, title_map = build_candidate_index(_cands())
    work = {"doi": "https://doi.org/10.1/x", "title": "totally different",
            "publication_year": 1900, "authorships": []}
    m = match_work(work, doi_map, title_map)
    assert m is not None and m.candidate.point_id == "d1" and m.source == "doi"


def test_title_match_requires_corroboration_year():
    doi_map, title_map = build_candidate_index(_cands())
    # same normalized title, year within +/-1 -> accept
    work = {"doi": None, "title": "Graph Models", "publication_year": 2021,
            "authorships": [{"author": {"display_name": "K. Park"}}]}
    m = match_work(work, doi_map, title_map)
    assert m is not None and m.candidate.point_id == "t1" and m.source == "title"


def test_title_match_rejected_without_corroboration():
    doi_map, title_map = build_candidate_index(_cands())
    # same title but year far off AND different author -> reject
    work = {"doi": None, "title": "Graph Models", "publication_year": 2005,
            "authorships": [{"author": {"display_name": "Q. Zhang"}}]}
    assert match_work(work, doi_map, title_map) is None


def test_extract_enrichment_fill_flags():
    cand = Candidate("t1", 2021, "lee", missing_abstract=True, missing_refs=True)
    work = {"abstract_inverted_index": {"Hi": [0], "there": [1]},
            "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"]}
    out = extract_enrichment(work, cand)
    assert out["abstract"] == "Hi there"
    assert out["referenced_works"] == ["https://openalex.org/W1", "https://openalex.org/W2"]
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement `src/core/snapshot/matcher.py`:**
```python
"""Pure matching logic for OpenAlex-snapshot offline enrichment."""

from dataclasses import dataclass

from src.core.deduplication import Deduplicator
from src.core.crawler.openalex import reconstruct_abstract


@dataclass
class Candidate:
    point_id: str
    year: int | None
    first_author: str | None
    missing_abstract: bool
    missing_refs: bool


@dataclass
class Match:
    candidate: Candidate
    source: str  # "doi" | "title"


def _norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d or None


def _work_first_author(work: dict) -> str | None:
    auths = work.get("authorships") or []
    if not auths:
        return None
    name = (auths[0].get("author") or {}).get("display_name") or ""
    parts = name.strip().split()
    return parts[-1].lower() if parts else None


def build_candidate_index(candidates: list[dict]):
    """Return (doi_map, title_map). doi_map: doi->Candidate; title_map: title_norm->list[Candidate]."""
    doi_map: dict[str, Candidate] = {}
    title_map: dict[str, list[Candidate]] = {}
    for c in candidates:
        cand = Candidate(c["point_id"], c.get("year"), c.get("first_author"),
                         c["missing_abstract"], c["missing_refs"])
        d = _norm_doi(c.get("doi"))
        if d:
            doi_map[d] = cand
        tnorm = Deduplicator.normalize_title(c.get("title") or "")
        if tnorm:
            title_map.setdefault(tnorm, []).append(cand)
    return doi_map, title_map


def _corroborates(work: dict, cand: Candidate) -> bool:
    wy = work.get("publication_year") or work.get("year")
    if wy and cand.year and abs(int(wy) - int(cand.year)) <= 1:
        return True
    wa = _work_first_author(work)
    if wa and cand.first_author and wa == cand.first_author:
        return True
    return False


def match_work(work: dict, doi_map, title_map) -> Match | None:
    d = _norm_doi(work.get("doi") or (work.get("ids") or {}).get("doi"))
    if d and d in doi_map:
        return Match(doi_map[d], "doi")
    tnorm = Deduplicator.normalize_title(work.get("title") or "")
    if tnorm and tnorm in title_map:
        for cand in title_map[tnorm]:
            if _corroborates(work, cand):
                return Match(cand, "title")
    return None


def extract_enrichment(work: dict, cand: Candidate) -> dict:
    """Return only the fields this candidate is MISSING (fill-only-missing)."""
    out: dict = {}
    if cand.missing_abstract:
        abs = reconstruct_abstract(work.get("abstract_inverted_index"))
        if abs:
            out["abstract"] = abs
    if cand.missing_refs:
        refs = work.get("referenced_works") or []
        if refs:
            out["referenced_works"] = refs
    return out
```
> Execution note: confirm `Deduplicator.normalize_title` is a `@staticmethod`/classmethod callable as `Deduplicator.normalize_title(s)` (grounding says yes, `src/core/deduplication.py:134`). The OpenAlex work `doi` field is usually a full URL (`https://doi.org/...`); `ids.doi` is the same — `_norm_doi` handles it.

- [ ] **Step 4: Run, confirm pass.** **Step 5: Commit** (`feat(snapshot): matcher with DOI/title corroboration + fill-only extraction`).

---

## Task 4: Writer — `batch_apply_snapshot_enrichment`

**Files:** Modify `src/core/storage/writer.py`; Test: append to `tests/core/snapshot/test_runner.py`.

One `set_payload` per point that writes the provided enrichment fields **plus** a provenance tag.

- [ ] **Step 1: Write the failing test.** Append to `tests/core/snapshot/test_runner.py`:
```python
def test_batch_apply_snapshot_enrichment_sets_payload_and_provenance():
    from src.core.storage.writer import QdrantWriterMixin  # adjust to real class
    storage = MagicMock(); storage.collection_name = "c"
    updates = [("p1", {"abstract": "hi"}), ("p2", {"referenced_works": ["W1"]})]
    n = QdrantWriterMixin.batch_apply_snapshot_enrichment(storage, updates)
    assert n == 2
    # each call set_payload with the field + provenance
    calls = storage.client.set_payload.call_args_list
    assert any("abstract" in c.kwargs["payload"] for c in calls)
    assert all(c.kwargs["payload"].get("enrichment_source") == "openalex_snapshot" for c in calls)
```
> Execution note: read `src/core/storage/writer.py` for the exact mixin/class name and the existing `set_payload` call signature used by sibling methods (e.g. `batch_update_abstracts`); match it (kwargs vs positional).

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement** in `writer.py` (mirror the existing batch_update_* methods' structure):
```python
def batch_apply_snapshot_enrichment(self, updates: list[tuple[str, dict]]) -> int:
    """Fill snapshot-sourced fields + provenance for each (point_id, fields) update.

    Only the provided keys are set (fill-only-missing is decided upstream by the matcher).
    """
    applied = 0
    for point_id, fields in updates:
        if not fields:
            continue
        payload = {**fields, "enrichment_source": "openalex_snapshot"}
        self.client.set_payload(
            collection_name=self.collection_name,
            payload=payload,
            points=[point_id],
        )
        applied += 1
    return applied
```

- [ ] **Step 4: Run, confirm pass.** **Step 5: Commit** (`feat(storage): batch_apply_snapshot_enrichment with provenance`).

---

## Task 5: Streaming runner (stream .gz works → match → write, with checkpoint + dry-run)

**Files:** Create `src/core/snapshot/runner.py`; Test: append to `tests/core/snapshot/test_runner.py`.

- [ ] **Step 1: Write the failing test.** Append:
```python
import gzip, json
from unittest.mock import MagicMock, patch
from src.core.snapshot import runner


def _write_gz(tmp_path, works):
    f = tmp_path / "updated_date=2020-01-01"
    f.mkdir(parents=True)
    gz = f / "0000_part_00.gz"
    with gzip.open(gz, "wt", encoding="utf-8") as fh:
        for w in works:
            fh.write(json.dumps(w) + "\n")
    return tmp_path


def test_runner_matches_and_writes(tmp_path):
    works = [
        {"doi": "https://doi.org/10.1/x", "title": "x", "publication_year": 2019,
         "abstract_inverted_index": {"Hello": [0]}, "referenced_works": []},
        {"doi": None, "title": "Graph Models", "publication_year": 2021,
         "authorships": [{"author": {"display_name": "A Lee"}}],
         "abstract_inverted_index": {"Refs": [0]}, "referenced_works": ["W9"]},
    ]
    snap = _write_gz(tmp_path, works)
    candidates = [
        {"point_id": "d1", "doi": "10.1/x", "title": "x", "year": 2019,
         "first_author": "smith", "missing_abstract": True, "missing_refs": False},
        {"point_id": "t1", "doi": None, "title": "Graph Models", "year": 2021,
         "first_author": "lee", "missing_abstract": True, "missing_refs": True},
    ]
    storage = MagicMock(); storage.collection_name = "c"
    storage.iter_enrichment_candidates.return_value = iter(candidates)
    storage.batch_apply_snapshot_enrichment.return_value = 2

    result = runner.run_snapshot_enrichment(
        storage=storage, snapshot_dir=str(snap), dry_run=False, batch_size=10,
    )
    assert result["doi_matches"] == 1
    assert result["title_matches"] == 1
    assert result["applied"] >= 1
    assert storage.batch_apply_snapshot_enrichment.called


def test_runner_dry_run_writes_nothing(tmp_path):
    snap = _write_gz(tmp_path, [
        {"doi": "https://doi.org/10.1/x", "title": "x", "publication_year": 2019,
         "abstract_inverted_index": {"Hi": [0]}, "referenced_works": []}])
    storage = MagicMock(); storage.collection_name = "c"
    storage.iter_enrichment_candidates.return_value = iter([
        {"point_id": "d1", "doi": "10.1/x", "title": "x", "year": 2019,
         "first_author": "smith", "missing_abstract": True, "missing_refs": False}])
    result = runner.run_snapshot_enrichment(storage=storage, snapshot_dir=str(snap), dry_run=True)
    assert result["doi_matches"] == 1
    assert not storage.batch_apply_snapshot_enrichment.called
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement `src/core/snapshot/runner.py`:**
```python
"""Streaming-join runner: enrich the corpus from a local OpenAlex works snapshot."""

import glob
import gzip
import json
import logging
import os

from src.core.snapshot.matcher import build_candidate_index, match_work, extract_enrichment

logger = logging.getLogger(__name__)


def _iter_work_files(snapshot_dir: str):
    # works/updated_date=*/*.gz
    pattern = os.path.join(snapshot_dir, "updated_date=*", "*.gz")
    return sorted(glob.glob(pattern))


def run_snapshot_enrichment(storage, snapshot_dir: str, dry_run: bool = False,
                            batch_size: int = 500) -> dict:
    """Stream the snapshot works files and fill-only-missing enrichment into Qdrant.

    Returns counts: scanned, doi_matches, title_matches, applied.
    """
    candidates = list(storage.iter_enrichment_candidates())
    doi_map, title_map = build_candidate_index(candidates)
    logger.info("Snapshot candidates: %d (doi=%d, title_norm=%d)",
                len(candidates), len(doi_map), len(title_map))

    scanned = doi_matches = title_matches = applied = 0
    seen_points: set[str] = set()
    pending: list[tuple[str, dict]] = []

    def flush():
        nonlocal applied, pending
        if pending and not dry_run:
            applied += storage.batch_apply_snapshot_enrichment(pending)
        pending = []

    for path in _iter_work_files(snapshot_dir):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    work = json.loads(line)
                except json.JSONDecodeError:
                    continue
                scanned += 1
                m = match_work(work, doi_map, title_map)
                if not m or m.candidate.point_id in seen_points:
                    continue
                fields = extract_enrichment(work, m.candidate)
                if not fields:
                    continue
                seen_points.add(m.candidate.point_id)
                if m.source == "doi":
                    doi_matches += 1
                else:
                    title_matches += 1
                pending.append((m.candidate.point_id, fields))
                if len(pending) >= batch_size:
                    flush()
        logger.info("Processed %s | scanned=%d matches=%d", os.path.basename(path),
                    scanned, doi_matches + title_matches)
    flush()
    return {"scanned": scanned, "doi_matches": doi_matches,
            "title_matches": title_matches, "applied": applied,
            "candidates": len(candidates)}
```
> Execution note: this keeps the whole candidate index + `seen_points` in memory (~170K — fine). Checkpointing across files is intentionally simple here (re-running re-streams; fill-only-missing makes it idempotent). If a per-file checkpoint is wanted later, wrap with `CheckpointMixin` — out of scope for this first version (YAGNI).

- [ ] **Step 4: Run, confirm pass** (both runner tests). **Step 5: Commit** (`feat(snapshot): streaming-join runner (match + fill-only writes)`).

---

## Task 6: Snapshot fetch script + aws CLI + CLI command

**Files:** Create `scripts/snapshot/fetch_openalex_snapshot.sh`, `src/cli/commands/snapshot.py`; Modify the CLI registrar (where command modules are registered).

- [ ] **Step 1: aws CLI.** Install via uv: `uv tool install awscli`. Verify: `uv tool run aws --version` (or `aws --version` if on PATH). Confirm connectivity (no download): `aws s3 ls --no-sign-request s3://openalex/data/works/ | head` → lists `updated_date=*` prefixes + `manifest`.

- [ ] **Step 2: Fetch script.** Create `scripts/snapshot/fetch_openalex_snapshot.sh`:
```bash
#!/bin/bash
# Download the OpenAlex WORKS snapshot (anonymous, no AWS creds) to NFS SSD2.
# ~300GB — run operationally; resumable by re-running.
set -e
DEST="${OPENALEX_SNAPSHOT_DIR:-/mnt/nfs/ssd2/openalex_snapshot}"
mkdir -p "$DEST"
echo "[snapshot] syncing s3://openalex/data/works -> $DEST/data/works"
aws s3 sync "s3://openalex/data/works" "$DEST/data/works" --no-sign-request
echo "[snapshot] done. works dir: $DEST/data/works"
du -sh "$DEST/data/works" 2>/dev/null || true
```
`chmod +x` it. `bash -n` to syntax-check. (Do NOT run the full ~300GB sync as part of this task — that's an operational step; verify with the `aws s3 ls` from Step 1.)

- [ ] **Step 3: CLI command.** FIRST read an existing command module (e.g. `src/cli/commands/similarity.py`) and the registrar (`src/cli/core_collect.py` or wherever `register_commands` are wired) to match the exact pattern. Create `src/cli/commands/snapshot.py`:
```python
"""CLI: enrich corpus from a local OpenAlex works snapshot."""

import click

from src.core.storage import QdrantStorage
from src.core.snapshot.runner import run_snapshot_enrichment

DEFAULT_SNAPSHOT_DIR = "/mnt/nfs/ssd2/openalex_snapshot/data/works"


def register_commands(cli):
    @cli.command("enrich-from-openalex-snapshot")
    @click.option("--snapshot-dir", default=DEFAULT_SNAPSHOT_DIR, show_default=True,
                  help="Path to the OpenAlex works snapshot (updated_date=*/*.gz)")
    @click.option("--batch-size", type=int, default=500)
    @click.option("--dry-run", is_flag=True, help="Count matches without writing")
    def enrich_from_openalex_snapshot(snapshot_dir, batch_size, dry_run):
        """Stream the OpenAlex works snapshot and fill-only-missing enrich the corpus."""
        storage = QdrantStorage()
        result = run_snapshot_enrichment(
            storage=storage, snapshot_dir=snapshot_dir,
            dry_run=dry_run, batch_size=batch_size,
        )
        click.echo(f"Snapshot enrichment: {result}")
```
Register it in the CLI registrar alongside the other `register_commands` calls (match the existing wiring exactly).

- [ ] **Step 4: Smoke (no full download).** `uv run python -m src.cli.core_collect enrich-from-openalex-snapshot --help` → shows options, exit 0. (A real run needs the snapshot synced first.)

- [ ] **Step 5: Commit** (`feat(cli): enrich-from-openalex-snapshot command + fetch script`).

---

## Task 7: Full suite + dry-run validation

**Files:** none.

- [ ] **Step 1: Full snapshot test suite.** `uv run --extra dev pytest tests/core/snapshot -v` → all pass.
- [ ] **Step 2: No-regression.** `uv run --extra dev pytest tests/core -q` → green.
- [ ] **Step 3: (Operational, optional) tiny live dry-run.** IF a partial snapshot is available locally, run `enrich-from-openalex-snapshot --dry-run --snapshot-dir <one updated_date=* folder>` and confirm it reports plausible `doi_matches`/`title_matches` against the live corpus with zero writes. (Skip if the snapshot isn't downloaded yet — the unit/integration tests already cover the logic.)
- [ ] **Step 4: Commit any fixups** (`chore(snapshot): validation`).

---

## Self-Review
- **Spec coverage:** snapshot acquisition (Task 6 script + aws), works-only (Task 6 path), in-memory corpus index (Task 2 + 3 `build_candidate_index`), streaming join (Task 5), DOI-trusted + title-corroborated matching (Task 3 `match_work`/`_corroborates`), fill-only-missing + provenance (Task 3 `extract_enrichment` + Task 4 `batch_apply_snapshot_enrichment`), abstract reconstruction reuse (Task 1), dry-run (Task 5/6), testing (Tasks 1–7). Shared entry function `run_snapshot_enrichment` (Dagster asset is a trivial later wrapper, per spec).
- **Placeholder scan:** complete code in every step; "Execution notes" are concrete verification instructions (confirm class names / payload field shapes), the same accepted pattern as prior plans — not deferred logic. No TODO/TBD.
- **Type consistency:** `Candidate`/`Match` dataclasses used consistently; `build_candidate_index -> (doi_map, title_map)`, `match_work(...) -> Match|None`, `extract_enrichment(work, cand) -> dict`, `run_snapshot_enrichment(...) -> dict(scanned/doi_matches/title_matches/applied/candidates)`, `batch_apply_snapshot_enrichment(updates) -> int`, `iter_enrichment_candidates() -> dict rows`. `reconstruct_abstract` shared by crawler + matcher. `Deduplicator.normalize_title` used for all title keys (corpus + snapshot).

## Out of scope → follow-ups
- Per-file `CheckpointMixin` resume (current version re-streams; idempotent via fill-only-missing).
- Stub-paper enrichment from the snapshot (add a flag to include `is_stub` candidates).
- A Dagster asset wrapping `run_snapshot_enrichment` (quarterly schedule) — fits the Phase 1–4 orchestration.
- Optional `aws s3 sync` of other entities if future needs arise.
