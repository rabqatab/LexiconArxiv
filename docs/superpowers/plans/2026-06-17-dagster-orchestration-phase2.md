# Dagster Orchestration — Phase 2 (Remaining Assets) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the remaining ~10 pipeline stages into shared `src/core/pipeline/stages.py` functions + native Dagster assets, completing the full incremental DAG (collect → enrich → resolve → graph → analytics) so the entire pipeline can run under Dagster.

**Architecture:** Same pattern as Phase 1 — each stage becomes a thin async/sync function in `src/core/pipeline/stages.py` that calls existing `src.core.*` code and returns a small counts dict; a native `@asset` wraps each (state flows through Qdrant via `deps=[...]`, no data passing). **All Phase-2 assets are native (in-process)** — verification confirmed `compute_similarity` and `compute_topics` are CPU/Qdrant-bound (no torch/cuML/GPU), so sparkq is not used here either. Qdrant remains the shared store; Dagster keeps its SQLite metadata store.

**Tech Stack:** Python 3.12, uv, Dagster, Qdrant, Ollama (already deps). Tests: `uv run --extra dev pytest`.

**Scope note:** Phase 2 of the migration (builds on Phase 1, merged `8ebd534`). Phase 3 (DQ asset-checks) and Phase 4 (schedules + retire bash) follow. Spec: `docs/superpowers/specs/2026-06-03-dagster-orchestration-design.md`. Phase 1 plan (pattern reference): `docs/superpowers/plans/2026-06-03-dagster-orchestration-phase1.md`.

---

## Conventions (apply to every task)

- **Test command:** `uv run --extra dev pytest <args>` (pytest is in the `dev` extra; plain `uv run pytest` fails).
- **TDD:** write the failing test, run it (confirm the expected failure), implement, run (confirm pass), commit.
- **Stage functions** live in `src/core/pipeline/stages.py` (append; keep all `import` lines at the top so tests can `patch.object(stages, "<Symbol>")`). Each returns a `dict[str, int]`.
- **Tests** mock the core class/function on the `stages` module and assert the returned counts dict — no network.
- **Commits:** `git commit --author="rabqatab <minhan.nick.cho@gmail.com>" -m "..."`. NEVER add a `Co-Authored-By` trailer or "Generated with Claude Code" line. Verify after: `git log -1 --format="%B" | grep -i "co-authored"` returns nothing.
- **Discipline:** implement exactly the stage's logic; no extra params/features (YAGNI). Do NOT refactor the existing CLI commands in Phase 2 (CLI→stage DRY refactors are deferred; Phase 2 only adds the shared stages + assets). The one exception already done in Phase 1 (enrich-6) stays.

---

## File Structure

- Modify `src/core/pipeline/stages.py` — append 10 stage functions
- Create `src/orchestration/assets/references.py` — `enrich_refs_s2`, `enrich_refs_crossref`
- Create `src/orchestration/assets/keywords.py` — `extract_keywords`
- Create `src/orchestration/assets/labeling.py` — `label_abstracts`
- Create `src/orchestration/assets/resolution.py` — `resolve_refs`, `enrich_stubs`
- Create `src/orchestration/assets/graph.py` — `build_cited_by`, `analyze_graph`
- Create `src/orchestration/assets/analytics.py` — `compute_similarity`, `compute_topics`
- Modify `src/orchestration/assets/embedding.py` — change `embed_papers` deps to `["label_abstracts"]`
- Modify `src/orchestration/definitions.py` — register all new assets
- Modify `tests/core/test_pipeline_stages.py` — append stage tests
- Modify `tests/orchestration/test_assets.py` — append asset tests

### Target asset DAG (deps)

```
collect_papers (P1)
  ├─ enrich_abstracts (P1) ─ extract_keywords ─┐
  │                        └ label_abstracts ──┴─ embed_papers (P1, deps→label_abstracts)
  │                                                  ├─ compute_similarity
  │                                                  └─ compute_topics
  ├─ enrich_refs_s2 ─┐
  └─ enrich_refs_crossref ─┴─ resolve_refs ─┬─ enrich_stubs
                                            └─ build_cited_by ─ analyze_graph
```

---

## Task 1: References stages (S2 + CrossRef)

