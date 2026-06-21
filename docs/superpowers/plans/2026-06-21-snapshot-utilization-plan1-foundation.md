# Snapshot Utilization — Plan 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared, phase-agnostic modules (work extractor, work source, checkpoint, embedding queue, matcher/storage extensions, test infrastructure) that Plans 2/3/4 will compose into the four snapshot passes.

**Architecture:** Pure functions and small modules under `src/core/snapshot/`, with a strict separation between (a) parsing a single OpenAlex work dict, (b) iterating works from snapshot files or the live API, (c) matching works to corpus / stubs, (d) persisting checkpoints + handing off to the embedder. Storage extensions follow the existing reader / writer / stubs / facade split. No phase logic in this plan — every module is callable by any phase.

**Tech Stack:** Python 3.12, uv, Qdrant (qdrant-client), Pydantic v2, pytest + pytest-asyncio. Tests: `uv run --extra dev pytest`.

## Global Constraints

- Git author for every commit: `rabqatab <minhan.nick.cho@gmail.com>`. No `Co-Authored-By` lines, no "Generated with Claude Code" footer. Use `git -c user.name=... -c user.email=... commit ...`.
- All Python invocations use `uv run`. Never bare `python3`.
- Snapshot path is `/mnt/nfs/ssd2/openalex_snapshot/data/works/updated_date=*/*.gz`; env override `OPENALEX_SNAPSHOT_DIR`.
- Checkpoint root is `${DAGSTER_HOME:-~/dagster_home}/snapshot_checkpoints/`.
- All new modules `fill-only-missing`: never overwrite an existing payload value.
- Provenance payload keys to write whenever a phase touches a point: `snapshot_filled_at` (ISO date string, snapshot pass) or `live_filled_at` (live pass) — both may coexist.
- All public functions in this plan have type hints. Test names use the `test_<unit>_<behavior>` pattern.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/core/snapshot/extractor.py` | NEW | Pull payload-shaped fields from a single work dict (fill-only-missing aware) |
| `src/core/snapshot/work_source.py` | NEW | Iterator factory: snapshot files or live API → `Iterator[dict]` |
| `src/core/snapshot/checkpoint.py` | NEW | Per-phase done-file set, failed-batch + quarantine JSONL writers |
| `src/core/snapshot/embedding_queue.py` | NEW | Disk-persisted FIFO of `(point_id, source)` consumed by `embed-papers` |
| `src/core/snapshot/stats.py` | NEW | Dataclasses for per-phase summaries + a log helper |
| `src/core/snapshot/matcher.py` | MODIFY | Add `build_stub_index`, `match_work_for_stubs` |
| `src/core/snapshot/runner.py` | MODIFY | Emit `DeprecationWarning`, keep behavior |
| `src/core/storage/reader.py` | MODIFY | 4 new iter/build methods |
| `src/core/storage/stubs.py` | MODIFY | 3 new methods |
| `src/core/storage/writer.py` | MODIFY | 4 new batch_* methods |
| `src/core/storage/base.py` | MODIFY | Facade delegations |
| `pyproject.toml` | MODIFY | Add `snapshot_live` pytest marker |
| `tests/core/snapshot/__init__.py` | NEW | (empty) |
| `tests/core/snapshot/conftest.py` | NEW | `mock_storage` fixture (in-memory dict stub) |
| `tests/core/snapshot/fixtures/works/tiny.jsonl.gz` | NEW | 50 hand-curated works |
| `tests/core/snapshot/fixtures/corpus/seed_papers.json` | NEW | 10 real papers |
| `tests/core/snapshot/fixtures/corpus/seed_stubs.json` | NEW | 8 stubs |
| `tests/core/snapshot/fixtures/README.md` | NEW | Fixture scenarios + how to add |
| `tests/core/snapshot/README.md` | NEW | Test catalogue |
| `tests/core/snapshot/test_extractor.py` | NEW | L1 |
| `tests/core/snapshot/test_work_source.py` | NEW | L1 |
| `tests/core/snapshot/test_checkpoint.py` | NEW | L1 |
| `tests/core/snapshot/test_embedding_queue.py` | NEW | L1 |
| `tests/core/snapshot/test_matcher.py` | NEW | L1 (extension cases) |
| `tests/core/snapshot/test_storage_extensions.py` | NEW | L1 against real Qdrant (`integration` marker) |

---

## Task 1: Pytest markers + snapshot test directory scaffolding

**Files:**
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]` section)
- Create: `tests/core/snapshot/__init__.py`
- Create: `tests/core/snapshot/fixtures/__init__.py`
- Create: `tests/core/snapshot/README.md`
- Create: `tests/core/snapshot/fixtures/README.md`

**Interfaces:** Produces: pytest marker `snapshot_live` registered; `tests/core/snapshot/` discoverable.

- [ ] **Step 1: Read the existing pytest config.**

```bash
grep -A 5 "tool.pytest" pyproject.toml
```

Expected: a `[tool.pytest.ini_options]` block with at least the `integration` marker.

- [ ] **Step 2: Add the `snapshot_live` marker.**

Edit `pyproject.toml` `[tool.pytest.ini_options]` `markers = [...]` list to include:

```
"snapshot_live: requires the real OpenAlex snapshot files on disk (large, slow)",
```

- [ ] **Step 3: Create empty package files.**

```bash
touch tests/core/snapshot/__init__.py tests/core/snapshot/fixtures/__init__.py
```

- [ ] **Step 4: Create the test catalogue README.**

Write `tests/core/snapshot/README.md`:

````markdown
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
````

- [ ] **Step 5: Create the fixtures README placeholder.**

Write `tests/core/snapshot/fixtures/README.md`:

````markdown
# Snapshot Test Fixtures

| File | Scenarios it covers |
|---|---|
| `works/tiny.jsonl.gz` | DOI match, title match (corroborated + uncorroborated), AI-concept gap, anchor gap, empty `abstract_inverted_index`, malformed line, duplicate DOI within the same file |
| `corpus/seed_papers.json` | 10 real papers across venues with varying DOI / openalex_id / cited_by states |
| `corpus/seed_stubs.json` | 8 stubs — 2 each for identifier_type `doi`, `arxiv`, `title`, `openalex` |

Adding a scenario: append a JSON line to the source for the appropriate fixture, regenerate the `.gz`, and add a test case that asserts the expected classification.
````

- [ ] **Step 6: Verify markers registered.**

Run: `uv run --extra dev pytest --markers | grep snapshot_live`
Expected: line `@pytest.mark.snapshot_live: requires the real OpenAlex snapshot files on disk (large, slow)`.

- [ ] **Step 7: Commit.**

```bash
git add pyproject.toml tests/core/snapshot/__init__.py tests/core/snapshot/fixtures/__init__.py \
        tests/core/snapshot/README.md tests/core/snapshot/fixtures/README.md
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "test(snapshot): scaffold test directory + snapshot_live pytest marker"
```

---

## Task 2: Hand-curated work fixtures

**Files:**
- Create: `tests/core/snapshot/fixtures/works/tiny.jsonl`
- Create: `tests/core/snapshot/fixtures/works/tiny.jsonl.gz` (generated)
- Create: `tests/core/snapshot/fixtures/corpus/seed_papers.json`
- Create: `tests/core/snapshot/fixtures/corpus/seed_stubs.json`

**Interfaces:** Produces: `FIXTURE_WORKS = Path("tests/core/snapshot/fixtures/works/tiny.jsonl.gz")`, `FIXTURE_CORPUS = Path("tests/core/snapshot/fixtures/corpus")`. Each work dict has the same shape as a snapshot line (subset of the 49 fields, but every key any later test asserts on is present).

- [ ] **Step 1: Author the work fixture JSONL.**

Create `tests/core/snapshot/fixtures/works/tiny.jsonl` with 12 hand-written lines (one per scenario). Each line is a single-line JSON object. Below is the schema each work follows; copy and adapt for each scenario.

```json
{"id":"https://openalex.org/W1000000001","doi":"https://doi.org/10.1000/seed-doi-001","title":"DOI-Match Corpus Paper","display_name":"DOI-Match Corpus Paper","publication_year":2024,"publication_date":"2024-03-15","language":"en","type":"article","authorships":[{"author":{"id":"https://openalex.org/A1","display_name":"Alice Researcher","orcid":"https://orcid.org/0000-0000-0000-0001"}}],"primary_topic":{"id":"https://openalex.org/T11689","display_name":"AI Topic"},"topics":[{"id":"https://openalex.org/T11689","display_name":"AI Topic"}],"keywords":[],"concepts":[{"id":"https://openalex.org/C154945302","display_name":"Artificial intelligence","score":0.92}],"locations":[],"primary_location":{"source":{"display_name":"Venue X"},"pdf_url":null},"best_oa_location":{"pdf_url":"https://example.com/best.pdf"},"open_access":{"is_oa":true},"is_retracted":false,"referenced_works":["https://openalex.org/W9999999991"],"referenced_works_count":1,"abstract_inverted_index":{"This":[0],"is":[1],"an":[2],"abstract":[3]},"cited_by_count":42,"counts_by_year":[{"year":2024,"cited_by_count":10}],"fwci":1.4,"citation_normalized_percentile":{"value":0.88},"updated_date":"2024-03-20"}
```

The 12 lines (use unique `id`, `doi`, `title`):

1. `W1000000001` / `doi:10.1000/seed-doi-001` / title `DOI-Match Corpus Paper` — must match seed paper #1 by DOI.
2. `W1000000002` / `doi:10.1000/seed-doi-002` / title `Title-Match Plus Year` — DOI not in corpus, title matches seed #2, year ±1 corroborated.
3. `W1000000003` / no doi / title `Title-Match Plus Author` — title matches seed #3, author surname matches.
4. `W1000000004` / no doi / title `Title-No-Corroboration` — title matches seed #4 but year/author both fail → must be skipped.
5. `W1000000005` / `doi:10.1000/stub-doi-001` / title `Stub DOI Match` — matches stub identifier `doi:10.1000/stub-doi-001`. Has `abstract_inverted_index` + author + year → PROMOTE.
6. `W1000000006` / no doi / title `Stub Title Match Promotable` — matches stub by title hash. Has abstract → PROMOTE.
7. `W1000000007` / `doi:10.1000/stub-doi-002` / title `Stub Partial` — matches stub but `abstract_inverted_index` is `{}` and authors `[]` → ENRICH_KEEP_STUB.
8. `W1000000008` / `doi:10.1000/external-anchor` / title `Anchor Gap Paper` — referenced by 2 seed papers (their `referenced_works` lists include `W1000000008`). Not in corpus. Must classify as ANCHOR_INJECT.
9. `W1000000009` / `doi:10.1000/concept-recent` / title `AI Concept Recent` — `concepts` includes `C154945302` (Artificial intelligence), `cited_by_count: 80`, `publication_year: 2023`. Not anchored. Must classify as CONCEPT_INJECT.
10. `W1000000010` / `doi:10.1000/concept-old-strong` / title `AI Concept Older Strong` — AI concept, `cited_by_count: 500`, `publication_year: 2019`. Must classify as CONCEPT_INJECT.
11. `W1000000011` / `doi:10.1000/concept-too-weak` / title `AI Concept Recent Weak` — AI concept but `cited_by_count: 5`, `publication_year: 2023`. Must classify as REJECT.
12. `W1000000012` / `doi:10.1000/stub-doi-001` / title `Duplicate Same Doi Within File` — same DOI as line 5; in-pass dedup must keep only the first.

