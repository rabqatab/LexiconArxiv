# Dagster Orchestration — Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up Dagster alongside the existing pipeline and prove the native-asset patterns end-to-end with three exemplar assets — a simple native asset (`collect_papers`), a native asset chained through Qdrant (`enrich_abstracts`), and a service-delegated GPU native asset (`embed_papers`, which calls the local Ollama embedding service).

**Architecture:** Stage logic is extracted from the CLI commands into shared `src/core/pipeline/stages.py` functions; both the CLI and the Dagster assets call them (DRY). All three Plan-1 assets run **in-process**. `embed_papers` is GPU work, but the GPU is held by the local **Ollama** service (`qwen3-embedding:8b` on the GB10) and the asset only makes HTTP calls to `/api/embed` — so it stays a lightweight native asset, no GPU-job dispatch needed in Plan 1. Qdrant remains the shared data store; assets return lightweight counts, not data. Dagster keeps its own SQLite metadata store (orthogonal to Qdrant).

**Tech Stack:** Python 3.12, uv, Dagster (`dagster`, `dagster-webserver`), Qdrant, Ollama (`qwen3-embedding:8b`), pytest. (No `sparkq` in Plan 1 — see Revision note.)

**Scope note:** This is Plan 1 of the migration (spec §6 phases 1–2). It ports 3 exemplar assets that exercise the native patterns. The remaining ~10 assets, DQ asset-checks (§3), schedules (§5), and GPU-job dispatch via `sparkq` land in subsequent plans once this foundation is validated. Spec: `docs/superpowers/specs/2026-06-03-dagster-orchestration-design.md`.

---

## Revision (2026-06-16) — verified against the current environment

This plan was verified against the live codebase and DGX environment on 2026-06-16. Two changes vs. the original 2026-06-03 draft:

1. **Collector import paths corrected (Task 2).** The collectors and venue getters are re-exported from the **`src.core.crawler`** package (matching `src/cli/commands/collection.py`), **not** `src.core.config`. The AAAI collector class is **`AAOJSCollector`**, not `AAAIOJSCollector`. The original plan's flagged "execution note" guess was wrong; this revision bakes in the verified paths.