**Files:** Modify `src/core/pipeline/stages.py`; Test: `tests/core/test_pipeline_stages.py`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/core/test_pipeline_stages.py`:
```python
def test_enrich_refs_s2_stage_returns_counts():
    enricher = AsyncMock()
    enricher.__aenter__.return_value = enricher
    enricher.__aexit__.return_value = False
    enricher.enrich_by_doi.return_value = type("P", (), {
        "processed": 8, "enriched": 5, "not_found": 2, "no_refs": 1, "errors": 0})()
    with patch.object(stages, "SemanticScholarEnricher", return_value=enricher), \
         patch.object(stages, "QdrantStorage"):
        result = asyncio.run(stages.enrich_refs_s2_stage(limit=None, parallel=10))
    assert result == {"processed": 8, "enriched": 5, "not_found": 2, "no_refs": 1, "errors": 0}


def test_enrich_refs_crossref_stage_returns_counts():
    enricher = AsyncMock()
    enricher.__aenter__.return_value = enricher
    enricher.__aexit__.return_value = False
    enricher.enrich_by_doi.return_value = type("P", (), {
        "processed": 4, "enriched": 3, "not_found": 1, "no_refs": 0, "errors": 0})()
    with patch.object(stages, "CrossRefEnricher", return_value=enricher):
        result = asyncio.run(stages.enrich_refs_crossref_stage(limit=None, parallel=10))
    assert result == {"processed": 4, "enriched": 3, "not_found": 1, "no_refs": 0, "errors": 0}
```

- [ ] **Step 2: Run, confirm fail** (`AttributeError: ... 'SemanticScholarEnricher'`):
`uv run --extra dev pytest tests/core/test_pipeline_stages.py -k "refs_s2 or refs_crossref" -v`

- [ ] **Step 3: Implement.** Add imports at top of `stages.py`:
```python
from src.core.enrichment.semantic_scholar import SemanticScholarEnricher
from src.core.enrichment.crossref import CrossRefEnricher
```
Append:
```python
async def enrich_refs_s2_stage(
    limit: int | None = None, batch_size: int = 100, delay: float = 0.1,
    parallel: int = 10, recent_days: int | None = None,
) -> dict[str, int]:
    """Fill referenced_works via Semantic Scholar for DOI papers missing refs."""
    fetched_since = None
    if recent_days is not None:
        fetched_since = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=recent_days)
        ).isoformat()
    storage = QdrantStorage()
    async with SemanticScholarEnricher(
        storage=storage, batch_size=batch_size, delay=delay, max_concurrent=parallel
    ) as enricher:
        p = await enricher.enrich_by_doi(dry_run=False, limit=limit, fetched_since=fetched_since)
    return {"processed": p.processed, "enriched": p.enriched,
            "not_found": p.not_found, "no_refs": p.no_refs, "errors": p.errors}


async def enrich_refs_crossref_stage(
    limit: int | None = None, batch_size: int = 100, delay: float = 0.1, parallel: int = 10,
) -> dict[str, int]:
    """Fill referenced_works via CrossRef for DOI papers missing refs."""
    async with CrossRefEnricher(
        batch_size=batch_size, delay=delay, max_concurrent=parallel
    ) as enricher:
        p = await enricher.enrich_by_doi(dry_run=False, limit=limit)
    return {"processed": p.processed, "enriched": p.enriched,
            "not_found": p.not_found, "no_refs": p.no_refs, "errors": p.errors}
```
> Execution note: `CrossRefEnricher.__init__` does NOT take `storage=` (uses its own default `QdrantStorage()`), per `enrichment.py:444`. Confirm both constructors' kwargs (`batch_size`, `delay`, `max_concurrent`) before finalizing.

- [ ] **Step 4: Run, confirm pass.** **Step 5: Commit** (`feat(pipeline): extract enrich_refs_s2/crossref stages`).

---

## Task 2: extract_keywords stage

**Files:** Modify `stages.py`; Test: `tests/core/test_pipeline_stages.py`.

Production uses the **sync** path (no `--llm`). The CLI loop (keywords.py:341–413) scrolls papers, extracts keywords, batch-writes. Extract that loop.

- [ ] **Step 1: Failing test.** Append:
```python
def test_extract_keywords_stage_returns_counts():
    extractor = MagicMock()
    extractor.extract.return_value = ["kw1", "kw2"]
    extractor.get_extraction_source.return_value = "keybert"
    storage = MagicMock()
    storage.get_papers_for_keyword_extraction.return_value = (
        [("id1", {"title": "T", "abstract": "A"})], None)
    with patch.object(stages, "KeywordExtractor", return_value=extractor), \
         patch.object(stages, "QdrantStorage", return_value=storage):
        result = asyncio.run(stages.extract_keywords_stage(batch_size=10))
    assert result["processed"] == 1
    assert result["with_keywords"] == 1