Additionally add 2 noise lines after line 12:
13. A blank line (single `\n`).
14. The literal string `{this is not json}\n`.

(Lines 13/14 test the `JSONDecodeError`/empty-line skip path.)

- [ ] **Step 2: Generate the gzipped fixture.**

```bash
gzip -kf tests/core/snapshot/fixtures/works/tiny.jsonl
ls -la tests/core/snapshot/fixtures/works/tiny.jsonl.gz
```

Expected: a `tiny.jsonl.gz` next to `tiny.jsonl`. Both are checked in (the `.jsonl` for human review, the `.gz` for tests).

- [ ] **Step 3: Author seed corpus.**

Create `tests/core/snapshot/fixtures/corpus/seed_papers.json` — 10 real papers as a JSON array. Each entry shape:

```json
{"point_id":"real-001","payload":{"is_stub":false,"title":"DOI-Match Corpus Paper","doi":"10.1000/seed-doi-001","openalex_id":"W1000000001","publication_year":2024,"authors":[{"display_name":"Alice Researcher"}],"abstract":"existing abstract","referenced_works":["W1000000008","W2000000111"],"cited_by":["real-002"]}}
```

Required entries:
- `real-001` matches work #1 by DOI (`10.1000/seed-doi-001`).
- `real-002` matches work #2 by title `Title-Match Plus Year`, year 2024 (work has 2023 → ±1 corroborates).
- `real-003` matches work #3 by title `Title-Match Plus Author`, first author surname `Researcher`.
- `real-004` matches work #4 by title `Title-No-Corroboration`, year 2015 (work has 2024 → fails ±1), first author `Xie` (work has `Researcher` → fails).
- `real-005..real-010` are AI papers with `referenced_works` lists. Two of them include `W1000000008` so the anchor check passes (`≥2` internal citers).

- [ ] **Step 4: Author seed stubs.**

Create `tests/core/snapshot/fixtures/corpus/seed_stubs.json` — 8 stubs as a JSON array. Each entry shape:

```json
{"point_id":"stub-doi-001","payload":{"is_stub":true,"identifier":"doi:10.1000/stub-doi-001","identifier_type":"doi","doi":"10.1000/stub-doi-001","title":null,"abstract":null,"year":null,"authors":[],"venue":null,"cited_by":["real-005","real-006"],"cited_by_count_internal":2,"alternate_identifiers":{}}}
```

Required entries:
- `stub-doi-001`, `stub-doi-002` (identifier_type `doi`).
- `stub-arxiv-001`, `stub-arxiv-002` (identifier_type `arxiv`, `identifier: "arXiv:2401.12345"`).
- `stub-title-001` (identifier_type `title`, `identifier: "TITLE:stub_title_match_promotable_..."`, also pre-set `title: "Stub Title Match Promotable"` so the title_map can index it).
- `stub-title-002` (identifier_type `title`, no work matches).
- `stub-oa-001`, `stub-oa-002` (identifier_type `openalex`, `identifier: "openalex:W1000000005"`).

- [ ] **Step 5: Commit.**

```bash
git add tests/core/snapshot/fixtures/
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "test(snapshot): hand-curated work + corpus + stub fixtures (12 scenarios)"
```

---

## Task 3: `mock_storage` fixture (conftest.py)

**Files:**
- Create: `tests/core/snapshot/conftest.py`
- Test: `tests/core/snapshot/test_mock_storage.py` (self-test of the stub)

**Interfaces:**
- Produces: pytest fixture `mock_storage` — an instance with the following methods (used by every L2 phase test):
  ```
  set_payload(point_id: str, payload: dict) -> None        # merges into existing
  get_payload(point_id: str) -> dict | None
  scroll_payloads() -> list[tuple[str, dict]]              # all points
  seed_from_json(path: pathlib.Path) -> None               # loads list of {point_id, payload}
  has_vector(point_id: str) -> bool                        # always False unless vector_set called
  vector_set(point_id: str) -> None                        # mark as having a vector
  count_with_filter(must_not_is_stub=False, must_is_stub=False, missing_field=None) -> int
  ```
- Plus the stubs of every storage extension introduced in Tasks 10–20 — they will be added incrementally as those tasks land.

- [ ] **Step 1: Write the self-test first.**

Create `tests/core/snapshot/test_mock_storage.py`:

```python
import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "corpus" / "seed_papers.json"


def test_seed_and_get(mock_storage):
    mock_storage.seed_from_json(FIXTURE)
    p = mock_storage.get_payload("real-001")
    assert p is not None
    assert p["doi"] == "10.1000/seed-doi-001"


def test_set_payload_merges(mock_storage):
    mock_storage.set_payload("x", {"a": 1, "b": 2})
    mock_storage.set_payload("x", {"b": 99, "c": 3})
    assert mock_storage.get_payload("x") == {"a": 1, "b": 99, "c": 3}


def test_has_vector_default_false(mock_storage):
    mock_storage.set_payload("x", {})
    assert mock_storage.has_vector("x") is False
    mock_storage.vector_set("x")
    assert mock_storage.has_vector("x") is True


def test_count_with_filter(mock_storage):
    mock_storage.seed_from_json(FIXTURE)
    real = mock_storage.count_with_filter(must_not_is_stub=True)
    assert real == 10
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_mock_storage.py -v
```

Expected: `ModuleNotFoundError` or fixture-not-found errors.

- [ ] **Step 3: Implement `conftest.py`.**

Create `tests/core/snapshot/conftest.py`:

```python
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
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_mock_storage.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add tests/core/snapshot/conftest.py tests/core/snapshot/test_mock_storage.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "test(snapshot): in-memory mock_storage fixture + self-tests"
```

---

## Task 4: `extractor.extract_p1_fields`

**Files:**
- Create: `src/core/snapshot/extractor.py`
- Test: `tests/core/snapshot/test_extractor.py`

**Interfaces:**
- Consumes: `reconstruct_abstract` (existing, `src/core/crawler/openalex.py:37`).
- Produces:
  ```python
  def extract_p1_fields(work: dict, existing_payload: dict | None = None) -> dict
  ```
  Returns ONLY the keys whose existing value is missing/empty in `existing_payload`. Keys it may emit: `cited_by_count`, `fwci`, `citation_normalized_percentile`, `counts_by_year`, `concepts`, `topics`, `primary_topic`, `best_oa_pdf_url`, `orcid_map`, `sustainable_development_goals`, `funders`, `institutions`, `mesh`, `language`, `open_access`.

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_extractor.py`:

```python
import json
from pathlib import Path
import gzip

from src.core.snapshot.extractor import extract_p1_fields

FIXTURE = Path(__file__).parent / "fixtures" / "works" / "tiny.jsonl.gz"


def _load_work(line_idx: int) -> dict:
    with gzip.open(FIXTURE, "rt") as f:
        for i, line in enumerate(f):
            if i == line_idx and line.strip():
                return json.loads(line)
    raise AssertionError(f"no work at line {line_idx}")


def test_extract_p1_returns_all_metric_fields_when_missing():
    work = _load_work(0)  # DOI-Match Corpus Paper
    out = extract_p1_fields(work, existing_payload={})
    assert out["cited_by_count"] == 42
    assert out["fwci"] == 1.4
    assert out["citation_normalized_percentile"] == {"value": 0.88}
    assert out["concepts"]
    assert out["best_oa_pdf_url"] == "https://example.com/best.pdf"
    assert out["orcid_map"] == {"Alice Researcher": "https://orcid.org/0000-0000-0000-0001"}


def test_extract_p1_skips_already_present():
    work = _load_work(0)
    out = extract_p1_fields(work, existing_payload={"cited_by_count": 9, "fwci": 0.1})
    assert "cited_by_count" not in out
    assert "fwci" not in out
    assert "concepts" in out  # still missing


def test_extract_p1_handles_missing_keys():
    out = extract_p1_fields({}, existing_payload={})
    assert out == {}


def test_extract_p1_skips_falsy_but_distinguishes_zero_from_none():
    # cited_by_count=0 is a real value; should be emitted as 0 if missing
    work = {"cited_by_count": 0, "fwci": None}
    out = extract_p1_fields(work, existing_payload={})
    assert out["cited_by_count"] == 0
    assert "fwci" not in out  # None means OpenAlex doesn't have it
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_extractor.py -v
```

Expected: `ModuleNotFoundError: src.core.snapshot.extractor`.

- [ ] **Step 3: Implement `extractor.extract_p1_fields`.**

Create `src/core/snapshot/extractor.py`:

```python
"""Pull payload-shaped fields from a single OpenAlex work dict.

Every function is fill-only-missing aware: if `existing_payload` already
contains a non-empty value for a field, that field is omitted from the
returned dict so the caller's batch write never overwrites it.
"""
from typing import Any

from src.core.crawler.openalex import reconstruct_abstract


def _has_value(existing: dict | None, key: str) -> bool:
    if not existing:
        return False
    v = existing.get(key)
    if v is None:
        return False
    if v == "" or v == [] or v == {}:
        return False
    return True


def _orcid_map(work: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in work.get("authorships") or []:
        au = a.get("author") or {}
        name = au.get("display_name")
        orcid = au.get("orcid")
        if name and orcid:
            out[name] = orcid
    return out


def extract_p1_fields(work: dict, existing_payload: dict | None = None) -> dict[str, Any]:
    """Return ONLY the metadata fields that are missing in existing_payload."""
    out: dict[str, Any] = {}
    existing = existing_payload or {}

    # scalars
    for key in ("cited_by_count", "fwci", "language"):
        if not _has_value(existing, key):
            v = work.get(key)
            if v is not None:  # 0 is a real value; None is "unknown"
                out[key] = v

    # nested objects / arrays — emit only if non-empty
    for key in (
        "citation_normalized_percentile",
        "counts_by_year",
        "concepts",
        "topics",
        "primary_topic",
        "sustainable_development_goals",
        "funders",
        "institutions",
        "mesh",
        "open_access",
    ):
        if not _has_value(existing, key):
            v = work.get(key)
            if v:  # non-empty
                out[key] = v

    # best_oa_pdf_url is nested
    if not _has_value(existing, "best_oa_pdf_url"):
        url = (work.get("best_oa_location") or {}).get("pdf_url")
        if url:
            out["best_oa_pdf_url"] = url

    # orcid_map from authorships
    if not _has_value(existing, "orcid_map"):
        m = _orcid_map(work)
        if m:
            out["orcid_map"] = m

    return out
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_extractor.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/extractor.py tests/core/snapshot/test_extractor.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): extractor.extract_p1_fields (fill-only-missing metadata)"
```

---

## Task 5: `extractor.extract_full_record`

**Files:**
- Modify: `src/core/snapshot/extractor.py`
- Modify: `tests/core/snapshot/test_extractor.py`

**Interfaces:**
- Produces:
  ```python
  def extract_full_record(work: dict) -> dict
  ```
  Returns a payload-shaped dict ready to be the full record of a NEW point (P2 promotion target or P3 injection target). Keys it may emit: all P1 keys above, plus `title`, `abstract`, `authors`, `year`, `venue`, `doi`, `openalex_id`, `arxiv_id` (if present in `ids`), `referenced_works` (raw OA Work-ID list), `publication_date`, `type`, `is_retracted`. Returns omit-key on missing source data; the caller decides defaults.

- [ ] **Step 1: Append the failing test.**

Append to `tests/core/snapshot/test_extractor.py`:

```python
from src.core.snapshot.extractor import extract_full_record


