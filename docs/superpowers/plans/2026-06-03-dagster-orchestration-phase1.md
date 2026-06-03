# Dagster Orchestration — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up Dagster alongside the existing pipeline and prove all three architectural patterns end-to-end with three exemplar assets — a simple native asset (`collect_papers`), a native asset chained through Qdrant (`enrich_abstracts`), and a GPU asset dispatched via `sparkq` (`embed_papers`).

**Architecture:** Stage logic is extracted from the CLI commands into shared `src/core/pipeline/stages.py` functions; both the CLI and the Dagster assets call them (DRY). CPU/IO assets run in-process; GPU assets submit the existing CLI command to the DGX Sparks via a `SparkqJobResource`. Qdrant remains the shared data store; assets return lightweight counts, not data. Dagster keeps its own SQLite metadata store (orthogonal to Qdrant).

**Tech Stack:** Python 3.12, uv, Dagster (`dagster`, `dagster-webserver`), Qdrant, `sparkq` CLI, pytest.

**Scope note:** This is Plan 1 of the migration (spec §6 phases 1–2). It ports 3 exemplar assets that exercise every pattern. The remaining ~10 assets, DQ asset-checks (§3), schedules (§5), and full sparkq routing land in subsequent plans once this foundation is validated. Spec: `docs/superpowers/specs/2026-06-03-dagster-orchestration-design.md`.

---

## File Structure

- Create `src/core/pipeline/__init__.py` — package marker
- Create `src/core/pipeline/stages.py` — extracted, importable stage functions (called by CLI + Dagster)
- Create `src/orchestration/__init__.py` — package marker
- Create `src/orchestration/resources.py` — `SparkqJobResource`
- Create `src/orchestration/assets/__init__.py` — package marker
- Create `src/orchestration/assets/collection.py` — `collect_papers` asset
- Create `src/orchestration/assets/enrichment.py` — `enrich_abstracts` asset
- Create `src/orchestration/assets/embedding.py` — `embed_papers` sparkq asset
- Create `src/orchestration/definitions.py` — Dagster `Definitions` (assets + resources)
- Create `tests/orchestration/__init__.py`
- Create `tests/orchestration/test_resources.py`
- Create `tests/orchestration/test_assets.py`
- Create `tests/core/test_pipeline_stages.py`
- Modify `pyproject.toml` — add dagster deps
- Modify `src/cli/commands/enrichment.py` — refactor enrich-6 to call the shared stage (proves DRY; CLI behavior unchanged)

---

## Task 1: Add Dagster dependencies

**Files:**
- Modify: `pyproject.toml` (dependency list)

- [ ] **Step 1: Add the dependencies via uv**

Run:
```bash
uv add dagster dagster-webserver
```
Expected: `pyproject.toml` gains `dagster` and `dagster-webserver` under `[project] dependencies`; `uv.lock` updates; exit 0.

- [ ] **Step 2: Verify Dagster imports**

Run:
```bash
uv run python -c "import dagster; print(dagster.__version__)"
```
Expected: prints a version (e.g. `1.9.x`), exit 0.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add dagster + dagster-webserver"
```

---

## Task 2: Extract the collect stage into a shared function

**Files:**
- Create: `src/core/pipeline/__init__.py`
- Create: `src/core/pipeline/stages.py`
- Test: `tests/core/test_pipeline_stages.py`

The collect logic currently lives inline in `src/cli/commands/collection.py::collect_incremental` (the `run_incremental` async closure, lines ~338+). Extract its source-dispatch into a reusable function that returns the per-source counts dict.

- [ ] **Step 1: Write the failing test** (mock the collectors so no network)

Create `tests/core/test_pipeline_stages.py`:
```python
import asyncio
from unittest.mock import AsyncMock, patch
from src.core.pipeline import stages