```

- [ ] **Step 2: Run, confirm fail.**
- [ ] **Step 3: Implement.** Add import: `from src.core.keyword import KeywordExtractor`. Append:
```python
async def extract_keywords_stage(
    limit: int | None = None, batch_size: int = 100, force: bool = False,
    use_keybert: bool = True,
) -> dict[str, int]:
    """Extract BM25/display keywords (sync KeyBERT path) for papers missing them."""
    storage = QdrantStorage()
    extractor = KeywordExtractor(use_keybert=use_keybert)
    processed = with_keywords = total_keywords = 0
    offset = None
    while True:
        papers, next_offset = storage.get_papers_for_keyword_extraction(
            limit=batch_size, offset=offset, skip_existing=not force
        )
        if not papers:
            break
        updates = []
        for point_id, payload in papers:
            title = payload.get("title") or ""
            abstract = payload.get("abstract") or ""
            keywords = extractor.extract(title, abstract)
            source = extractor.get_extraction_source(title, abstract)
            processed += 1
            if keywords:
                with_keywords += 1
                total_keywords += len(keywords)
            updates.append((point_id, keywords, source, None))
        storage.batch_update_keywords_with_source(updates)
        if limit and processed >= limit:
            break
        if next_offset is None:
            break
        offset = next_offset
    return {"processed": processed, "with_keywords": with_keywords,
            "total_keywords": total_keywords}
```
> Execution note: confirm `KeywordExtractor.__init__` accepts `use_keybert=` (and whether `embedding_model=` is required/defaulted) at keywords.py:96; if `embedding_model` has no default, pass the same default the CLI uses. Confirm `batch_update_keywords_with_source` accepts a list of `(point_id, keywords, source, structured|None)` tuples.

- [ ] **Step 4: Run, confirm pass. Step 5: Commit** (`feat(pipeline): extract extract_keywords stage`).

---

## Task 3: label_abstracts stage

**Files:** Modify `stages.py`; Test.

Loop (labeling.py:126–208) scrolls papers missing `abstract_structure` (with abstract), calls `AbstractLabeler.label_abstract`, batch-writes. Default backend `gemini` (keys in `GEMINI_API_KEYS`).

- [ ] **Step 1: Failing test.** Append:
```python
def test_label_abstracts_stage_returns_counts():
    labeler = AsyncMock()
    labeler.label_abstract.return_value = ({"task": "x"}, "gemini")
    labeler.close.return_value = None
    storage = MagicMock()
    storage.get_papers_for_abstract_labeling.return_value = (
        [("id1", {"title": "T", "abstract": "A"})], None)
    with patch.object(stages, "AbstractLabeler", return_value=labeler), \
         patch.object(stages, "QdrantStorage", return_value=storage):
        result = asyncio.run(stages.label_abstracts_stage(batch_size=10))
    assert result == {"processed": 1, "labeled": 1}
```

- [ ] **Step 2: Run, confirm fail.**
- [ ] **Step 3: Implement.** Add import: `from src.core.labeling import AbstractLabeler`. Append:
```python
async def label_abstracts_stage(
    limit: int | None = None, batch_size: int = 500, force: bool = False,
    llm_backend: str = "gemini",
) -> dict[str, int]:
    """Label abstract sentences (rhetorical roles -> abstract_structure)."""
    storage = QdrantStorage()
    labeler = AbstractLabeler(llm_backend=llm_backend)
    processed = labeled = 0
    offset = None
    try:
        while True:
            papers, next_offset = storage.get_papers_for_abstract_labeling(
                limit=batch_size, offset=offset, skip_existing=not force
            )
            if not papers:
                break
            results = await asyncio.gather(*[
                labeler.label_abstract(p.get("title") or "", p.get("abstract") or "")
                for _, p in papers
            ])
            updates = []
            for (point_id, _), (structure, source) in zip(papers, results):
                processed += 1
                if structure:
                    labeled += 1
                    updates.append((point_id, structure, source))
            if updates:
                storage.batch_update_abstract_structure(updates)
            if limit and processed >= limit:
                break
            if next_offset is None:
                break
            offset = next_offset
    finally:
        await labeler.close()
    return {"processed": processed, "labeled": labeled}