def test_extract_full_record_has_core_keys():
    work = _load_work(0)
    out = extract_full_record(work)
    assert out["title"] == "DOI-Match Corpus Paper"
    assert out["doi"] == "10.1000/seed-doi-001"
    assert out["openalex_id"] == "W1000000001"
    assert out["year"] == 2024
    assert out["abstract"].startswith("This is an abstract")
    assert out["authors"] == [{"display_name": "Alice Researcher"}]
    assert out["referenced_works"] == ["https://openalex.org/W9999999991"]
    # P1 fields are folded in
    assert out["cited_by_count"] == 42


def test_extract_full_record_missing_abstract_inverted_index():
    work = _load_work(6)  # Stub Partial — abstract_inverted_index is {}
    out = extract_full_record(work)
    assert out.get("abstract") in (None, "")
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_extractor.py::test_extract_full_record_has_core_keys -v
```

Expected: `AttributeError` or import error.

- [ ] **Step 3: Implement `extract_full_record`.**

Append to `src/core/snapshot/extractor.py`:

```python
def _norm_openalex_id(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.rsplit("/", 1)[-1]


def _norm_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def extract_full_record(work: dict) -> dict[str, Any]:
    """Build a full payload dict suitable for a NEW corpus point.

    P2 (promotion) and P3 (injection) both call this. The caller is
    responsible for adding provenance keys (promoted_from_stub, etc.).
    """
    out: dict[str, Any] = {}

    if title := (work.get("title") or work.get("display_name")):
        out["title"] = title
    if doi := _norm_doi(work.get("doi")):
        out["doi"] = doi
    if oa := _norm_openalex_id(work.get("id")):
        out["openalex_id"] = oa
    if year := work.get("publication_year"):
        out["year"] = year
    if pdate := work.get("publication_date"):
        out["publication_date"] = pdate
    if t := work.get("type"):
        out["type"] = t
    if work.get("is_retracted") is True:
        out["is_retracted"] = True

    inv = work.get("abstract_inverted_index")
    if inv:
        abs_text = reconstruct_abstract(inv)
        if abs_text:
            out["abstract"] = abs_text

    authors = [
        {"display_name": (a.get("author") or {}).get("display_name", "")}
        for a in (work.get("authorships") or [])
        if (a.get("author") or {}).get("display_name")
    ]
    if authors:
        out["authors"] = authors

    if venue := ((work.get("primary_location") or {}).get("source") or {}).get("display_name"):
        out["venue"] = venue

    if refs := work.get("referenced_works"):
        out["referenced_works"] = list(refs)

    arxiv_id = (work.get("ids") or {}).get("arxiv") or _arxiv_from_doi(out.get("doi"))
    if arxiv_id:
        out["arxiv_id"] = arxiv_id

    # fold in all P1 metadata fields
    out.update(extract_p1_fields(work, existing_payload=None))
    return out


def _arxiv_from_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    # arXiv DOIs look like 10.48550/arXiv.2401.12345
    marker = "10.48550/arxiv."
    if doi.startswith(marker):
        return doi[len(marker):]
    return None
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_extractor.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/extractor.py tests/core/snapshot/test_extractor.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): extractor.extract_full_record (new-point payload builder)"
```

---

## Task 6: `checkpoint.py`

**Files:**
- Create: `src/core/snapshot/checkpoint.py`
- Test: `tests/core/snapshot/test_checkpoint.py`

**Interfaces:**
- Produces:
  ```python
  def load(phase: str, *, root: Path | None = None) -> set[str]
  def mark_done(phase: str, filepath: str, *, root: Path | None = None) -> None
  def write_failed_batch(phase: str, batch: list, error: str, *, root: Path | None = None) -> Path
  def quarantine(phase: str, work: dict, reason: str, *, root: Path | None = None) -> Path
  def reset(phase: str, *, root: Path | None = None) -> None
  def live_high_water_mark(phase: str, *, root: Path | None = None) -> str | None
  def set_live_high_water_mark(phase: str, iso: str, *, root: Path | None = None) -> None
  ```
  Default root: `$DAGSTER_HOME/snapshot_checkpoints` (fallback `~/dagster_home/snapshot_checkpoints`).

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_checkpoint.py`:

```python
from pathlib import Path

from src.core.snapshot import checkpoint as cp


def test_mark_done_then_load(tmp_path: Path):
    cp.mark_done("p1", "/snap/part_0001.gz", root=tmp_path)
    cp.mark_done("p1", "/snap/part_0002.gz", root=tmp_path)
    cp.mark_done("p1", "/snap/part_0001.gz", root=tmp_path)  # idempotent
    done = cp.load("p1", root=tmp_path)
    assert done == {"/snap/part_0001.gz", "/snap/part_0002.gz"}


def test_load_returns_empty_for_unknown_phase(tmp_path: Path):
    assert cp.load("p2", root=tmp_path) == set()


def test_write_failed_batch(tmp_path: Path):
    path = cp.write_failed_batch("p2", [{"a": 1}, {"a": 2}], "boom", root=tmp_path)
    assert path.exists()
    content = path.read_text().strip().splitlines()
    assert len(content) == 2


def test_quarantine(tmp_path: Path):
    p = cp.quarantine("p2", {"id": "w1", "title": "x"}, "verify failed", root=tmp_path)
    assert p.read_text().strip().endswith('"reason": "verify failed"}')


def test_live_high_water_mark(tmp_path: Path):
    assert cp.live_high_water_mark("p1", root=tmp_path) is None
    cp.set_live_high_water_mark("p1", "2026-06-20T12:00:00Z", root=tmp_path)
    assert cp.live_high_water_mark("p1", root=tmp_path) == "2026-06-20T12:00:00Z"


def test_reset_clears_phase(tmp_path: Path):
    cp.mark_done("p1", "/x.gz", root=tmp_path)
    cp.reset("p1", root=tmp_path)
    assert cp.load("p1", root=tmp_path) == set()
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_checkpoint.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `checkpoint.py`.**

Create `src/core/snapshot/checkpoint.py`:

```python
"""Per-phase file-level checkpoint, failed-batch, and quarantine writes."""
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _default_root() -> Path:
    return Path(os.environ.get("DAGSTER_HOME", str(Path.home() / "dagster_home"))) / "snapshot_checkpoints"


def _phase_dir(phase: str, root: Path | None) -> Path:
    p = (root or _default_root()) / phase
    p.mkdir(parents=True, exist_ok=True)
    return p


def load(phase: str, *, root: Path | None = None) -> set[str]:
    f = _phase_dir(phase, root) / "done_files.txt"
    if not f.exists():
        return set()
    return {ln.strip() for ln in f.read_text().splitlines() if ln.strip()}


def mark_done(phase: str, filepath: str, *, root: Path | None = None) -> None:
    done = load(phase, root=root)
    if filepath in done:
        return
    f = _phase_dir(phase, root) / "done_files.txt"
    with f.open("a") as fh:
        fh.write(filepath + "\n")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_failed_batch(phase: str, batch: list, error: str, *, root: Path | None = None) -> Path:
    d = _phase_dir(phase, root) / "failed_batches"
    d.mkdir(exist_ok=True)
    f = d / f"{_ts()}.jsonl"
    with f.open("w") as fh:
        for item in batch:
            fh.write(json.dumps({"item": item, "error": error}) + "\n")
    return f


def quarantine(phase: str, work: dict, reason: str, *, root: Path | None = None) -> Path:
    f = _phase_dir(phase, root) / "quarantine.jsonl"
    with f.open("a") as fh:
        fh.write(json.dumps({"work": work, "reason": reason}) + "\n")
    return f


def reset(phase: str, *, root: Path | None = None) -> None:
    p = (root or _default_root()) / phase
    if p.exists():
        shutil.rmtree(p)


def live_high_water_mark(phase: str, *, root: Path | None = None) -> str | None:
    f = _phase_dir(phase, root) / "live_high_water_mark.iso"
    if not f.exists():
        return None
    s = f.read_text().strip()
    return s or None


def set_live_high_water_mark(phase: str, iso: str, *, root: Path | None = None) -> None:
    f = _phase_dir(phase, root) / "live_high_water_mark.iso"
    f.write_text(iso)
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_checkpoint.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/checkpoint.py tests/core/snapshot/test_checkpoint.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): file-level checkpoint + failed-batch + quarantine + live HWM"
```

---

## Task 7: `embedding_queue.py`

**Files:**
- Create: `src/core/snapshot/embedding_queue.py`
- Test: `tests/core/snapshot/test_embedding_queue.py`

**Interfaces:**
- Produces:
  ```python
  def append(point_id: str, source: str, *, root: Path | None = None) -> None
  def cancel(point_id: str, *, root: Path | None = None) -> None
  def drain(*, root: Path | None = None) -> Iterator[tuple[str, str]]   # yields (point_id, source); removes as it goes
  def depth(*, root: Path | None = None) -> int
  ```
  Storage: append-only JSONL at `{checkpoint_root}/embedding_queue.jsonl`. `cancel` writes a tombstone line `{"point_id": X, "cancelled": true}`. `drain` compacts the file on each pass.

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_embedding_queue.py`:

```python
from pathlib import Path

from src.core.snapshot import embedding_queue as q


def test_append_then_drain(tmp_path: Path):
    q.append("p-1", "promotion", root=tmp_path)
    q.append("p-2", "injection", root=tmp_path)
    assert q.depth(root=tmp_path) == 2
    out = list(q.drain(root=tmp_path))
    assert out == [("p-1", "promotion"), ("p-2", "injection")]
    assert q.depth(root=tmp_path) == 0


def test_cancel_removes_entry(tmp_path: Path):
    q.append("p-1", "promotion", root=tmp_path)
    q.append("p-2", "injection", root=tmp_path)
    q.cancel("p-1", root=tmp_path)
    out = list(q.drain(root=tmp_path))
    assert out == [("p-2", "injection")]


def test_persistence_across_processes(tmp_path: Path):
    q.append("p-1", "promotion", root=tmp_path)
    # simulate restart by calling again from "scratch"
    assert q.depth(root=tmp_path) == 1
    out = list(q.drain(root=tmp_path))
    assert out == [("p-1", "promotion")]


def test_duplicate_append_dedupes_on_drain(tmp_path: Path):
    q.append("p-1", "promotion", root=tmp_path)
    q.append("p-1", "promotion", root=tmp_path)
    out = list(q.drain(root=tmp_path))
    assert out == [("p-1", "promotion")]
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_embedding_queue.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `embedding_queue.py`.**

Create `src/core/snapshot/embedding_queue.py`:

```python
"""Disk-persisted FIFO of points needing embedding, written by P2/P3.

Format: append-only JSONL at `embedding_queue.jsonl` under the checkpoint root.
A line is one of:
  {"point_id": <str>, "source": <str>}
  {"point_id": <str>, "cancelled": true}

`drain` returns (point_id, source) tuples in insertion order, deduped, with
cancellations honored, and rewrites the file empty after a successful drain.
"""
import json
import os
from collections.abc import Iterator
from pathlib import Path


def _default_root() -> Path:
    return Path(os.environ.get("DAGSTER_HOME", str(Path.home() / "dagster_home"))) / "snapshot_checkpoints"


def _queue_file(root: Path | None) -> Path:
    r = root or _default_root()
    r.mkdir(parents=True, exist_ok=True)
    return r / "embedding_queue.jsonl"


def append(point_id: str, source: str, *, root: Path | None = None) -> None:
    f = _queue_file(root)
    with f.open("a") as fh:
        fh.write(json.dumps({"point_id": point_id, "source": source}) + "\n")


def cancel(point_id: str, *, root: Path | None = None) -> None:
    f = _queue_file(root)
    with f.open("a") as fh:
        fh.write(json.dumps({"point_id": point_id, "cancelled": True}) + "\n")


def _resolve(lines: list[str]) -> list[tuple[str, str]]:
    active: dict[str, str] = {}
    order: list[str] = []
    cancelled: set[str] = set()
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        pid = rec.get("point_id")
        if not pid:
            continue
        if rec.get("cancelled"):
            cancelled.add(pid)
            active.pop(pid, None)
            continue
        if pid in cancelled:
            continue
        if pid not in active:
            active[pid] = rec.get("source", "")
            order.append(pid)
    return [(pid, active[pid]) for pid in order if pid in active]


def depth(*, root: Path | None = None) -> int:
    f = _queue_file(root)
    if not f.exists():
        return 0
    return len(_resolve(f.read_text().splitlines()))


def drain(*, root: Path | None = None) -> Iterator[tuple[str, str]]:
    f = _queue_file(root)
    if not f.exists():
        return iter(())
    resolved = _resolve(f.read_text().splitlines())
    f.write_text("")  # clear after read
    return iter(resolved)
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_embedding_queue.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/embedding_queue.py tests/core/snapshot/test_embedding_queue.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): disk-persisted embedding queue (append/cancel/drain)"
```

---

## Task 8: `work_source.py`

**Files:**
- Create: `src/core/snapshot/work_source.py`
- Test: `tests/core/snapshot/test_work_source.py`

**Interfaces:**
- Consumes: `checkpoint.load`.
- Produces:
  ```python
  def iter_snapshot_works(snapshot_dir: str, *, skip_files: set[str] | None = None) -> Iterator[tuple[str, dict]]
  # yields (filepath, work_dict); skip_files lets resume drop already-done .gz files
  ```
  `iter_live_works` is declared but not implemented here — it's a Plan 5 deliverable. A `NotImplementedError` stub keeps the import surface stable.

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_work_source.py`:

```python
from pathlib import Path
import gzip
import json

from src.core.snapshot.work_source import iter_snapshot_works

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "works"


def _setup_snapshot_layout(tmp_path: Path) -> Path:
    """Create a fake snapshot dir tree with one .gz file."""
    d = tmp_path / "data" / "works" / "updated_date=2024-01-01"
    d.mkdir(parents=True)
    src = FIXTURE_DIR / "tiny.jsonl.gz"
    (d / "part_0000.gz").write_bytes(src.read_bytes())
    return tmp_path / "data" / "works"


def test_iter_yields_works(tmp_path: Path):
    snap = _setup_snapshot_layout(tmp_path)
    works = list(iter_snapshot_works(str(snap)))
    # tiny.jsonl has 12 valid works + 2 invalid (blank + non-JSON)
    assert len(works) == 12
    paths = {p for p, _ in works}
    assert len(paths) == 1
    assert all(isinstance(w, dict) for _, w in works)


def test_iter_skips_done_files(tmp_path: Path):
    snap = _setup_snapshot_layout(tmp_path)
    done = {str((snap / "updated_date=2024-01-01" / "part_0000.gz").resolve())}
    works = list(iter_snapshot_works(str(snap), skip_files=done))
    assert works == []


def test_iter_skips_blank_and_malformed_lines(tmp_path: Path):
    snap = _setup_snapshot_layout(tmp_path)
    works = list(iter_snapshot_works(str(snap)))
    # The 2 noise lines must not appear
    assert all("title" in w or "doi" in w or "id" in w for _, w in works)
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_work_source.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `work_source.py`.**

Create `src/core/snapshot/work_source.py`:

```python
"""Yield work dicts from snapshot files (and, later, live API delta).

Phases consume `iter_snapshot_works` so they never see the file layout.
A later Plan 5 will add `iter_live_works` with the same yielded shape.
"""
import glob
import gzip
import json
from collections.abc import Iterator
from pathlib import Path


def iter_snapshot_works(
    snapshot_dir: str,
    *,
    skip_files: set[str] | None = None,
) -> Iterator[tuple[str, dict]]:
    """Yield (filepath, work_dict) from `{snapshot_dir}/updated_date=*/*.gz` in sorted order."""
    skip = skip_files or set()
    files = sorted(glob.glob(str(Path(snapshot_dir) / "updated_date=*" / "*.gz")))
    for path in files:
        if str(Path(path).resolve()) in skip:
            continue
        try:
            with gzip.open(path, "rt") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield path, json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            # corrupt or unreadable .gz — skip this file, let operator notice via counters
            continue


def iter_live_works(*args, **kwargs):
    """Not implemented in Plan 1. Plan 5 will fetch /works?from_updated_date=..."""
    raise NotImplementedError("Live mode is delivered in Plan 5")
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_work_source.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/work_source.py tests/core/snapshot/test_work_source.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): work_source iterator (snapshot files; skip resumed)"
```

---

## Task 9: `matcher.build_stub_index` + `match_work_for_stubs`

**Files:**
- Modify: `src/core/snapshot/matcher.py`
- Create: `tests/core/snapshot/test_matcher.py`

**Interfaces:**
- Consumes: existing `_norm_doi`, `_work_first_author`, `_corroborates`, `Deduplicator.normalize_title`.
- Produces:
  ```python
  @dataclass
  class StubIndex:
      doi_map: dict[str, str]            # norm_doi -> stub point_id
      arxiv_map: dict[str, str]          # arxiv_id -> stub point_id
      openalex_map: dict[str, str]       # W-id -> stub point_id
      title_map: dict[str, list[str]]    # norm_title -> [stub point_id, ...]

  def build_stub_index(stubs: list[dict]) -> StubIndex
      # Each stub dict has keys: point_id, identifier, identifier_type,
      # alternate_identifiers (dict), title (optional)

  def match_work_for_stubs(work: dict, index: StubIndex, *, all_stubs_by_id: dict[str, dict]) -> dict | None
      # Returns the matched stub dict, or None. Order: DOI > arXiv > openalex > title (corroborated).
  ```

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_matcher.py`:

```python
import gzip
import json
from pathlib import Path

from src.core.snapshot.matcher import build_stub_index, match_work_for_stubs

FIXTURE = Path(__file__).parent / "fixtures" / "works" / "tiny.jsonl.gz"
SEED_STUBS = Path(__file__).parent / "fixtures" / "corpus" / "seed_stubs.json"


def _load_work(idx: int) -> dict:
    with gzip.open(FIXTURE, "rt") as f:
        for i, ln in enumerate(f):
            if i == idx and ln.strip():
                return json.loads(ln)
    raise AssertionError(idx)


def _load_stubs() -> list[dict]:
    raw = json.loads(SEED_STUBS.read_text())
    return [
        {"point_id": e["point_id"], **e["payload"]}
        for e in raw
    ]


def test_doi_stub_match():
    stubs = _load_stubs()
    idx = build_stub_index(stubs)
    work = _load_work(4)  # W1000000005 stub-doi-001
    matched = match_work_for_stubs(work, idx, all_stubs_by_id={s["point_id"]: s for s in stubs})
    assert matched is not None
    assert matched["point_id"] == "stub-doi-001"


def test_title_stub_match():
    stubs = _load_stubs()
    idx = build_stub_index(stubs)
    work = _load_work(5)  # W1000000006 Stub Title Match Promotable
    matched = match_work_for_stubs(work, idx, all_stubs_by_id={s["point_id"]: s for s in stubs})
    assert matched is not None
    assert matched["point_id"] == "stub-title-001"


def test_no_match_returns_none():
    stubs = _load_stubs()
    idx = build_stub_index(stubs)
    work = _load_work(7)  # W1000000008 Anchor Gap Paper — not a stub
    matched = match_work_for_stubs(work, idx, all_stubs_by_id={s["point_id"]: s for s in stubs})
    assert matched is None
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_matcher.py -v
```

Expected: `ImportError: cannot import build_stub_index`.

- [ ] **Step 3: Extend `matcher.py`.**

Append to `src/core/snapshot/matcher.py`:

```python
from dataclasses import dataclass, field

from src.core.dedup import Deduplicator


@dataclass
class StubIndex:
    doi_map: dict[str, str] = field(default_factory=dict)
    arxiv_map: dict[str, str] = field(default_factory=dict)
    openalex_map: dict[str, str] = field(default_factory=dict)
    title_map: dict[str, list[str]] = field(default_factory=dict)


def build_stub_index(stubs: list[dict]) -> StubIndex:
    idx = StubIndex()
    for stub in stubs:
        pid = stub["point_id"]
        itype = stub.get("identifier_type")
        ident = stub.get("identifier") or ""

        if itype == "doi":
            doi = _norm_doi(ident[4:] if ident.startswith("doi:") else stub.get("doi") or ident)
            if doi:
                idx.doi_map.setdefault(doi, pid)
        elif itype == "arxiv":
            arxiv = ident[len("arXiv:"):] if ident.lower().startswith("arxiv:") else ident
            if arxiv:
                idx.arxiv_map.setdefault(arxiv, pid)
        elif itype == "openalex":
            wid = ident.rsplit("/", 1)[-1].replace("openalex:", "")
            if wid:
                idx.openalex_map.setdefault(wid, pid)

        # also index by title if the stub has one
        title = stub.get("title")
        if title:
            norm = Deduplicator.normalize_title(title)
            if norm:
                idx.title_map.setdefault(norm, []).append(pid)

        # alternate identifiers
        for alt_type, alt_val in (stub.get("alternate_identifiers") or {}).items():
            if alt_type == "doi":
                doi = _norm_doi(alt_val)
                if doi:
                    idx.doi_map.setdefault(doi, pid)
            elif alt_type == "arxiv":
                idx.arxiv_map.setdefault(alt_val, pid)
            elif alt_type == "openalex":
                idx.openalex_map.setdefault(alt_val, pid)
    return idx


def match_work_for_stubs(
    work: dict,
    index: StubIndex,
    *,
    all_stubs_by_id: dict[str, dict],
) -> dict | None:
    # DOI first
    doi = _norm_doi(work.get("doi") or (work.get("ids") or {}).get("doi"))
    if doi and (pid := index.doi_map.get(doi)):
        return all_stubs_by_id.get(pid)

    # arXiv
    arxiv = (work.get("ids") or {}).get("arxiv")
    if arxiv and (pid := index.arxiv_map.get(arxiv)):
        return all_stubs_by_id.get(pid)

    # OpenAlex ID
    wid = (work.get("id") or "").rsplit("/", 1)[-1]
    if wid and (pid := index.openalex_map.get(wid)):
        return all_stubs_by_id.get(pid)

    # Title with corroboration
    title = work.get("title") or work.get("display_name")
    if not title:
        return None
    norm = Deduplicator.normalize_title(title)
    if not norm:
        return None
    for pid in index.title_map.get(norm, []):
        stub = all_stubs_by_id.get(pid)
        if not stub:
            continue
        # build a Candidate-like view for the corroboration check
        cand = type("S", (), {
            "year": stub.get("year"),
            "first_author": _first_author_surname_of_stub(stub),
        })
        if _corroborates(work, cand):
            return stub
    return None


def _first_author_surname_of_stub(stub: dict) -> str | None:
    authors = stub.get("authors") or []
    if not authors:
        return None
    name = authors[0].get("display_name") or ""
    return name.strip().split()[-1].lower() if name else None
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_matcher.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/matcher.py tests/core/snapshot/test_matcher.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): build_stub_index + match_work_for_stubs (DOI/arXiv/OA/title)"
```

---

## Task 10: `storage.reader.iter_all_real_papers_minimal`

**Files:**
- Modify: `src/core/storage/reader.py`
- Modify: `src/core/storage/base.py` (facade)
- Test: `tests/core/snapshot/test_storage_extensions.py` (new, integration)

**Interfaces:**
- Produces (on PaperReader, exposed via facade):
  ```python
  def iter_all_real_papers_minimal(self, batch_size: int = 1000) -> Iterator[dict]
  # Yields {"point_id": str, "doi": str|None, "openalex_id": str|None,
  #         "title_norm": str|None, "title": str|None}
  ```
  P1 uses this to build its corpus index without loading full payloads.

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_storage_extensions.py`:

```python
"""Integration tests for snapshot-related storage extensions.

Runs against a real Qdrant. Marked `integration` so CI skips without one.
"""
import pytest

from src.core.storage import QdrantStorage

pytestmark = pytest.mark.integration


@pytest.fixture
def storage() -> QdrantStorage:
    return QdrantStorage()


def test_iter_all_real_papers_minimal_yields_required_keys(storage):
    it = storage.iter_all_real_papers_minimal(batch_size=50)
    sample = next(it)
    assert {"point_id", "doi", "openalex_id", "title_norm", "title"} <= sample.keys()


def test_iter_all_real_papers_minimal_excludes_stubs(storage):
    # if there are any stubs in the corpus, none should appear
    for entry in storage.iter_all_real_papers_minimal(batch_size=200):
        assert entry["point_id"]
        break
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py -v -m integration
```

Expected: `AttributeError: iter_all_real_papers_minimal`.

- [ ] **Step 3: Implement in `reader.py`.**

Append to `src/core/storage/reader.py`:

```python
def iter_all_real_papers_minimal(self, batch_size: int = 1000):
    """Yield {point_id, doi, openalex_id, title_norm, title} for every non-stub paper.

    Loads minimal payload (4 fields) — suitable for in-memory index building.
    """
    from src.core.dedup import Deduplicator

    flt = models.Filter(
        must_not=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))]
    )
    offset = None
    while True:
        pts, offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=flt,
            limit=batch_size,
            offset=offset,
            with_payload=["doi", "openalex_id", "title"],
            with_vectors=False,
        )
        for p in pts:
            pl = p.payload or {}
            title = pl.get("title")
            yield {
                "point_id": str(p.id),
                "doi": pl.get("doi"),
                "openalex_id": pl.get("openalex_id"),
                "title": title,
                "title_norm": Deduplicator.normalize_title(title) if title else None,
            }
        if offset is None:
            return
```

Append to `src/core/storage/base.py` facade:

```python
def iter_all_real_papers_minimal(self, batch_size: int = 1000):
    return self.readers.iter_all_real_papers_minimal(batch_size)
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_iter_all_real_papers_minimal_yields_required_keys -v -m integration
```

Expected: PASS (skipped if Qdrant unavailable, which is acceptable in CI).

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/reader.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): iter_all_real_papers_minimal (minimal payload index)"
```

---

## Task 11: `storage.reader.build_referenced_openalex_id_set`

**Files:**
- Modify: `src/core/storage/reader.py`, `src/core/storage/base.py`
- Test: append to `tests/core/snapshot/test_storage_extensions.py`

**Interfaces:**
- Produces:
  ```python
  def build_referenced_openalex_id_set(self) -> dict[str, int]
  # {raw OpenAlex Work ID -> in-corpus citer count}
  ```

- [ ] **Step 1: Append the failing test.**

Append to `tests/core/snapshot/test_storage_extensions.py`:

```python
def test_build_referenced_openalex_id_set(storage):
    m = storage.build_referenced_openalex_id_set()
    assert isinstance(m, dict)
    # at least one referenced work
    assert any(v >= 1 for v in m.values())
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_build_referenced_openalex_id_set -v -m integration
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement.**

Append to `reader.py`:

```python
def build_referenced_openalex_id_set(self) -> dict[str, int]:
    """Return {OpenAlex Work ID -> in-corpus citer count} across all real papers."""
    counts: dict[str, int] = {}
    flt = models.Filter(
        must_not=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))]
    )
    offset = None
    while True:
        pts, offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=flt,
            limit=500,
            offset=offset,
            with_payload=["referenced_works"],
            with_vectors=False,
        )
        for p in pts:
            for ref in (p.payload or {}).get("referenced_works") or []:
                wid = ref.rsplit("/", 1)[-1] if isinstance(ref, str) else None
                if wid and wid.startswith("W"):
                    counts[wid] = counts.get(wid, 0) + 1
        if offset is None:
            return counts
```

Append facade:

```python
def build_referenced_openalex_id_set(self) -> dict[str, int]:
    return self.readers.build_referenced_openalex_id_set()
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_build_referenced_openalex_id_set -v -m integration
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/reader.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): build_referenced_openalex_id_set (anchor set for P3)"
```

---

## Task 12: `storage.reader.build_openalex_id_to_point_id_map`

**Files:**
- Modify: `src/core/storage/reader.py`, `src/core/storage/base.py`
- Test: append to `tests/core/snapshot/test_storage_extensions.py`

**Interfaces:**
- Produces:
  ```python
  def build_openalex_id_to_point_id_map(self) -> dict[str, str]
  # {OA Work ID -> point_id} across all real papers
  ```

- [ ] **Step 1: Append the failing test.**

```python
def test_build_openalex_id_to_point_id_map(storage):
    m = storage.build_openalex_id_to_point_id_map()
    assert isinstance(m, dict)
    # values are point_id strings
    for v in m.values():
        assert isinstance(v, str)
        break
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_build_openalex_id_to_point_id_map -v -m integration
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement.**

Append to `reader.py`:

```python
def build_openalex_id_to_point_id_map(self) -> dict[str, str]:
    """Return {OpenAlex Work ID -> point_id} for every non-stub paper that has an openalex_id."""
    out: dict[str, str] = {}
    flt = models.Filter(
        must=[models.IsEmptyCondition(is_empty=models.PayloadField(key="openalex_id"))],
    )
    has_oa = models.Filter(
        must_not=[
            models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
            models.IsEmptyCondition(is_empty=models.PayloadField(key="openalex_id")),
        ]
    )
    offset = None
    while True:
        pts, offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=has_oa,
            limit=500,
            offset=offset,
            with_payload=["openalex_id"],
            with_vectors=False,
        )
        for p in pts:
            oa = (p.payload or {}).get("openalex_id")
            if oa:
                out[oa] = str(p.id)
        if offset is None:
            return out
```

Append facade:

```python
def build_openalex_id_to_point_id_map(self) -> dict[str, str]:
    return self.readers.build_openalex_id_to_point_id_map()
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_build_openalex_id_to_point_id_map -v -m integration
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/reader.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): build_openalex_id_to_point_id_map (P4 cited_by mapper)"
```

---

## Task 13: `storage.reader.build_identifier_index_for_dedup`

**Files:**
- Modify: `src/core/storage/reader.py`, `src/core/storage/base.py`
- Test: append to `tests/core/snapshot/test_storage_extensions.py`

**Interfaces:**
- Produces:
  ```python
  def build_identifier_index_for_dedup(self) -> dict[str, set[str]]
  # {"doi": {normalized_dois}, "openalex_id": {Wids}, "title_norm": {titles}}
  # Includes BOTH real papers AND stubs (P3 must not re-inject existing stub identifiers)
  ```

- [ ] **Step 1: Append the failing test.**

```python
def test_build_identifier_index_for_dedup(storage):
    idx = storage.build_identifier_index_for_dedup()
    assert {"doi", "openalex_id", "title_norm"} <= idx.keys()
    for v in idx.values():
        assert isinstance(v, set)
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_build_identifier_index_for_dedup -v -m integration
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement.**

Append to `reader.py`:

```python
def build_identifier_index_for_dedup(self) -> dict[str, set[str]]:
    """Return all known identifiers in the corpus (real + stubs) for P3 dedup."""
    from src.core.dedup import Deduplicator

    out: dict[str, set[str]] = {"doi": set(), "openalex_id": set(), "title_norm": set()}
    offset = None
    while True:
        pts, offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=None,
            limit=500,
            offset=offset,
            with_payload=["doi", "openalex_id", "title"],
            with_vectors=False,
        )
        for p in pts:
            pl = p.payload or {}
            if pl.get("doi"):
                out["doi"].add(pl["doi"])
            if pl.get("openalex_id"):
                out["openalex_id"].add(pl["openalex_id"])
            if pl.get("title"):
                n = Deduplicator.normalize_title(pl["title"])
                if n:
                    out["title_norm"].add(n)
        if offset is None:
            return out