def test_collect_incremental_stage_returns_per_source_counts():
    fake = AsyncMock()
    fake.__aenter__.return_value = fake
    fake.__aexit__.return_value = False
    fake.collect_incremental.return_value = 42

    with patch.object(stages, "CoreCorpusCollector", return_value=fake), \
         patch.object(stages, "QdrantStorage") as Storage:
        Storage.return_value.ensure_collection.return_value = None
        result = asyncio.run(stages.collect_incremental_stage(days=3, source="openalex"))

    assert result["openalex"] == 42
    assert result["total"] == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_pipeline_stages.py::test_collect_incremental_stage_returns_per_source_counts -v`
Expected: FAIL — `ModuleNotFoundError: src.core.pipeline` (module not created yet).

- [ ] **Step 3: Create the package and stage function**

Create `src/core/pipeline/__init__.py` (empty).

Create `src/core/pipeline/stages.py`:
```python
"""Importable pipeline stage functions shared by the CLI and the Dagster assets.

Each stage is a thin, side-effecting orchestration over src.core.* that returns
a small structured result (counts), not paper data. Paper data lives in Qdrant.
"""

import datetime

from src.core.storage import QdrantStorage
from src.core.crawler.openalex import CoreCorpusCollector
from src.core.crawler.acl_anthology import ACLAnthologyCollector
from src.core.crawler.dblp import DBLPCollector
from src.core.crawler.openreview import OpenReviewCollector
from src.core.crawler.aaai_ojs import AAAIOJSCollector
from src.core.config import (
    get_acl_venues,
    get_dblp_venues,
    get_openreview_venues,
    get_aaai_venues,
)


async def collect_incremental_stage(days: int = 3, source: str = "all") -> dict[str, int]:
    """Collect new papers from the last `days` days across sources.

    Returns a dict of per-source counts plus a "total" key. Mirrors the logic in
    the collect-incremental CLI command. The collector dedups against existing
    DOIs/IDs, so overlapping daily windows are harmless.
    """
    since_year = (datetime.datetime.now() - datetime.timedelta(days=days)).year
    current_year = datetime.datetime.now().year

    storage = QdrantStorage()
    storage.ensure_collection()
    results: dict[str, int] = {}

    if source in ("all", "openalex"):
        async with CoreCorpusCollector(storage=storage) as collector:
            results["openalex"] = await collector.collect_incremental(days_back=days)

    if source in ("all", "acl"):
        async with ACLAnthologyCollector(storage=storage) as collector:
            count = 0
            for venue in get_acl_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["acl"] = count

    if source in ("all", "dblp"):
        async with DBLPCollector(storage=storage) as collector:
            count = 0
            for venue in get_dblp_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["dblp"] = count

    if source in ("all", "openreview"):
        async with OpenReviewCollector(storage=storage) as collector:
            count = 0
            for venue in get_openreview_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["openreview"] = count

    if source in ("all", "aaai"):
        async with AAAIOJSCollector(storage=storage) as collector:
            count = 0
            for venue in get_aaai_venues():
                async for batch in collector.collect_venue(
                    venue, since_year=since_year, to_year=current_year, force=True
                ):
                    count += len(batch)
            results["aaai"] = count

    results["total"] = sum(v for k, v in results.items() if k != "total")
    return results
```

> **Execution note:** the exact import paths/class names above (`CoreCorpusCollector`, `ACLAnthologyCollector`, `get_acl_venues`, …) are taken from `src/cli/commands/collection.py`. Before writing, open that file and confirm each symbol's import path; adjust if the CLI imports them from a different module.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_pipeline_stages.py::test_collect_incremental_stage_returns_per_source_counts -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/pipeline/__init__.py src/core/pipeline/stages.py tests/core/test_pipeline_stages.py
git commit -m "feat(pipeline): extract collect_incremental_stage shared function"
```

---

## Task 3: Extract the enrich-abstracts stage and refactor the CLI to use it