```
> Execution note: confirm `AbstractLabeler(llm_backend=...)` constructor kwargs (labeler.py:46) and that `label_abstract(title, abstract) -> (dict|None, str)` and `batch_update_abstract_structure(list[(id, dict, str)])` match. Need `import asyncio` (already present in stages.py? add if not).

---

## Task 4: resolve_refs stage

**Files:** Modify `stages.py`; Test. CLI body is a clean delegation to `run_full_pipeline` (LOW risk).

- [ ] **Step 1: Failing test.** Append:
```python
def test_resolve_refs_stage_returns_counts():
    resolver = AsyncMock()
    resolver.__aenter__.return_value = resolver
    resolver.__aexit__.return_value = False
    step = type("RP", (), {"processed": 6, "updated": 4, "stubs_created": 3, "errors": 0})()
    resolver.run_full_pipeline.return_value = {"normalize": step, "arxiv": step, "internal": step}
    with patch.object(stages, "ReferenceResolver", return_value=resolver), \
         patch.object(stages, "QdrantStorage"):
        result = asyncio.run(stages.resolve_refs_stage())
    assert result["stubs_created"] == 9   # summed across 3 steps
    assert result["updated"] == 12
```

- [ ] **Step 2: Run, confirm fail.**
- [ ] **Step 3: Implement.** Add import: `from src.core.resolution.resolver import ReferenceResolver`. Append:
```python
async def resolve_refs_stage(
    limit: int | None = None, batch_size: int = 100, parallel: int = 10,
    create_stubs: bool = True, fuzzy_matching: bool = True, external_search: bool = False,
) -> dict[str, int]:
    """Normalize/resolve references and (optionally) create stub papers."""
    storage = QdrantStorage()
    async with ReferenceResolver(
        storage=storage, batch_size=batch_size, max_concurrent=parallel
    ) as resolver:
        results = await resolver.run_full_pipeline(
            dry_run=False, limit=limit, fuzzy_matching=fuzzy_matching,
            external_search=external_search, create_stubs=create_stubs,
        )
    out = {"processed": 0, "updated": 0, "stubs_created": 0, "errors": 0}
    for step in results.values():
        out["processed"] += getattr(step, "processed", 0)
        out["updated"] += getattr(step, "updated", 0)
        out["stubs_created"] += getattr(step, "stubs_created", 0)
        out["errors"] += getattr(step, "errors", 0)
    return out
```
> Execution note: confirm `ReferenceResolver(storage, batch_size, max_concurrent)` and `run_full_pipeline(dry_run, limit, fuzzy_matching, external_search, create_stubs) -> dict[str, ResolutionProgress]` (resolver.py:890). `ResolutionProgress` has `processed/updated/stubs_created/errors` (use getattr so missing fields default 0).

---

## Task 5: enrich_stubs stage

**Files:** Modify `stages.py`; Test.

- [ ] **Step 1: Failing test.** Append:
```python
def test_enrich_stubs_stage_returns_counts():
    enricher = AsyncMock()
    enricher.__aenter__.return_value = enricher
    enricher.__aexit__.return_value = False
    enricher.enrich_stubs.return_value = type("SP", (), {
        "processed": 5, "enriched": 3, "merged": 1, "not_found": 1, "errors": 0})()
    with patch.object(stages, "StubEnricher", return_value=enricher), \
         patch.object(stages, "QdrantStorage"):
        result = asyncio.run(stages.enrich_stubs_stage(limit=100, parallel=10))
    assert result == {"processed": 5, "enriched": 3, "merged": 1, "not_found": 1, "errors": 0}