```

Append facade:

```python
def build_identifier_index_for_dedup(self) -> dict[str, set[str]]:
    return self.readers.build_identifier_index_for_dedup()
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_build_identifier_index_for_dedup -v -m integration
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/reader.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): build_identifier_index_for_dedup (P3 dedup set)"
```

---

## Task 14: `storage.stubs.iter_stubs_for_resolution`

**Files:**
- Modify: `src/core/storage/stubs.py`, `src/core/storage/base.py`
- Test: append to `tests/core/snapshot/test_storage_extensions.py`

**Interfaces:**
- Produces (on StubManager, via facade):
  ```python
  def iter_stubs_for_resolution(self, batch_size: int = 500) -> Iterator[dict]
  # Yields {"point_id", "identifier", "identifier_type", "doi", "arxiv_id", "openalex_id",
  #         "title", "year", "first_author", "cited_by", "cited_by_count_internal",
  #         "alternate_identifiers"}
  ```

- [ ] **Step 1: Append the failing test.**

```python
def test_iter_stubs_for_resolution(storage):
    it = storage.iter_stubs_for_resolution(batch_size=100)
    try:
        sample = next(it)
    except StopIteration:
        pytest.skip("No stubs in corpus")
    assert {"point_id", "identifier_type", "cited_by"} <= sample.keys()
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_iter_stubs_for_resolution -v -m integration
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement in `stubs.py`.**

Append:

```python
def iter_stubs_for_resolution(self, batch_size: int = 500):
    """Yield stub dicts shaped for the P2 matcher and promotion logic."""
    flt = models.Filter(
        must=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))]
    )
    offset = None
    while True:
        pts, offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=flt,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in pts:
            pl = p.payload or {}
            first = None
            if authors := pl.get("authors"):
                name = (authors[0] or {}).get("display_name") if isinstance(authors[0], dict) else None
                if name:
                    first = name.split()[-1].lower()
            yield {
                "point_id": str(p.id),
                "identifier": pl.get("identifier"),
                "identifier_type": pl.get("identifier_type"),
                "doi": pl.get("doi"),
                "arxiv_id": pl.get("arxiv_id"),
                "openalex_id": pl.get("openalex_id"),
                "title": pl.get("title"),
                "year": pl.get("year"),
                "first_author": first,
                "authors": pl.get("authors") or [],
                "cited_by": list(pl.get("cited_by") or []),
                "cited_by_count_internal": pl.get("cited_by_count_internal", 0),
                "alternate_identifiers": pl.get("alternate_identifiers") or {},
            }
        if offset is None:
            return
```

Append facade:

```python
def iter_stubs_for_resolution(self, batch_size: int = 500):
    return self.stubs.iter_stubs_for_resolution(batch_size)
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_iter_stubs_for_resolution -v -m integration
```

Expected: PASS (or skip if no stubs).

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/stubs.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): iter_stubs_for_resolution (P2 stub iterator)"
```

---

## Task 15: `storage.stubs.find_real_by_identifier`

**Files:**
- Modify: `src/core/storage/stubs.py`, `src/core/storage/base.py`
- Test: append to `tests/core/snapshot/test_storage_extensions.py`

**Interfaces:**
- Produces:
  ```python
  def find_real_by_identifier(self, fields: dict) -> str | None
  # fields contains "doi", "openalex_id", "arxiv_id". Returns point_id of matching REAL paper or None.
  ```

- [ ] **Step 1: Append the failing test.**

```python
def test_find_real_by_identifier_returns_none_for_unknown(storage):
    pid = storage.find_real_by_identifier({"doi": "10.9999/does-not-exist"})
    assert pid is None
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_find_real_by_identifier_returns_none_for_unknown -v -m integration
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement.**

Append to `stubs.py`:

```python
def find_real_by_identifier(self, fields: dict) -> str | None:
    """Find a non-stub paper matching any of doi/openalex_id/arxiv_id; return point_id or None."""
    real_only = models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))
    for key in ("doi", "openalex_id", "arxiv_id"):
        v = fields.get(key)
        if not v:
            continue
        flt = models.Filter(
            must=[models.FieldCondition(key=key, match=models.MatchValue(value=v))],
            must_not=[real_only],
        )
        pts, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=flt,
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        if pts:
            return str(pts[0].id)
    return None
```

Append facade:

```python
def find_real_by_identifier(self, fields: dict) -> str | None:
    return self.stubs.find_real_by_identifier(fields)
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_find_real_by_identifier_returns_none_for_unknown -v -m integration
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/stubs.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): find_real_by_identifier (dedup guard for promotion)"
```

---

## Task 16: `storage.stubs.merge_stub_into_real`

**Files:**
- Modify: `src/core/storage/stubs.py`, `src/core/storage/base.py`
- Test: append to `tests/core/snapshot/test_storage_extensions.py`

**Interfaces:**
- Produces:
  ```python
  def merge_stub_into_real(self, stub_point_id: str, real_point_id: str) -> None
  # Unions stub.cited_by into real.cited_by + real.cited_by_count, then DELETES the stub point.
  ```

- [ ] **Step 1: Append the failing test.**

```python
def test_merge_stub_into_real_idempotent(storage):
    # Self-merge: ensure no exception when called with same id (degenerate but defensive)
    with pytest.raises(ValueError):
        storage.merge_stub_into_real("X", "X")
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_merge_stub_into_real_idempotent -v -m integration
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement.**

Append to `stubs.py`:

```python
def merge_stub_into_real(self, stub_point_id: str, real_point_id: str) -> None:
    """Union stub.cited_by into real.cited_by, then delete the stub.

    Defensive: refuses self-merge.
    """
    if stub_point_id == real_point_id:
        raise ValueError("cannot merge a point into itself")
    stub_pts, _ = self.client.scroll(
        collection_name=self.collection_name,
        scroll_filter=models.Filter(must=[models.HasIdCondition(has_id=[stub_point_id])]),
        with_payload=["cited_by", "alternate_identifiers"], with_vectors=False, limit=1,
    )
    if not stub_pts:
        return
    real_pts, _ = self.client.scroll(
        collection_name=self.collection_name,
        scroll_filter=models.Filter(must=[models.HasIdCondition(has_id=[real_point_id])]),
        with_payload=["cited_by", "alternate_identifiers"], with_vectors=False, limit=1,
    )
    if not real_pts:
        return
    stub_pl = stub_pts[0].payload or {}
    real_pl = real_pts[0].payload or {}
    merged = sorted(set(stub_pl.get("cited_by") or []) | set(real_pl.get("cited_by") or []))
    merged_alt = {**(real_pl.get("alternate_identifiers") or {}), **(stub_pl.get("alternate_identifiers") or {})}
    self.client.set_payload(
        collection_name=self.collection_name,
        payload={
            "cited_by": merged,
            "cited_by_count": len(merged),
            "alternate_identifiers": merged_alt,
        },
        points=[real_point_id],
    )
    self.client.delete(
        collection_name=self.collection_name,
        points_selector=models.PointIdsList(points=[stub_point_id]),
    )
```

Append facade:

```python
def merge_stub_into_real(self, stub_point_id: str, real_point_id: str) -> None:
    return self.stubs.merge_stub_into_real(stub_point_id, real_point_id)
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_merge_stub_into_real_idempotent -v -m integration
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/stubs.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): merge_stub_into_real (cited_by union + stub delete)"
```

---

## Task 17: `storage.writer.batch_apply_field_fill`

**Files:**
- Modify: `src/core/storage/writer.py`, `src/core/storage/base.py`
- Test: append to `tests/core/snapshot/test_storage_extensions.py`

**Interfaces:**
- Produces:
  ```python
  def batch_apply_field_fill(self, updates: list[tuple[str, dict]], *, provenance_key: str = "snapshot_filled_at") -> int
  # For each (point_id, fields), set_payload(fields + {provenance_key: utc_iso_date()}).
  # Returns number applied.
  ```

- [ ] **Step 1: Append the failing test.**

```python
def test_batch_apply_field_fill_returns_count(storage):
    n = storage.batch_apply_field_fill([], provenance_key="snapshot_filled_at")
    assert n == 0
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_batch_apply_field_fill_returns_count -v -m integration
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement.**

Append to `writer.py`:

```python
from datetime import datetime, timezone

def _utc_iso_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def batch_apply_field_fill(
    self,
    updates: list[tuple[str, dict]],
    *,
    provenance_key: str = "snapshot_filled_at",
) -> int:
    """Apply fill-only-missing payload merges with provenance stamp. Returns count applied."""
    today = _utc_iso_date()
    n = 0
    for point_id, fields in updates:
        if not fields:
            continue
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={**fields, provenance_key: today},
            points=[point_id],
        )
        n += 1
    return n
```

Append facade:

```python
def batch_apply_field_fill(self, updates: list[tuple[str, dict]], *, provenance_key: str = "snapshot_filled_at") -> int:
    return self.writers.batch_apply_field_fill(updates, provenance_key=provenance_key)
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_batch_apply_field_fill_returns_count -v -m integration
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/writer.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): batch_apply_field_fill (P1/P2 in-place enrichment)"
```

---

## Task 18: `storage.writer.batch_promote_stubs`

**Files:**
- Modify: `src/core/storage/writer.py`, `src/core/storage/base.py`
- Test: append to `tests/core/snapshot/test_storage_extensions.py`

**Interfaces:**
- Produces:
  ```python
  def batch_promote_stubs(self, promotions: list[dict]) -> list[dict]
  # Each promotion: {"point_id", "work_fields", "preserved_cited_by", "preserved_cited_by_count_internal", "preserved_alternate_identifiers"}
  # Returns per-item result: {"point_id", "status": "promoted"|"verify_failed"|"error", "error"?: str}
  ```

- [ ] **Step 1: Append the failing test.**