2. **`embed_papers` is a native asset, not a sparkq asset.** Verification showed `embed-papers` computes embeddings via **local Ollama `/api/embed` HTTP calls** (`src/core/embedding/embedder.py`), and the GB10 GPU + Ollama run on Node 1 (`localhost`). The original premise "GPU work can't run in-process → dispatch via sparkq" does not hold for this service-delegated embedding architecture; routing it through sparkq would also double-count GPU memory (Ollama is an untracked GPU tenant from sparkq's view). Per the user's decision, `embed_papers` is implemented as a **native asset calling `embed_papers_stage()`**. The `SparkqJobResource` and the sparkq asset are **removed from Plan 1** and deferred (see "Out of scope") to the first plan that introduces a genuinely CUDA-bound, single-shot stage. When that resource is eventually built, it must be **JSON-first** (`sparkq submit --json`, `sparkq wait <id> --json`, decide on the `success`/`terminal` booleans) per the sparkq skill — never regex human output or hand-roll a poll loop.

Stable & confirmed (no change): Python 3.12.3 / uv 0.9.27; Dagster not yet installed; `CoreCorpusCollector.collect_incremental(days_back=)`; `PaperEnricher(storage, batch_size, delay, max_concurrent).enrich_abstracts(dry_run, limit) -> EnrichmentProgress(processed/enriched/not_found/errors)`; CLI commands `enrich-6-abstracts-by-doi-via-openalex` and `embed-papers --batch-size/--embed-batch-size`.

---

## File Structure

- Create `src/core/pipeline/__init__.py` — package marker
- Create `src/core/pipeline/stages.py` — extracted, importable stage functions (called by CLI + Dagster): `collect_incremental_stage`, `enrich_abstracts_stage`, `embed_papers_stage`
- Create `src/orchestration/__init__.py` — package marker
- Create `src/orchestration/assets/__init__.py` — package marker
- Create `src/orchestration/assets/collection.py` — `collect_papers` asset
- Create `src/orchestration/assets/enrichment.py` — `enrich_abstracts` asset
- Create `src/orchestration/assets/embedding.py` — `embed_papers` native asset
- Create `src/orchestration/definitions.py` — Dagster `Definitions` (assets only)
- Create `tests/orchestration/__init__.py`
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

The collect logic currently lives inline in `src/cli/commands/collection.py::collect_incremental` (the `run_incremental` async closure, lines ~338+). Extract its source-dispatch into a reusable function that returns the per-source counts dict. **The import paths below are verified against `src/cli/commands/collection.py` (2026-06-16): collectors and venue getters come from `src.core.crawler`, and the AAAI class is `AAOJSCollector`.**

- [ ] **Step 1: Write the failing test** (mock the collectors so no network)

Create `tests/core/test_pipeline_stages.py`:
```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
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
from src.core.crawler import (
    CoreCorpusCollector,
    ACLAnthologyCollector,
    get_acl_venues,
    DBLPCollector,
    get_dblp_venues,
    OpenReviewCollector,
    get_openreview_venues,
    AAOJSCollector,
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
        async with AAOJSCollector(storage=storage) as collector:
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

In `src/cli/commands/enrichment.py`, inside `enrich_6_abstracts_by_doi_via_openalex`, replace the body of the non-dry-run path's enrichment call so it delegates to the stage when not a dry run. Minimal change — keep the dry-run/`--retry-incomplete` paths as-is, but for the standard enrich path call:
```python
from src.core.pipeline.stages import enrich_abstracts_stage
# ... in the enrich runner, replacing the enrich_abstracts call when not dry_run and not retry_incomplete:
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

## Task 4: Extract the embed-papers stage (native, local Ollama)

**Files:**
- Modify: `src/core/pipeline/stages.py` (add function)
- Test: `tests/core/test_pipeline_stages.py` (add test)

The embed logic currently lives inline in `src/cli/commands/embedding.py::embed_papers`. It loops `storage.get_papers_for_embedding(...)` → `embedder.embed_and_upsert_batch(...)` where `embedder` is `PaperEmbedder` (HTTP calls to local Ollama). Extract the loop into a stage that returns the embedded count.

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_pipeline_stages.py`:
```python
def test_embed_papers_stage_returns_embedded_count():
    embedder = AsyncMock()
    embedder.__aenter__.return_value = embedder
    embedder.__aexit__.return_value = False
    embedder.check_model_available.return_value = True
    embedder.embed_and_upsert_batch.return_value = 2

    storage = MagicMock()
    # one batch of two papers, then no more (next_offset=None)
    storage.get_papers_for_embedding.return_value = ([{"id": "a"}, {"id": "b"}], None)

    with patch.object(stages, "PaperEmbedder", return_value=embedder), \
         patch.object(stages, "QdrantStorage", return_value=storage):
        result = asyncio.run(stages.embed_papers_stage(batch_size=2))

    assert result == {"embedded": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_pipeline_stages.py::test_embed_papers_stage_returns_embedded_count -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'PaperEmbedder'`.

- [ ] **Step 3: Add the stage function**

Append to `src/core/pipeline/stages.py`:
```python
from src.core.embedding.embedder import PaperEmbedder


async def embed_papers_stage(
    batch_size: int = 8,
    embed_batch_size: int = 64,
    concurrency: int = 4,
    limit: int | None = None,
    resume: bool = True,
) -> dict[str, int]:
    """Embed new papers (section + structured-abstract + BM25 vectors) via Ollama.

    The GPU work is delegated to the local Ollama service (qwen3-embedding:8b);
    this function only makes HTTP calls, so it runs in-process. `resume=True`
    skips papers that already have dense vectors. Returns {"embedded": N}.
    """
    storage = QdrantStorage()
    embedder = PaperEmbedder(max_concurrent=concurrency)
    total_embedded = 0
    async with embedder:
        if not await embedder.check_model_available():
            raise RuntimeError(
                "Embedding model not available in Ollama "
                "(run: ollama pull qwen3-embedding:8b)"
            )
        offset = None
        while True:
            papers, next_offset = storage.get_papers_for_embedding(
                limit=batch_size, offset=offset, skip_embedded=resume
            )
            if not papers:
                break
            total_embedded += await embedder.embed_and_upsert_batch(
                papers=papers, storage=storage, embed_batch_size=embed_batch_size
            )
            if limit and total_embedded >= limit:
                break
            if next_offset is None:
                break
            offset = next_offset
    return {"embedded": total_embedded}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_pipeline_stages.py::test_embed_papers_stage_returns_embedded_count -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/pipeline/stages.py tests/core/test_pipeline_stages.py
git commit -m "feat(pipeline): extract embed_papers_stage shared function"
```

---

## Task 5: `collect_papers` and `enrich_abstracts` native assets

**Files:**
- Create: `src/orchestration/__init__.py`
- Create: `src/orchestration/assets/__init__.py`
- Create: `src/orchestration/assets/collection.py`
- Create: `src/orchestration/assets/enrichment.py`
- Test: `tests/orchestration/__init__.py`, `tests/orchestration/test_assets.py`

- [ ] **Step 1: Write the failing test** (materialize/unit-call assets with stages mocked)

Create `tests/orchestration/__init__.py` (empty).

Create `tests/orchestration/test_assets.py`:
```python
from unittest.mock import patch
from dagster import materialize, build_asset_context
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


def test_enrich_abstracts_asset_records_enriched():
    async def fake_enrich(limit=None, batch_size=100, delay=0.1, parallel=10):
        return {"processed": 4, "enriched": 3, "not_found": 1, "errors": 0}

    with patch("src.orchestration.assets.enrichment.enrich_abstracts_stage",
               side_effect=fake_enrich):
        out = enrich_abstracts(build_asset_context())
    assert out.metadata["enriched"].value == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestration/test_assets.py -v`
Expected: FAIL — `ModuleNotFoundError: src.orchestration.assets.collection`.

- [ ] **Step 3: Implement the assets**

Create `src/orchestration/__init__.py` (empty).
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
def enrich_abstracts(context: AssetExecutionContext) -> MaterializeResult:
    """Fill missing abstracts via OpenAlex. Depends on collect_papers (state via Qdrant)."""
    counts = asyncio.run(enrich_abstracts_stage())
    context.log.info(f"Abstract enrichment: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
```

> **Execution note:** the `enrich_abstracts` dependency on `collect_papers` is declared via `deps=[...]` — no data is passed between assets; state flows through Qdrant. The asset signature takes only `context`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestration/test_assets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orchestration/__init__.py src/orchestration/assets/ tests/orchestration/__init__.py tests/orchestration/test_assets.py
git commit -m "feat(orchestration): collect_papers + enrich_abstracts native assets"
```

---

## Task 6: `embed_papers` native asset

**Files:**
- Create: `src/orchestration/assets/embedding.py`
- Test: `tests/orchestration/test_assets.py` (add test)

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestration/test_assets.py`:
```python
def test_embed_papers_asset_records_embedded():
    from src.orchestration.assets.embedding import embed_papers

    async def fake_embed(**kwargs):
        return {"embedded": 5}

    with patch("src.orchestration.assets.embedding.embed_papers_stage",
               side_effect=fake_embed):
        out = embed_papers(build_asset_context())
    assert out.metadata["embedded"].value == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestration/test_assets.py::test_embed_papers_asset_records_embedded -v`
Expected: FAIL — `ModuleNotFoundError: src.orchestration.assets.embedding`.

- [ ] **Step 3: Implement the asset**

Create `src/orchestration/assets/embedding.py`:
```python
import asyncio

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from src.core.pipeline.stages import embed_papers_stage


@asset(deps=["enrich_abstracts"])
def embed_papers(context: AssetExecutionContext) -> MaterializeResult:
    """Embed new papers via the local Ollama service (GPU: qwen3-embedding:8b).

    Service-delegated GPU work: the asset only issues HTTP calls to Ollama, so it
    runs in-process. Depends on enrich_abstracts (state via Qdrant).
    """
    counts = asyncio.run(embed_papers_stage())
    context.log.info(f"Embedding: {counts}")
    return MaterializeResult(
        metadata={k: MetadataValue.int(v) for k, v in counts.items()}
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestration/test_assets.py::test_embed_papers_asset_records_embedded -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orchestration/assets/embedding.py tests/orchestration/test_assets.py
git commit -m "feat(orchestration): embed_papers native asset (local Ollama)"
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

defs = Definitions(
    assets=[collect_papers, enrich_abstracts, embed_papers],
)
```

- [ ] **Step 2: Validate the code location loads**

Run:
```bash
uv run dagster definitions validate -m src.orchestration.definitions
```
Expected: "Validation successful" (all 3 assets load, DAG `collect_papers → enrich_abstracts → embed_papers` resolves), exit 0.

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

**Precondition:** Qdrant up (`localhost:6333`) and Ollama serving `qwen3-embedding:8b` (warm it once: `curl localhost:11434/api/embed -d '{"model":"qwen3-embedding:8b","input":["x"]}'`). See `MEMORY.md` → `lexiconarxiv-bringup-sequence`.

- [ ] **Step 1: Launch the Dagster UI**

Run (background):
```bash
uv run dagster dev -m src.orchestration.definitions
```
Expected: webserver on `http://localhost:3000`, the 3-asset graph visible.

- [ ] **Step 2: Materialize the assets against a tiny window**

In the UI (or CLI), materialize `collect_papers` → `enrich_abstracts` → `embed_papers`. For a fast check, temporarily set `DAYS_LOOKBACK = 1`.
Run (CLI alternative):
```bash
uv run dagster asset materialize --select collect_papers -m src.orchestration.definitions
```
Expected: run succeeds; `collect_papers` materialization metadata shows per-source counts; new/updated papers visible in Qdrant via `uv run python -m src.cli.core_collect status`.

- [ ] **Step 3: Validate embed_papers runs locally via Ollama**

Materialize `embed_papers`; confirm the asset succeeds and records an `embedded` count, and that the papers gain dense vectors (e.g. a `search_papers` MCP call returns `hybrid`, not `bm25_only`).
Expected: asset run succeeds; embedded count > 0 on a window with new papers (or 0 if all already embedded with `resume=True`).

- [ ] **Step 4: Confirm results match the bash path**

Compare counts/coverage with a `scripts/run_incremental_pipeline.sh --days 1 --dry-run` projection and `status` output — the Dagster path should produce equivalent collection + embedding outcomes.

- [ ] **Step 5: Restore `DAYS_LOOKBACK = 3` and commit any tweaks**

```bash
git add -A && git commit -m "chore(orchestration): phase-1 validation tweaks" || echo "nothing to commit"
```

---

## Self-Review

- **Spec coverage (phases 1–2):** Dagster stood up (Tasks 1,7,8); stage logic ported to shared functions (Tasks 2,3,4); native CPU assets (Task 5); native service-delegated GPU asset (Task 6); validation vs bash (Task 8). GPU-job dispatch via sparkq (spec §2 "sparkq assets"), DQ checks (§3), schedules (§5), and the remaining ~10 assets are explicitly out of scope for Plan 1 → follow-up plans.
- **Placeholder scan:** no TODO/TBD; every code step has complete code verified against the current codebase (2026-06-16). The one "Execution note" (Task 3) is a concrete verification instruction (keep dry-run/`--retry-incomplete` branches), not deferred implementation.
- **Type consistency:** stage functions return `dict[str,int]` (`collect_incremental_stage` → per-source + total; `enrich_abstracts_stage` → processed/enriched/not_found/errors; `embed_papers_stage` → embedded); assets wrap them in `MaterializeResult`/`MetadataValue`; every asset signature is `(context: AssetExecutionContext) -> MaterializeResult` with cross-asset order via `deps=[...]` (state through Qdrant, no data passing). Verified symbols: `src.core.crawler.{CoreCorpusCollector, ACLAnthologyCollector, DBLPCollector, OpenReviewCollector, AAOJSCollector, get_acl_venues, get_dblp_venues, get_openreview_venues, get_aaai_venues}`; `PaperEnricher`; `PaperEmbedder`.

## Out of scope → next plans
- **Plan 2:** remaining native assets (enrich_refs_s2/crossref, extract_keywords, label_abstracts, resolve_refs, enrich_stubs, build_cited_by, analyze_graph) + compute_similarity/compute_topics. **`compute_topics` (UMAP+HDBSCAN) is the first candidate for a genuinely CUDA-bound stage** — if it moves to cuML-GPU, this is where the `SparkqJobResource` (JSON-first: `sparkq submit --json` / `sparkq wait <id> --json`, decide on `success`/`terminal` booleans) gets introduced. Otherwise it stays native.
- **Plan 3:** DQ asset-checks (spec §3) in warn-only then block+flag, with the `dq_flags` payload field.
- **Plan 4:** daily/weekly schedules + partitions + failure sensor (spec §5); retire bash orchestrator.