```

- [ ] **Step 2: Run, confirm fail.**
- [ ] **Step 3: Implement.** Add import: `from src.core.enrichment import StubEnricher`. Append:
```python
async def enrich_stubs_stage(
    limit: int = 100, parallel: int = 10, identifier_type: str | None = None,
    min_citations: int = 1,
) -> dict[str, int]:
    """Enrich most-cited stub papers with metadata via OpenAlex."""
    storage = QdrantStorage()
    async with StubEnricher(storage=storage, max_concurrent=parallel) as enricher:
        p = await enricher.enrich_stubs(
            limit=limit, identifier_type=identifier_type,
            min_citations=min_citations, dry_run=False,
        )
    return {"processed": p.processed, "enriched": p.enriched, "merged": p.merged,
            "not_found": p.not_found, "errors": p.errors}
```
> Execution note: confirm `StubEnricher(storage, max_concurrent)` and `enrich_stubs(limit, identifier_type, min_citations, dry_run) -> StubEnrichmentProgress(processed/enriched/merged/not_found/errors)` (stub.py:69).

---

## Task 6: build_cited_by stage

**Files:** Modify `stages.py`; Test. Calls `storage.build_cited_by_incremental` directly (no class).

- [ ] **Step 1: Failing test.** Append:
```python
def test_build_cited_by_stage_returns_counts():
    storage = MagicMock()
    storage.build_cited_by_incremental.return_value = {
        "new_papers_processed": 12, "new_edges": 30, "papers_updated": 9}
    with patch.object(stages, "QdrantStorage", return_value=storage):
        result = asyncio.run(stages.build_cited_by_stage())
    assert result == {"new_papers_processed": 12, "new_edges": 30, "papers_updated": 9}
```

- [ ] **Step 2: Run, confirm fail.**
- [ ] **Step 3: Implement.** Append (no new import — uses `QdrantStorage`):
```python
async def build_cited_by_stage() -> dict[str, int]:
    """Incrementally build reverse-citation (cited_by) edges."""
    storage = QdrantStorage()
    result = storage.build_cited_by_incremental()
    return {
        "new_papers_processed": result.get("new_papers_processed", 0),
        "new_edges": result.get("new_edges", 0),
        "papers_updated": result.get("papers_updated", 0),
    }
```
> Execution note: `build_cited_by_incremental(batch_size=100, progress_callback=None) -> dict` (statistics.py:555). It's a sync method; calling it inside an `async def` is fine (no await). Keep the stage `async` for asset uniformity.

---

## Task 7: analyze_graph stage (HIGH extraction risk — verify carefully)

**Files:** Modify `stages.py`; Test. CLI body (graph.py:175–281) interleaves compute + display; extract the compute+store sequence only.

- [ ] **Step 1: Failing test.** Append:
```python
def test_analyze_graph_stage_returns_counts():
    builder = MagicMock()
    builder.build_graph.return_value = MagicMock()  # nx.DiGraph stand-in
    analyzer = MagicMock()
    analyzer.compute_pagerank.return_value = {"a": 0.5}
    analyzer.compute_hits.return_value = ({"a": 0.1}, {"a": 0.2})
    analyzer.compute_communities.return_value = {"a": 0}
    analyzer.store_metrics_to_qdrant.return_value = 1
    with patch.object(stages, "CitationGraphBuilder", return_value=builder), \
         patch.object(stages, "GraphAnalyzer", return_value=analyzer), \
         patch.object(stages, "QdrantStorage"):
        result = asyncio.run(stages.analyze_graph_stage())
    assert result == {"metrics_stored": 1}
```

- [ ] **Step 2: Run, confirm fail.**
- [ ] **Step 3: Implement.** Add import: `from src.core.citation_graph import CitationGraphBuilder, GraphAnalyzer`. Append:
```python
async def analyze_graph_stage(
    pagerank_alpha: float = 0.85, community_resolution: float = 1.0,
) -> dict[str, int]:
    """Build the citation graph and store PageRank/HITS/community metrics to Qdrant."""
    storage = QdrantStorage()
    builder = CitationGraphBuilder(storage=storage)
    graph = builder.build_graph(include_metadata=True)
    analyzer = GraphAnalyzer(graph, storage=storage)
    pagerank = analyzer.compute_pagerank(alpha=pagerank_alpha)
    hubs, authorities = analyzer.compute_hits()
    communities = analyzer.compute_communities(resolution=community_resolution)
    updated = analyzer.store_metrics_to_qdrant(pagerank, hubs, authorities, communities)
    return {"metrics_stored": updated}