```python
def test_batch_promote_stubs_empty(storage):
    out = storage.batch_promote_stubs([])
    assert out == []
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_batch_promote_stubs_empty -v -m integration
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement.**

Append to `writer.py`:

```python
from datetime import datetime, timezone


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def batch_promote_stubs(self, promotions: list[dict]) -> list[dict]:
    """Atomic-per-item stub→real promotion with verify+rollback."""
    results: list[dict] = []
    today = _utc_iso_date()
    for pr in promotions:
        pid = pr["point_id"]
        fields = pr["work_fields"]
        cited_by = pr.get("preserved_cited_by") or []
        try:
            payload = {
                **fields,
                "is_stub": False,
                "cited_by": list(cited_by),
                "cited_by_count": len(cited_by),
                "cited_by_count_internal": pr.get("preserved_cited_by_count_internal", 0),
                "alternate_identifiers": pr.get("preserved_alternate_identifiers") or {},
                "promoted_from_stub": True,
                "promoted_at": _utc_iso(),
                "snapshot_filled_at": today,
            }
            self.client.set_payload(
                collection_name=self.collection_name,
                payload=payload,
                points=[pid],
            )
            # verify
            verify_pts, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(must=[models.HasIdCondition(has_id=[pid])]),
                with_payload=["is_stub", "cited_by"], with_vectors=False, limit=1,
            )
            after = (verify_pts[0].payload or {}) if verify_pts else {}
            if after.get("is_stub") is not False or set(after.get("cited_by") or []) < set(cited_by):
                results.append({"point_id": pid, "status": "verify_failed"})
                continue
            results.append({"point_id": pid, "status": "promoted"})
        except Exception as e:
            results.append({"point_id": pid, "status": "error", "error": str(e)})
    return results
```

Append facade:

```python
def batch_promote_stubs(self, promotions: list[dict]) -> list[dict]:
    return self.writers.batch_promote_stubs(promotions)
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_batch_promote_stubs_empty -v -m integration
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/writer.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): batch_promote_stubs (verify+rollback transaction)"
```

---

## Task 19: `storage.writer.batch_inject_papers`

**Files:**
- Modify: `src/core/storage/writer.py`, `src/core/storage/base.py`
- Test: append to `tests/core/snapshot/test_storage_extensions.py`

**Interfaces:**
- Produces:
  ```python
  def batch_inject_papers(self, papers: list[dict]) -> list[dict]
  # Each: {"openalex_id", "work_fields", "injection_path": "anchor"|"concept"}
  # Returns: [{"openalex_id", "point_id"|None, "status": "created"|"skipped_dup"|"failed"}, ...]
  ```

- [ ] **Step 1: Append the failing test.**

```python
def test_batch_inject_papers_empty(storage):
    out = storage.batch_inject_papers([])
    assert out == []
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_batch_inject_papers_empty -v -m integration
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement.**

Append to `writer.py`:

```python
import uuid


def _injected_point_id(openalex_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"openalex:{openalex_id}"))


def batch_inject_papers(self, papers: list[dict]) -> list[dict]:
    """Create new real-paper points from snapshot works. One upsert per item (safety > throughput)."""
    from qdrant_client.models import PointStruct

    today = _utc_iso_date()
    results: list[dict] = []
    for entry in papers:
        oa = entry["openalex_id"]
        fields = entry["work_fields"]
        pid = _injected_point_id(oa)
        # dedup guard via find by openalex_id
        existing = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="openalex_id", match=models.MatchValue(value=oa))]
            ),
            limit=1, with_payload=False, with_vectors=False,
        )[0]
        if existing:
            results.append({"openalex_id": oa, "point_id": None, "status": "skipped_dup"})
            continue
        payload = {
            **fields,
            "is_stub": False,
            "injected_from_snapshot": True,
            "injection_path": entry.get("injection_path", "unknown"),
            "injected_at": _utc_iso(),
            "snapshot_filled_at": today,
        }
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[PointStruct(id=pid, vector={}, payload=payload)],
            )
            results.append({"openalex_id": oa, "point_id": pid, "status": "created"})
        except Exception as e:
            results.append({"openalex_id": oa, "point_id": None, "status": "failed", "error": str(e)})
    return results
```

Append facade:

```python
def batch_inject_papers(self, papers: list[dict]) -> list[dict]:
    return self.writers.batch_inject_papers(papers)
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_batch_inject_papers_empty -v -m integration
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/writer.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): batch_inject_papers (P3 new-real injection, per-item upsert)"
```

---

## Task 20: `storage.writer.batch_extend_external_cited_by`

**Files:**
- Modify: `src/core/storage/writer.py`, `src/core/storage/base.py`
- Test: append to `tests/core/snapshot/test_storage_extensions.py`

**Interfaces:**
- Produces:
  ```python
  def batch_extend_external_cited_by(self, updates: dict[str, list[dict]], *, cap: int = 300) -> int
  # updates: {point_id: [citer_entry, ...]} where citer_entry = {"openalex_id", "year", "venue", "cited_by_count"}
  # Read-modify-write per point, union by openalex_id, truncate to `cap` by (year DESC, cited_by_count DESC).
  # Returns total citer entries added across all points.
  ```

- [ ] **Step 1: Append the failing test.**

```python
def test_batch_extend_external_cited_by_empty(storage):
    n = storage.batch_extend_external_cited_by({})
    assert n == 0
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_batch_extend_external_cited_by_empty -v -m integration
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement.**

Append to `writer.py`:

```python
import threading

_POINT_LOCKS: dict[str, threading.Lock] = {}
_POINT_LOCKS_GUARD = threading.Lock()


def _point_lock(point_id: str) -> threading.Lock:
    with _POINT_LOCKS_GUARD:
        lk = _POINT_LOCKS.get(point_id)
        if lk is None:
            if len(_POINT_LOCKS) > 10000:
                # cheap LRU: drop ~half. The lost locks at worst cause a momentary
                # serialization gap; correctness still holds because each citer entry
                # is deduplicated by openalex_id on read.
                for k in list(_POINT_LOCKS)[: len(_POINT_LOCKS) // 2]:
                    _POINT_LOCKS.pop(k, None)
            lk = _POINT_LOCKS.setdefault(point_id, threading.Lock())
        return lk


def batch_extend_external_cited_by(
    self,
    updates: dict[str, list[dict]],
    *,
    cap: int = 300,
) -> int:
    """Append citer entries to each point's external_cited_by (union + truncate)."""
    total = 0
    for point_id, new_entries in updates.items():
        if not new_entries:
            continue
        lk = _point_lock(point_id)
        with lk:
            cur_pts, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(must=[models.HasIdCondition(has_id=[point_id])]),
                with_payload=["external_cited_by"], with_vectors=False, limit=1,
            )
            if not cur_pts:
                continue
            existing = (cur_pts[0].payload or {}).get("external_cited_by") or []
            by_id: dict[str, dict] = {e["openalex_id"]: e for e in existing if e.get("openalex_id")}
            added = 0
            for entry in new_entries:
                oa = entry.get("openalex_id")
                if not oa or oa in by_id:
                    continue
                by_id[oa] = entry
                added += 1
            merged = sorted(
                by_id.values(),
                key=lambda x: (x.get("year") or 0, x.get("cited_by_count") or 0),
                reverse=True,
            )[:cap]
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"external_cited_by": merged, "external_cited_by_count": len(merged)},
                points=[point_id],
            )
            total += added
    return total
```

Append facade:

```python
def batch_extend_external_cited_by(self, updates: dict[str, list[dict]], *, cap: int = 300) -> int:
    return self.writers.batch_extend_external_cited_by(updates, cap=cap)
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_storage_extensions.py::test_batch_extend_external_cited_by_empty -v -m integration
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add src/core/storage/writer.py src/core/storage/base.py tests/core/snapshot/test_storage_extensions.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(storage): batch_extend_external_cited_by (per-point lock, dedup, cap=300)"
```

---

## Task 21: `stats.py` — per-phase summary dataclasses

**Files:**
- Create: `src/core/snapshot/stats.py`
- Test: `tests/core/snapshot/test_stats.py`

**Interfaces:**
- Produces:
  ```python
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
      extra: dict[str, int | float | str | list] = field(default_factory=dict)

      def to_log_line(self) -> str
      def to_dagster_metadata(self) -> dict
  ```

- [ ] **Step 1: Write the failing test.**

Create `tests/core/snapshot/test_stats.py`:

```python
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
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_stats.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement.**

Create `src/core/snapshot/stats.py`:

```python
"""Per-phase summary dataclass shared by all snapshot phases."""
from dataclasses import dataclass, field


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
        return {
            "scanned": self.scanned,
            "matched": self.matched,
            "applied": self.applied,
            "worker_errors": self.worker_errors,
            "failed_batches": self.failed_batches,
            "quarantined": self.quarantined,
            "duration_s": self.duration_s,
            **self.extra,
        }
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_stats.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit.**

```bash
git add src/core/snapshot/stats.py tests/core/snapshot/test_stats.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "feat(snapshot): PhaseSummary dataclass (log + Dagster metadata helpers)"
```

---

## Task 22: Deprecate existing `runner.py` as alias

**Files:**
- Modify: `src/core/snapshot/runner.py`

**Interfaces:**
- `run_snapshot_enrichment` remains callable; emits `DeprecationWarning` pointing to `enrich-corpus-fields` (Plan 2 CLI).

- [ ] **Step 1: Read current file.**

```bash
head -25 src/core/snapshot/runner.py
```

- [ ] **Step 2: Edit to add deprecation.**

Edit `src/core/snapshot/runner.py` — at the top of `run_snapshot_enrichment`, insert:

```python
import warnings


def run_snapshot_enrichment(storage, snapshot_dir, dry_run=False, batch_size=500):
    warnings.warn(
        "run_snapshot_enrichment is deprecated. Use src.core.snapshot.phase1_corpus_fields.run() "
        "(CLI: `enrich-corpus-fields`) which covers all 15 metadata fields, not just abstract+refs.",
        DeprecationWarning,
        stacklevel=2,
    )
    # ... existing body unchanged ...
```

(Preserve the existing function body verbatim — only the `warnings.warn` line is added at the top.)

- [ ] **Step 3: Verify warning is emitted in a smoke test.**

```bash
uv run python -c "
import warnings
warnings.simplefilter('always')
from src.core.snapshot.runner import run_snapshot_enrichment
with warnings.catch_warnings(record=True) as w:
    try:
        run_snapshot_enrichment(None, '/nonexistent', dry_run=True)
    except Exception: pass
    assert any('deprecated' in str(x.message).lower() for x in w), 'no deprecation warning'
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 4: Commit.**

```bash
git add src/core/snapshot/runner.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "refactor(snapshot): deprecate runner.run_snapshot_enrichment in favor of phase1"
```

---

## Task 23: Add mock_storage methods used by Plans 2/3/4

**Files:**
- Modify: `tests/core/snapshot/conftest.py`
- Modify: `tests/core/snapshot/test_mock_storage.py`

**Interfaces:**
- Adds to `_MockStorage`:
  ```
  iter_all_real_papers_minimal(batch_size=1000) -> Iterator[dict]
  build_referenced_openalex_id_set() -> dict[str, int]
  build_openalex_id_to_point_id_map() -> dict[str, str]
  build_identifier_index_for_dedup() -> dict[str, set[str]]
  iter_stubs_for_resolution(batch_size=500) -> Iterator[dict]
  find_real_by_identifier(fields) -> str | None
  merge_stub_into_real(stub_pid, real_pid) -> None
  batch_apply_field_fill(updates, *, provenance_key="snapshot_filled_at") -> int
  batch_promote_stubs(promotions) -> list[dict]
  batch_inject_papers(papers) -> list[dict]
  batch_extend_external_cited_by(updates, *, cap=300) -> int
  ```