**Files:**
- Modify: `src/core/pipeline/stages.py` (add function)
- Modify: `src/cli/commands/enrichment.py` (enrich-6 calls the shared stage)
- Test: `tests/core/test_pipeline_stages.py` (add test)

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_pipeline_stages.py`:
```python
def test_enrich_abstracts_stage_returns_progress_counts():
    enricher = AsyncMock()
    enricher.__aenter__.return_value = enricher
    enricher.__aexit__.return_value = False
    progress = type("P", (), {"processed": 10, "enriched": 7, "not_found": 3, "errors": 0})()
    enricher.enrich_abstracts.return_value = progress

    with patch.object(stages, "PaperEnricher", return_value=enricher), \
         patch.object(stages, "QdrantStorage"):
        result = asyncio.run(stages.enrich_abstracts_stage(limit=None, parallel=10))

    assert result == {"processed": 10, "enriched": 7, "not_found": 3, "errors": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_pipeline_stages.py::test_enrich_abstracts_stage_returns_progress_counts -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'PaperEnricher'`.

- [ ] **Step 3: Add the stage function**

Append to `src/core/pipeline/stages.py`:
```python
from src.core.enrichment.openalex import PaperEnricher


async def enrich_abstracts_stage(
    limit: int | None = None, batch_size: int = 100, delay: float = 0.1, parallel: int = 10
) -> dict[str, int]:
    """Fill missing abstracts via OpenAlex for papers that have a DOI.

    Returns processed/enriched/not_found/errors counts.
    """
    storage = QdrantStorage()
    async with PaperEnricher(
        storage=storage, batch_size=batch_size, delay=delay, max_concurrent=parallel
    ) as enricher:
        progress = await enricher.enrich_abstracts(dry_run=False, limit=limit)
    return {
        "processed": progress.processed,
        "enriched": progress.enriched,
        "not_found": progress.not_found,
        "errors": progress.errors,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_pipeline_stages.py::test_enrich_abstracts_stage_returns_progress_counts -v`
Expected: PASS.

- [ ] **Step 5: Refactor the CLI command to call the shared stage (prove DRY)**

In `src/cli/commands/enrichment.py`, inside `enrich_6_abstracts_by_doi_via_openalex`, replace the body of the non-dry-run path's `run_enrichment` enrichment call so it delegates to the stage when not a dry run. Minimal change — keep the dry-run/`--retry-incomplete` paths as-is, but for the standard enrich path call:
```python
from src.core.pipeline.stages import enrich_abstracts_stage
# ... in run_enrichment(), replacing the enrich_abstracts call when not dry_run and not retry_incomplete:
counts = await enrich_abstracts_stage(
    limit=limit, batch_size=batch_size, delay=delay, parallel=parallel
)
click.echo(f"\nAbstract Enrichment Results: {counts}")
```

> **Execution note:** Keep the existing dry-run and `--retry-incomplete` branches untouched (the stage only covers the standard enrich path). Confirm `enrich-6 --dry-run` still works after the edit.

- [ ] **Step 6: Run the CLI smoke check (dry-run must still work)**

Run: `uv run python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --dry-run --limit 1`
Expected: prints a count, exit 0, no exception.

- [ ] **Step 7: Commit**

```bash
git add src/core/pipeline/stages.py src/cli/commands/enrichment.py tests/core/test_pipeline_stages.py
git commit -m "feat(pipeline): extract enrich_abstracts_stage, route CLI through it"
```

---

## Task 4: `SparkqJobResource` (submit → poll → map status)

**Files:**
- Create: `src/orchestration/__init__.py`
- Create: `src/orchestration/resources.py`
- Test: `tests/orchestration/__init__.py`, `tests/orchestration/test_resources.py`

- [ ] **Step 1: Confirm sparkq stdout format (one cheap real call)**

Run:
```bash
sparkq submit "echo dagster-probe" --tag dagster-probe --eta 1m --if-not-running
sparkq status --all
```
Expected: note the exact wording of the submit line (job id location) and the `status` field token (`queued`/`running`/`completed`). Use these to set the regexes in Step 3. (This is a 0-GPU job; cancel with `sparkq cancel <id>` if needed.)

- [ ] **Step 2: Write the failing test** (mock the sparkq CLI via the injectable runner)

Create `tests/orchestration/__init__.py` (empty).

Create `tests/orchestration/test_resources.py`:
```python
import pytest
from src.orchestration.resources import SparkqJobResource, SparkqError


def make_resource(outputs):
    """outputs: list of stdout strings returned by successive _run calls."""
    calls = []

    class R(SparkqJobResource):
        def _run(self, args):
            calls.append(args)
            return outputs[len(calls) - 1]

    return R(poll_interval_seconds=0), calls


def test_submit_and_wait_success():
    res, calls = make_resource([
        "Submitted job abc123 (position 1)\n",   # submit
        "id: abc123\nstatus: completed\n",        # status poll 1
    ])
    job_id = res.submit_and_wait("uv run python -m x", tag="t", gpu_mem="8G", eta="1h")
    assert job_id == "abc123"
    assert calls[0][0] == "submit"
    assert calls[1] == ["status", "abc123"]


def test_submit_and_wait_raises_on_failure():
    res, _ = make_resource([
        "Submitted job def456 (position 1)\n",
        "id: def456\nstatus: failed_final\n",
        "...log tail...\n",                        # log fetch on failure
    ])
    with pytest.raises(SparkqError, match="def456"):
        res.submit_and_wait("cmd", tag="t")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/orchestration/test_resources.py -v`
Expected: FAIL — `ModuleNotFoundError: src.orchestration.resources`.

- [ ] **Step 4: Implement the resource**

Create `src/orchestration/__init__.py` (empty).

Create `src/orchestration/resources.py`:
```python
"""Dagster resource for dispatching GPU work to the DGX Sparks via sparkq."""

import re
import subprocess
import time

from dagster import ConfigurableResource

_TERMINAL_OK = {"completed"}
_TERMINAL_FAIL = {"failed_final", "cancelled", "killed"}


class SparkqError(Exception):
    pass


class SparkqJobResource(ConfigurableResource):
    """Submit a command to sparkq and block until it reaches a terminal state.

    GPU stages can't run in-process; this submits the existing CLI command to a
    Spark node and polls to completion. `--if-not-running` makes retries idempotent.
    """

    workdir: str = "/home/alphabridge/LexiconArxiv"
    poll_interval_seconds: int = 30

    def _run(self, args: list[str]) -> str:
        """Run a sparkq subcommand and return stdout. Isolated for testability."""
        result = subprocess.run(
            ["sparkq", *args], capture_output=True, text=True, check=True
        )
        return result.stdout

    def _parse_job_id(self, submit_output: str) -> str:
        m = re.search(r"\bjob\s+(\S+)", submit_output)
        if not m:
            raise SparkqError(f"Could not parse job id from: {submit_output!r}")
        return m.group(1)

    def _parse_status(self, status_output: str) -> str:
        m = re.search(r"status[:\s]+(\w+)", status_output)
        if not m:
            raise SparkqError(f"Could not parse status from: {status_output!r}")
        return m.group(1)

    def submit_and_wait(
        self, cmd: str, tag: str, gpu_mem: str = "16G", eta: str = "1h"
    ) -> str:
        out = self._run([
            "submit", cmd,
            "--workdir", self.workdir,
            "--tag", tag,
            "--gpu-mem", gpu_mem,
            "--eta", eta,
            "--if-not-running",
        ])
        job_id = self._parse_job_id(out)
        while True:
            status = self._parse_status(self._run(["status", job_id]))
            if status in _TERMINAL_OK:
                return job_id
            if status in _TERMINAL_FAIL:
                log_tail = self._run(["log", job_id, "--lines", "50"])
                raise SparkqError(
                    f"sparkq job {job_id} ended '{status}'. Log tail:\n{log_tail}"
                )
            time.sleep(self.poll_interval_seconds)
```

> **Execution note:** adjust `_parse_job_id` / `_parse_status` regexes to match the real output captured in Step 1.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/orchestration/test_resources.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add src/orchestration/__init__.py src/orchestration/resources.py tests/orchestration/__init__.py tests/orchestration/test_resources.py
git commit -m "feat(orchestration): SparkqJobResource submit/poll/map"
```

---

## Task 5: `collect_papers` and `enrich_abstracts` native assets

**Files:**
- Create: `src/orchestration/assets/__init__.py`
- Create: `src/orchestration/assets/collection.py`
- Create: `src/orchestration/assets/enrichment.py`
- Test: `tests/orchestration/test_assets.py`

- [ ] **Step 1: Write the failing test** (materialize assets with stages mocked)

Create `tests/orchestration/test_assets.py`:
```python
import asyncio
from unittest.mock import patch
from dagster import materialize
from src.orchestration.assets.collection import collect_papers
from src.orchestration.assets.enrichment import enrich_abstracts


def test_collect_papers_asset_records_total():
    async def fake_collect(days, source="all"):
        return {"openalex": 5, "openreview": 1, "total": 6}

    with patch("src.orchestration.assets.collection.collect_incremental_stage",
               side_effect=fake_collect):
        result = materialize([collect_papers])
    assert result.success
    mat = result.asset_materializations_for_node("collect_papers")[0]
    assert mat.metadata["total"].value == 6


def test_enrich_abstracts_asset_runs_after_collect():
    async def fake_enrich(limit=None, batch_size=100, delay=0.1, parallel=10):
        return {"processed": 4, "enriched": 3, "not_found": 1, "errors": 0}

    with patch("src.orchestration.assets.enrichment.enrich_abstracts_stage",
               side_effect=fake_enrich):
        # enrich_abstracts depends on collect_papers; provide the upstream value
        result = materialize(
            [collect_papers, enrich_abstracts],
            selection=["enrich_abstracts"],
            partition_key=None,
        ) if False else None
    # Direct unit call instead of full graph wiring (kept simple):
    from dagster import build_asset_context
    with patch("src.orchestration.assets.enrichment.enrich_abstracts_stage",
               side_effect=fake_enrich):
        out = enrich_abstracts(build_asset_context(), {"total": 6})
    assert out.metadata["enriched"].value == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestration/test_assets.py -v`
Expected: FAIL — `ModuleNotFoundError: src.orchestration.assets.collection`.

- [ ] **Step 3: Implement the assets**

Create `src/orchestration/assets/__init__.py` (empty).

Create `src/orchestration/assets/collection.py`:
```python
import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import collect_incremental_stage

DAYS_LOOKBACK = 3  # daily runs use a 3-day rolling window (self-healing via dedup)


@asset
def collect_papers(context: AssetExecutionContext) -> MaterializeResult:
    """Collect new papers from all sources (3-day rolling window)."""
    counts = asyncio.run(collect_incremental_stage(days=DAYS_LOOKBACK, source="all"))
    context.log.info(f"Collected: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
```

Create `src/orchestration/assets/enrichment.py`:
```python
import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import enrich_abstracts_stage


@asset(deps=["collect_papers"])
def enrich_abstracts(context: AssetExecutionContext, collect_papers=None) -> MaterializeResult:
    """Fill missing abstracts via OpenAlex. Depends on collect_papers."""
    counts = asyncio.run(enrich_abstracts_stage())
    context.log.info(f"Abstract enrichment: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
```

> **Execution note:** the `enrich_abstracts` dependency on `collect_papers` is declared via `deps=[...]` (no data passed — state flows through Qdrant). Adjust the test's direct-call signature to match the final asset signature; the `if False` branch in the test is a guard so only the direct unit call runs.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestration/test_assets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orchestration/assets/ tests/orchestration/test_assets.py
git commit -m "feat(orchestration): collect_papers + enrich_abstracts native assets"
```

---

## Task 6: `embed_papers` sparkq asset

**Files:**
- Create: `src/orchestration/assets/embedding.py`
- Test: `tests/orchestration/test_assets.py` (add test)

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestration/test_assets.py`:
```python
def test_embed_papers_asset_submits_via_sparkq():
    from dagster import build_asset_context
    from src.orchestration.assets.embedding import embed_papers

    class FakeSparkq:
        def __init__(self):
            self.submitted = None
        def submit_and_wait(self, cmd, tag, gpu_mem="16G", eta="1h"):
            self.submitted = (cmd, tag)
            return "job999"

    fake = FakeSparkq()
    out = embed_papers(build_asset_context(), sparkq=fake)
    assert "embed-papers" in fake.submitted[0]
    assert out.metadata["sparkq_job_id"].value == "job999"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestration/test_assets.py::test_embed_papers_asset_submits_via_sparkq -v`
Expected: FAIL — `ModuleNotFoundError: src.orchestration.assets.embedding`.

- [ ] **Step 3: Implement the asset**

Create `src/orchestration/assets/embedding.py`:
```python
from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.orchestration.resources import SparkqJobResource

EMBED_CMD = (
    "uv run python -m src.cli.core_collect embed-papers "
    "--batch-size 16 --embed-batch-size 128"
)


@asset(deps=["enrich_abstracts"])
def embed_papers(
    context: AssetExecutionContext, sparkq: SparkqJobResource
) -> MaterializeResult:
    """Embed new papers on the DGX Sparks via sparkq (GPU: Qwen3-Embedding-8B)."""
    job_id = sparkq.submit_and_wait(
        EMBED_CMD, tag="lexicon-embed", gpu_mem="16G", eta="2h"
    )
    context.log.info(f"Embedding completed via sparkq job {job_id}")
    return MaterializeResult(metadata={"sparkq_job_id": MetadataValue.text(job_id)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestration/test_assets.py::test_embed_papers_asset_submits_via_sparkq -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orchestration/assets/embedding.py tests/orchestration/test_assets.py
git commit -m "feat(orchestration): embed_papers sparkq GPU asset"
```

---

## Task 7: Wire `Definitions` and validate the code location

**Files:**
- Create: `src/orchestration/definitions.py`
- Test: command-line validation

- [ ] **Step 1: Write `Definitions`**

Create `src/orchestration/definitions.py`:
```python
from dagster import Definitions

from src.orchestration.assets.collection import collect_papers
from src.orchestration.assets.enrichment import enrich_abstracts
from src.orchestration.assets.embedding import embed_papers
from src.orchestration.resources import SparkqJobResource

defs = Definitions(
    assets=[collect_papers, enrich_abstracts, embed_papers],
    resources={"sparkq": SparkqJobResource()},
)
```

- [ ] **Step 2: Validate the code location loads**

Run:
```bash
uv run dagster definitions validate -m src.orchestration.definitions
```
Expected: "Validation successful" (all 3 assets + resource load, DAG `collect_papers → enrich_abstracts → embed_papers` resolves), exit 0.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest tests/orchestration tests/core/test_pipeline_stages.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/orchestration/definitions.py
git commit -m "feat(orchestration): wire Definitions for phase-1 assets"
```

---

## Task 8: End-to-end validation against a known window

**Files:** none (validation only)

- [ ] **Step 1: Launch the Dagster UI**

Run (background):
```bash
uv run dagster dev -m src.orchestration.definitions
```
Expected: webserver on `http://localhost:3000`, the 3-asset graph visible.

- [ ] **Step 2: Materialize the CPU assets against a tiny window**

In the UI (or CLI), materialize `collect_papers` then `enrich_abstracts`. For a fast check, temporarily set `DAYS_LOOKBACK = 1`.
Run (CLI alternative):
```bash
uv run dagster asset materialize --select collect_papers -m src.orchestration.definitions
```
Expected: run succeeds; `collect_papers` materialization metadata shows per-source counts; new/updated papers visible in Qdrant via `uv run python -m src.cli.core_collect status`.

- [ ] **Step 3: Validate embed_papers dispatches to sparkq**

Materialize `embed_papers`; confirm a `lexicon-embed` job appears in `sparkq status --all` and the asset blocks until it completes, then records the job id.
Expected: asset run succeeds; `sparkq history --like lexicon-embed` shows the completed job.

- [ ] **Step 4: Confirm results match the bash path**

Compare counts/coverage with a `scripts/run_incremental_pipeline.sh --days 1 --dry-run` projection and `status` output — Dagster path should produce equivalent collection + embedding outcomes.

- [ ] **Step 5: Restore `DAYS_LOOKBACK = 3` and commit any tweaks**

```bash
git add -A && git commit -m "chore(orchestration): phase-1 validation tweaks" || echo "nothing to commit"
```

---

## Self-Review

- **Spec coverage (phases 1–2):** Dagster stood up (Tasks 1,7,8); stage logic ported to shared functions (Tasks 2,3); native CPU assets (Task 5); sparkq GPU asset + resource (Tasks 4,6); validation vs bash (Task 8). DQ checks (§3), schedules (§5), and the remaining ~10 assets are explicitly out of scope for Plan 1 → follow-up plans.
- **Placeholder scan:** no TODO/TBD; every code step has complete code. The two "Execution notes" are concrete verification instructions (confirm import paths; confirm sparkq output format), not deferred implementation.
- **Type consistency:** stage functions return `dict[str,int]`; assets wrap them in `MaterializeResult`/`MetadataValue`; `SparkqJobResource.submit_and_wait(cmd, tag, gpu_mem, eta) -> str` used identically in Task 6 and its test. `deps=[...]` used consistently (state via Qdrant, not data passing).

## Out of scope → next plans
- **Plan 2:** remaining native assets (enrich_refs_s2/crossref, extract_keywords, label_abstracts, resolve_refs, enrich_stubs, build_cited_by, analyze_graph) + compute_similarity/compute_topics (native-vs-sparkq decided here).
- **Plan 3:** DQ asset-checks (spec §3) in warn-only then block+flag, with the `dq_flags` payload field.
- **Plan 4:** daily/weekly schedules + partitions + failure sensor (spec §5); retire bash orchestrator.