```
> Execution note: confirm `CitationGraphBuilder(storage=...).build_graph(include_metadata=True)`, `GraphAnalyzer(graph, storage=...)`, the four compute/store method names + `store_metrics_to_qdrant(pagerank, hubs, authorities, communities) -> int` (analyzer.py:304). This mirrors what the bash pipeline's `analyze-citation-graph --all --store` does.

---

## Task 8: compute_similarity stage (native, CPU/Qdrant-bound)

**Files:** Modify `stages.py`; Test. Module-level function `compute_similarity_batch`.

- [ ] **Step 1: Failing test.** Append:
```python
def test_compute_similarity_stage_returns_counts():
    storage = MagicMock()
    with patch.object(stages, "QdrantStorage", return_value=storage), \
         patch.object(stages, "compute_similarity_batch",
                      return_value={"processed": 100, "updated": 95}) as csb:
        result = asyncio.run(stages.compute_similarity_stage(k=10, batch_size=50))
    assert result == {"processed": 100, "updated": 95}
    assert csb.called
```

- [ ] **Step 2: Run, confirm fail.**
- [ ] **Step 3: Implement.** Add import: `from src.core.analytics.similarity import compute_similarity_batch`. Append:
```python
async def compute_similarity_stage(
    k: int = 10, batch_size: int = 20, limit: int | None = None,
) -> dict[str, int]:
    """Compute the semantic similarity graph (Qdrant ANN; CPU-bound)."""
    storage = QdrantStorage()
    stats = compute_similarity_batch(storage=storage, k=k, batch_size=batch_size, limit=limit)
    return {"processed": stats.get("processed", 0), "updated": stats.get("updated", 0)}
```
> Execution note: `compute_similarity_batch(storage, k, batch_size, limit, edge_types=None) -> dict` (similarity.py:171). Sync call inside async is fine.

---

## Task 9: compute_topics stage (native, CPU UMAP+HDBSCAN)

**Files:** Modify `stages.py`; Test. Module-level `compute_clusters` + `store_cluster_results`.

- [ ] **Step 1: Failing test.** Append:
```python
def test_compute_topics_stage_returns_counts():
    storage = MagicMock()
    with patch.object(stages, "QdrantStorage", return_value=storage), \
         patch.object(stages, "compute_clusters",
                      return_value={"num_papers": 100, "num_clusters": 8, "noise_count": 12}), \
         patch.object(stages, "store_cluster_results", return_value=100):
        result = asyncio.run(stages.compute_topics_stage())
    assert result == {"papers": 100, "clusters": 8, "noise": 12, "stored": 100}


def test_compute_topics_stage_handles_error():
    storage = MagicMock()
    with patch.object(stages, "QdrantStorage", return_value=storage), \
         patch.object(stages, "compute_clusters", return_value={"error": "too few", "count": 3}), \
         patch.object(stages, "store_cluster_results") as scr:
        result = asyncio.run(stages.compute_topics_stage())
    assert result == {"papers": 0, "clusters": 0, "noise": 0, "stored": 0}
    assert not scr.called
```

- [ ] **Step 2: Run, confirm fail.**
- [ ] **Step 3: Implement.** Add import: `from src.core.analytics.clustering import compute_clusters, store_cluster_results`. Append:
```python
async def compute_topics_stage(
    umap_n_components: int = 50, umap_n_neighbors: int = 15,
    hdbscan_min_cluster_size: int = 50, hdbscan_min_samples: int = 10,
) -> dict[str, int]:
    """Cluster papers into topics (UMAP + HDBSCAN; CPU-bound)."""
    storage = QdrantStorage()
    results = compute_clusters(
        storage, umap_n_components=umap_n_components, umap_n_neighbors=umap_n_neighbors,
        hdbscan_min_cluster_size=hdbscan_min_cluster_size, hdbscan_min_samples=hdbscan_min_samples,
    )
    if "error" in results:
        return {"papers": 0, "clusters": 0, "noise": 0, "stored": 0}
    stored = store_cluster_results(storage, results)
    return {"papers": results.get("num_papers", 0), "clusters": results.get("num_clusters", 0),
            "noise": results.get("noise_count", 0), "stored": stored}