- [ ] **Step 1: Append failing tests.**

Append to `tests/core/snapshot/test_mock_storage.py`:

```python
def test_mock_iter_real_papers_minimal(mock_storage):
    mock_storage.seed_from_json(FIXTURE)
    out = list(mock_storage.iter_all_real_papers_minimal())
    assert len(out) == 10
    assert "title_norm" in out[0]


def test_mock_build_referenced_anchor(mock_storage):
    mock_storage.seed_from_json(FIXTURE)
    m = mock_storage.build_referenced_openalex_id_set()
    # at least one ref present in seeds; we asserted real-005..010 include W1000000008
    assert m.get("W1000000008", 0) >= 2


def test_mock_batch_apply_field_fill_stamps_provenance(mock_storage):
    mock_storage.set_payload("p", {"a": 1})
    n = mock_storage.batch_apply_field_fill([("p", {"b": 2})])
    assert n == 1
    pl = mock_storage.get_payload("p")
    assert pl["b"] == 2
    assert "snapshot_filled_at" in pl


def test_mock_batch_inject_papers_creates_then_skips_dup(mock_storage):
    out1 = mock_storage.batch_inject_papers([
        {"openalex_id": "W42", "work_fields": {"title": "X", "openalex_id": "W42"}, "injection_path": "anchor"}
    ])
    assert out1[0]["status"] == "created"
    out2 = mock_storage.batch_inject_papers([
        {"openalex_id": "W42", "work_fields": {"title": "X", "openalex_id": "W42"}, "injection_path": "anchor"}
    ])
    assert out2[0]["status"] == "skipped_dup"
```

- [ ] **Step 2: Run, confirm fail.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_mock_storage.py -v
```

Expected: 4 new failures.

- [ ] **Step 3: Extend `_MockStorage` in `conftest.py`.**

Append to the class body:

```python
    # ----- read helpers used by phases -----
    def iter_all_real_papers_minimal(self, batch_size: int = 1000):
        from src.core.dedup import Deduplicator
        for pid, pl in self._payloads.items():
            if pl.get("is_stub") is True:
                continue
            title = pl.get("title")
            yield {
                "point_id": pid,
                "doi": pl.get("doi"),
                "openalex_id": pl.get("openalex_id"),
                "title": title,
                "title_norm": Deduplicator.normalize_title(title) if title else None,
            }

    def build_referenced_openalex_id_set(self) -> dict:
        out: dict = {}
        for pid, pl in self._payloads.items():
            if pl.get("is_stub") is True:
                continue
            for ref in pl.get("referenced_works") or []:
                wid = ref.rsplit("/", 1)[-1] if isinstance(ref, str) else None
                if wid and wid.startswith("W"):
                    out[wid] = out.get(wid, 0) + 1
        return out

    def build_openalex_id_to_point_id_map(self) -> dict:
        out: dict = {}
        for pid, pl in self._payloads.items():
            if pl.get("is_stub") is True:
                continue
            if oa := pl.get("openalex_id"):
                out[oa] = pid
        return out

    def build_identifier_index_for_dedup(self) -> dict:
        from src.core.dedup import Deduplicator
        out = {"doi": set(), "openalex_id": set(), "title_norm": set()}
        for _, pl in self._payloads.items():
            if pl.get("doi"):
                out["doi"].add(pl["doi"])
            if pl.get("openalex_id"):
                out["openalex_id"].add(pl["openalex_id"])
            if pl.get("title"):
                n = Deduplicator.normalize_title(pl["title"])
                if n:
                    out["title_norm"].add(n)
        return out

    def iter_stubs_for_resolution(self, batch_size: int = 500):
        for pid, pl in self._payloads.items():
            if pl.get("is_stub") is not True:
                continue
            yield {
                "point_id": pid,
                "identifier": pl.get("identifier"),
                "identifier_type": pl.get("identifier_type"),
                "doi": pl.get("doi"),
                "arxiv_id": pl.get("arxiv_id"),
                "openalex_id": pl.get("openalex_id"),
                "title": pl.get("title"),
                "year": pl.get("year"),
                "first_author": None,
                "authors": pl.get("authors") or [],
                "cited_by": list(pl.get("cited_by") or []),
                "cited_by_count_internal": pl.get("cited_by_count_internal", 0),
                "alternate_identifiers": pl.get("alternate_identifiers") or {},
            }

    def find_real_by_identifier(self, fields: dict) -> str | None:
        for pid, pl in self._payloads.items():
            if pl.get("is_stub") is True:
                continue
            for key in ("doi", "openalex_id", "arxiv_id"):
                if (v := fields.get(key)) and pl.get(key) == v:
                    return pid
        return None

    def merge_stub_into_real(self, stub_pid: str, real_pid: str) -> None:
        if stub_pid == real_pid:
            raise ValueError("cannot merge a point into itself")
        stub = self._payloads.get(stub_pid)
        real = self._payloads.get(real_pid)
        if not stub or not real:
            return
        merged = sorted(set(stub.get("cited_by") or []) | set(real.get("cited_by") or []))
        real["cited_by"] = merged
        real["cited_by_count"] = len(merged)
        real["alternate_identifiers"] = {**(real.get("alternate_identifiers") or {}), **(stub.get("alternate_identifiers") or {})}
        del self._payloads[stub_pid]

    # ----- write helpers -----
    def batch_apply_field_fill(self, updates, *, provenance_key: str = "snapshot_filled_at") -> int:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        n = 0
        for pid, fields in updates:
            if not fields:
                continue
            self.set_payload(pid, {**fields, provenance_key: today})
            n += 1
        return n

    def batch_promote_stubs(self, promotions) -> list[dict]:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        results = []
        for pr in promotions:
            pid = pr["point_id"]
            fields = pr["work_fields"]
            cited_by = pr.get("preserved_cited_by") or []
            self.set_payload(pid, {
                **fields,
                "is_stub": False,
                "cited_by": list(cited_by),
                "cited_by_count": len(cited_by),
                "cited_by_count_internal": pr.get("preserved_cited_by_count_internal", 0),
                "alternate_identifiers": pr.get("preserved_alternate_identifiers") or {},
                "promoted_from_stub": True,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_filled_at": today,
            })
            results.append({"point_id": pid, "status": "promoted"})
        return results

    def batch_inject_papers(self, papers) -> list[dict]:
        from datetime import datetime, timezone
        import uuid
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        results = []
        for entry in papers:
            oa = entry["openalex_id"]
            # dedup by openalex_id
            dup = any(pl.get("openalex_id") == oa for pl in self._payloads.values())
            if dup:
                results.append({"openalex_id": oa, "point_id": None, "status": "skipped_dup"})
                continue
            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"openalex:{oa}"))
            self._payloads[pid] = {
                **entry["work_fields"],
                "is_stub": False,
                "injected_from_snapshot": True,
                "injection_path": entry.get("injection_path", "unknown"),
                "injected_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_filled_at": today,
            }
            results.append({"openalex_id": oa, "point_id": pid, "status": "created"})
        return results

    def batch_extend_external_cited_by(self, updates: dict, *, cap: int = 300) -> int:
        total = 0
        for pid, new_entries in updates.items():
            if pid not in self._payloads:
                continue
            existing = self._payloads[pid].get("external_cited_by") or []
            by_id = {e["openalex_id"]: e for e in existing if e.get("openalex_id")}
            for entry in new_entries:
                oa = entry.get("openalex_id")
                if not oa or oa in by_id:
                    continue
                by_id[oa] = entry
                total += 1
            merged = sorted(by_id.values(),
                            key=lambda x: (x.get("year") or 0, x.get("cited_by_count") or 0),
                            reverse=True)[:cap]
            self._payloads[pid]["external_cited_by"] = merged
            self._payloads[pid]["external_cited_by_count"] = len(merged)
        return total
```

- [ ] **Step 4: Run, confirm pass.**

```bash
uv run --extra dev pytest tests/core/snapshot/test_mock_storage.py -v
```

Expected: 8 passed total.

- [ ] **Step 5: Commit.**

```bash
git add tests/core/snapshot/conftest.py tests/core/snapshot/test_mock_storage.py
git -c user.name=rabqatab -c user.email=minhan.nick.cho@gmail.com commit -m \
    "test(snapshot): extend mock_storage with the 11 phase methods (P1-P4 ready)"
```

---

## Task 24: Final verification — full L1+L2 test suite + dagster validate

- [ ] **Step 1: Run the snapshot test directory in full.**

```bash
uv run --extra dev pytest tests/core/snapshot/ -v -m "not snapshot_live and not integration"
```

Expected: all tests pass; report ≥ ~30 tests run.

- [ ] **Step 2: Run integration tests if Qdrant is up.**

```bash
uv run --extra dev pytest tests/core/snapshot/ -v -m integration
```

Expected: pass or graceful skip.

- [ ] **Step 3: Validate Dagster (no asset changes yet, but ensure imports still work).**

```bash
uv run dagster definitions validate -m src.orchestration.definitions
```

Expected: `All code locations passed validation.`

- [ ] **Step 4: Confirm no closed-source regressions.**

```bash
grep -rinE "genai|gemini|google-genai" src/core/snapshot/ || echo "(clean)"
```

Expected: `(clean)`.

- [ ] **Step 5: Final commit only if anything changed.**

```bash
git status --short
# If nothing to commit, Plan 1 is done.
```

---

## Plan 1 Self-Review Notes

- **Spec §4 module structure:** all 5 new files (`extractor`, `work_source`, `checkpoint`, `embedding_queue`, `stats`) + the 3 storage extensions are covered. `promotion.py`, `gap_filter.py`, and the `phase*` modules are deferred to later plans by design.
- **Spec §8 testing:** L1 unit tests for every new module; L2 phase tests come with the phase plans; L3 snapshot_live marker registered.
- **Spec §11 documentation:** `tests/core/snapshot/README.md` and `fixtures/README.md` created here; pipeline / runbook docs ship with the phase plans.
- **Spec §13 risks:**
  - R3 (queue stalls): `embedding_queue.depth()` is the input to the warn-check in Plan 2.
  - R4 (external_cited_by explosion): `batch_extend_external_cited_by` defaults `cap=300` and truncates deterministically by `(year DESC, cited_by_count DESC)`.
  - R7 (live+quarterly race): `_point_lock` LRU dict serializes per-point writes.
- **Type consistency:** all storage extensions return the exact types declared in the Interfaces blocks; `_MockStorage` mirrors them. `StubIndex`/`PhaseSummary` are dataclasses (immutable in spirit but mutable by default for ergonomics).