```
> Execution note: `compute_clusters(storage, umap_*, hdbscan_*) -> dict` (clustering.py:18) returns `{error,...}` on failure; `store_cluster_results(storage, results) -> int` (clustering.py:178).

- [ ] **Commit Tasks 2–9 each separately** with `feat(pipeline): extract <name> stage`.

---

## Task 10: Native assets + DAG wiring + Definitions

**Files:** Create `src/orchestration/assets/{references,keywords,labeling,resolution,graph,analytics}.py`; Modify `src/orchestration/assets/embedding.py`, `src/orchestration/definitions.py`; Test: `tests/orchestration/test_assets.py`.

- [ ] **Step 1: Failing test.** Append one representative asset test per new asset (mock the stage). Example for two; replicate the shape for all 10:
```python
def test_enrich_refs_s2_asset_records_enriched():
    from dagster import build_asset_context
    from src.orchestration.assets.references import enrich_refs_s2
    async def fake(**k): return {"processed": 8, "enriched": 5, "not_found": 2, "no_refs": 1, "errors": 0}
    with patch("src.orchestration.assets.references.enrich_refs_s2_stage", side_effect=fake):
        out = enrich_refs_s2(build_asset_context())
    assert out.metadata["enriched"].value == 5


def test_analyze_graph_asset_records_metrics():
    from dagster import build_asset_context
    from src.orchestration.assets.graph import analyze_graph
    async def fake(**k): return {"metrics_stored": 424000}
    with patch("src.orchestration.assets.graph.analyze_graph_stage", side_effect=fake):
        out = analyze_graph(build_asset_context())
    assert out.metadata["metrics_stored"].value == 424000
```

- [ ] **Step 2: Run, confirm fail** (ModuleNotFoundError).

- [ ] **Step 3: Implement the asset modules.** Each asset follows the Phase-1 pattern exactly: `asyncio.run(<stage>())`, log, return `MaterializeResult(metadata={k: MetadataValue.int(v) ...})`. Write all 10 with correct `deps`:

`references.py`:
```python
import asyncio
from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset
from src.core.pipeline.stages import enrich_refs_s2_stage, enrich_refs_crossref_stage

@asset(deps=["collect_papers"])
def enrich_refs_s2(context: AssetExecutionContext) -> MaterializeResult:
    """Fill references via Semantic Scholar."""
    counts = asyncio.run(enrich_refs_s2_stage())
    context.log.info(f"S2 refs: {counts}")
    return MaterializeResult(metadata={k: MetadataValue.int(v) for k, v in counts.items()})

@asset(deps=["enrich_refs_s2"])
def enrich_refs_crossref(context: AssetExecutionContext) -> MaterializeResult:
    """Fill remaining references via CrossRef."""
    counts = asyncio.run(enrich_refs_crossref_stage())
    context.log.info(f"CrossRef refs: {counts}")
    return MaterializeResult(metadata={k: MetadataValue.int(v) for k, v in counts.items()})
```

`keywords.py` — `extract_keywords` (`deps=["enrich_abstracts"]`).
`labeling.py` — `label_abstracts` (`deps=["enrich_abstracts"]`).
`resolution.py` — `resolve_refs` (`deps=["enrich_refs_crossref"]`), `enrich_stubs` (`deps=["resolve_refs"]`).
`graph.py` — `build_cited_by` (`deps=["resolve_refs"]`), `analyze_graph` (`deps=["build_cited_by"]`).
`analytics.py` — `compute_similarity` (`deps=["embed_papers"]`), `compute_topics` (`deps=["embed_papers"]`).

Each module mirrors `references.py`'s structure exactly, importing its stage(s) from `src.core.pipeline.stages` and mapping the counts dict to int metadata. (For metadata values that are already ints in the counts dict, `MetadataValue.int` is correct.)

- [ ] **Step 4: Update embed deps.** In `src/orchestration/assets/embedding.py`, change `@asset(deps=["enrich_abstracts"])` → `@asset(deps=["label_abstracts"])` (embedding needs `abstract_structure` from labeling). Update the Phase-1 embed asset test if it asserted the old dep (it does not — it calls the function directly).

- [ ] **Step 5: Register in Definitions.** Rewrite `src/orchestration/definitions.py`:
```python
from dagster import Definitions
from src.orchestration.assets.collection import collect_papers
from src.orchestration.assets.enrichment import enrich_abstracts
from src.orchestration.assets.references import enrich_refs_s2, enrich_refs_crossref
from src.orchestration.assets.keywords import extract_keywords
from src.orchestration.assets.labeling import label_abstracts
from src.orchestration.assets.resolution import resolve_refs, enrich_stubs
from src.orchestration.assets.graph import build_cited_by, analyze_graph
from src.orchestration.assets.embedding import embed_papers
from src.orchestration.assets.analytics import compute_similarity, compute_topics

defs = Definitions(
    assets=[
        collect_papers, enrich_abstracts, enrich_refs_s2, enrich_refs_crossref,
        extract_keywords, label_abstracts, resolve_refs, enrich_stubs,
        build_cited_by, analyze_graph, embed_papers, compute_similarity, compute_topics,
    ],
)
```

- [ ] **Step 6: Run asset tests, confirm pass.**
- [ ] **Step 7: Commit** (`feat(orchestration): phase-2 native assets + DAG wiring`).

---

## Task 11: Validate the full DAG + suite

**Files:** none (validation).

- [ ] **Step 1: Validate the code location and the 13-asset DAG resolves.**
`uv run dagster definitions validate -m src.orchestration.definitions`
Expected: "Validation successful" — all 13 assets load and every `deps=[...]` resolves (no dangling dep names). A typo in any dep string fails here.

- [ ] **Step 2: Full test suite.**
`uv run --extra dev pytest tests/orchestration tests/core/test_pipeline_stages.py -v`
Expected: all pass (Phase-1 + Phase-2 stage tests + asset tests).

- [ ] **Step 3: Asset-list sanity.**
`uv run dagster asset list -m src.orchestration.definitions` → 13 assets.

- [ ] **Step 4: Commit any fixups** (`chore(orchestration): phase-2 validation`).

> **Live materialization is intentionally NOT part of this plan** — the corpus enrich/label/embed backlog is being completed separately, and materializing graph/analytics assets is a heavy real operation. Defer live end-to-end runs to a deliberate session (or Phase 4 scheduling).

---

## Self-Review

- **Spec coverage:** all 10 remaining stages from spec §2 ported (refs s2/crossref, keywords, labeling, resolve+stubs, build_cited_by, analyze_graph, similarity, topics) as shared functions + native assets; DAG deps wired per spec §2 graph; `compute_similarity`/`compute_topics` resolved to **native** (verification: CPU/Qdrant-bound, no GPU) — sparkq remains deferred (no CUDA-bound stage exists yet). embed dep corrected to `label_abstracts`.
- **Placeholder scan:** every stage has complete code; the "Execution notes" are concrete signature-confirmation instructions (same accepted style as Phase 1), not deferred implementation.
- **Type consistency:** all stages return `dict[str, int]`; all assets wrap via `MaterializeResult`/`MetadataValue.int`; `(context)`-only signatures; ordering via `deps=[...]` (state through Qdrant). Stage/symbol names match the Explore-verified entry points (`SemanticScholarEnricher.enrich_by_doi`, `CrossRefEnricher.enrich_by_doi`, `KeywordExtractor`, `AbstractLabeler.label_abstract`, `ReferenceResolver.run_full_pipeline`, `StubEnricher.enrich_stubs`, `storage.build_cited_by_incremental`, `CitationGraphBuilder`/`GraphAnalyzer`, `compute_similarity_batch`, `compute_clusters`/`store_cluster_results`).

## Out of scope → next plans
- **Plan 3 (DQ):** spec §3 asset-checks — now unblocked for all assets (warn-first → block+flag, `dq_flags` payload).
- **Plan 4:** daily/weekly schedules + partitions + failure sensor; retire bash orchestrator.
