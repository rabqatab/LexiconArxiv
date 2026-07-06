# Code Overhaul Plan — Post-2026-07-04

**Author:** MCH
**Date:** 2026-07-04
**Status:** **DEFERRED — planning only, do NOT execute until trigger below is met.**

## Trigger condition for applying

Apply only **after**:
1. Snapshot bootstrap (P1-P4) has completed end-to-end against the live corpus, AND
2. The full [post-bootstrap catchup](../runbooks/post-bootstrap-catchup.md) has completed (labeling → keywords → refs → embed → similarity → graph → topics → DQ), AND
3. The corpus is verified stable (search API returns sensible results, all DQ asset_checks PASS, no user-reported quality regressions on the newly-added ~2-4M papers), AND
4. **At least 1 week** of clean operation has passed.

**Why deferred:** the same rationale as the [2026-06-24 ponytail audit](2026-06-24-ponytail-audit.md). We are simultaneously (a) mutating the corpus at 3M-paper scale, (b) migrating labeling to vLLM, and (c) executing a runbook that touches every downstream stage. Adding structural refactors to that pile makes root-cause analysis impossible when something goes sideways. Refactor on a known-good codebase, not while the data layer is in motion.

**Sibling doc:** the 2026-06-24 ponytail audit already tracks 25 line-level cuts. This plan is different — it groups them by **overhaul domain** and adds cross-cutting items (registries, abstractions, deprecation removals) that emerged from the 2026-07-04 wave. Merge both when executing.

---

## Motivation

Between 2026-06-24 (ponytail audit) and 2026-07-04 (labeling gap) the codebase acquired new debt in three shapes:

1. **Duplication from parallel evolution.** vLLM and Ollama labeling share HTTP retry + schema-marshalling logic. Same shape will emerge for HyDE if it ever migrates. See §Wave 2.
2. **N-file-touch operations.** Adding one DQ check requires editing `dq.py`, `checks.py`, and `quality.py`. Adding one CLI command touches its file, `core_collect.py`, and often a doc. Nothing enforces consistency — the labeling gap survived precisely because nobody had a single-file catalog of "what phases must run against every paper." See §Wave 1.
3. **Dead-weight files/deps that survived because they were "harmless."** `abstract-qwen3-8b` vector, `feedparser`/`python-dateutil`/`auto-mix-prep`/`cachetools` deps, several ABC-with-one-impl class hierarchies. See §Wave 4.

**Not motivating**: raw line count. `stubs.py` (910 lines), `enrichment.py` (1036 lines), `reader.py` (852 lines) are long but internally consistent. Splitting them for line-count reasons alone would create more cognitive overhead than it removes.

---

## Waves (execution order when triggered)

### Wave 1 — Registries and enforcement (safe, non-breaking)

Add machine-checked catalogs so future gaps like 2026-07-04 fail at CI time, not in production.

| Item | Files touched | Notes |
|---|---|---|
| **1a. DQ check registry** | `src/core/pipeline/dq.py`, `src/orchestration/checks.py`, `src/cli/commands/quality.py`, `tests/core/test_dq.py` | Single `CHECKS = [...]` list in `dq.py` declaring `{name, fn, severity, threshold, asset_binding}`. `checks.py` and `quality.py` iterate the registry — no more 3-file touch per check. Add tests that assert the CLI JSON output includes every registered check. |
| **1b. "Papers-must-have-fields" contract** | New: `src/core/pipeline/paper_contract.py`, `src/core/pipeline/dq.py` | Explicit list of every payload field a real paper is expected to have after full bootstrap + catchup: `abstract`, `abstract_structure`, `keywords`, `keywords_structured`, vectors present, similarity edges, `cluster_id`, `pagerank`. DQ has one check per field; the labeling gap could not have hidden here. |
| **1c. CLI command manifest** | `src/cli/core_collect.py`, `tests/cli/test_commands.py` | Auto-generated from CLI + a small manifest declaring which commands belong to bulk vs incremental vs ops. Test asserts every command is categorized. Prevents another "we forgot which pipeline this belongs to" incident. |
| **1d. Vector schema versioning** | `src/core/constants.py`, `src/core/storage/base.py` | Add `VECTOR_SCHEMA_VERSION` string; write to collection metadata on `ensure_collection_with_vectors`. Any code that reads a vector name checks the version and refuses gracefully (with a documented migration path) if it doesn't match. Precondition for §Wave 3 abstract-qwen3-8b removal. |
| **1e. Generalize `_retry_qdrant_call` across all bulk write paths** | `src/core/storage/writer.py` | The 2026-07-04 targeted fix wrapped `batch_update_abstract_structure` in retry after a single `set_payload` timeout torched the whole 500-paper batch (commit `c61a652`). The same shape applies to `batch_update_code_repos`, `batch_extend_external_cited_by`, `batch_inject_papers`, and the sequential upserts inside phase-2/3 runners. Extend the helper's coverage; treat any bulk write without retry as a latent regression. |
| **1e-bis. Same coverage across all bulk READ paths** (added 2026-07-06 after 830c/d582/7e38 fatals) | `src/core/storage/reader.py` | The 2026-07-06 targeted fixes wrapped `get_papers_missing_abstracts` (commit `a10edcb`) and `get_papers_missing_references` (commit `b629b46`) in `_retry_qdrant_call` — but the remaining scroll methods (`get_papers_missing_references_no_doi`, `get_papers_for_abstract_labeling`, `get_papers_missing_keywords`, `iter_enrichment_candidates`, `scroll_by_arxiv_ids`, etc.) still call `self.client.scroll` bare. When any Qdrant scroll times out, that call site becomes the next fatal. Move `_retry_qdrant_call` to a shared `src/core/storage/_retry.py` (both readers and writers import from there — currently the reader imports the writer for the helper, which is a directional leak), and wrap every remaining scroll/count in it. |
| **1e-ter. Bulk-scroll filter-shape lint** (added 2026-07-06) | `tests/core/test_storage_reader.py`, `src/core/storage/reader.py` | Introduce a test that inspects `payload_schema` on a fresh test collection, then for every `scroll_filter` shape returned by the reader methods asserts each `FieldCondition.key` and `IsEmptyCondition.is_empty.key` maps to an indexed field. Rationale: the 2026-07-06 6.2 M-scale fatals were latent as soon as the corresponding index disappeared — a schema-driven lint would have flagged them at CI time instead of at 3 am incident time. Include an explicit whitelist for narrow non-scroll callsites (`retrieve`, `get_by_id`) where a full scan is OK. |
| **1e-quater. Backfill `fetched_at` on P2/P3-injected points** (added 2026-07-06) | `src/core/snapshot/writer.py`, new one-off `scripts/analytics/backfill_fetched_at.py` | Root cause: `snapshot/writer.py::batch_inject_papers` and `batch_promote_stubs_from_snapshot` set `injected_at` / `promoted_at` / `snapshot_filled_at` but never `fetched_at`. Result: 178 K of 6.2 M points have `fetched_at`, so `--recent-days` only reaches original-crawler papers. Fix the snapshot writers to populate `fetched_at = snapshot_filled_at` at write time (already computed in the same block), and ship a one-off backfill script that scans existing P2/P3 points where `fetched_at` is empty and copies `snapshot_filled_at` (now indexed — the join is cheap). Follow-up impact: the `--recent-days` filter becomes reachable for snapshot-injected papers, which unblocks proper year-based chronological chunking of the labeling backlog. |

**Estimated effort:** 1-2 days. Purely additive; nothing removed.

### Wave 2 — Backend abstraction cleanup (minor breaking)

Consolidate the labeling backend HTTP + retry logic; prepare for HyDE-vLLM migration if ever needed.

| Item | Files | Notes |
|---|---|---|
| **2a. Extract `BaseHTTPLabeler`** | New: `src/core/labeling/http_backend.py`; refactor `src/core/labeling/ollama.py`, `src/core/labeling/vllm.py` | Common: httpx client, semaphore, exponential-backoff retry, exception unwrapping. Subclasses declare their endpoint + payload shape only. Reduces both concrete classes from ~80 lines to ~30. |
| **2b. Consolidate CLI backend params** | `src/cli/commands/labeling.py` | 5 backend params (`ollama-model`, `ollama-timeout`, `vllm-model`, `vllm-base-url`, `vllm-max-concurrent`) → 3 (`--backend`, `--model`, `--config-key`). Model + timeout resolve from a `labeling_backends.toml` config file when `--config-key` is set. |
| **2c. Consider CLI reorganization** | `src/cli/commands/{labeling,keywords,embedding}.py` → possibly `src/cli/commands/{bulk,incremental,search}.py` | **Investigate before deciding.** Grouping by user intent (bulk vs incremental vs ops) matches the audit's mental model but breaks muscle-memory paths. Do only if the manifest from 1c shows genuine confusion. |

**Estimated effort:** 2-3 days. Backend param change is a soft breakage — old flags become aliases with a deprecation warning, gone in the next minor.

### Wave 3 — Vector schema migration (breaking, careful)

`abstract-qwen3-8b` (~11% of embed cost) is dead-weight for search but used by UMAP clustering. Migrate clustering to `structured-abstract`, drop the extra vector.

| Item | Files | Notes |
|---|---|---|
| **3a. Clustering-vector migration eval** | New: `scripts/analytics/eval_clustering_vector_migration.py` | Compute clusters on both `abstract-qwen3-8b` and `structured-abstract` on a 10K-paper sample; compare HDBSCAN silhouette scores, cluster label agreement, MMR-in-cluster diversity. Pass condition documented before running. |
| **3b. Migration script** | New: `scripts/analytics/migrate_clustering_vector.sh` | Move clustering code to read `structured-abstract`; run `client.delete_vectors(names=["abstract-qwen3-8b"])` on the collection; drop `EMBEDDING_VECTOR_NAME` from `ALL_DENSE_VECTORS`. Requires §1d schema versioning already in place. |
| **3c. `SearchService.dense_vector_name` cleanup** | `src/core/search/service.py` | Remove the vestigial `dense_vector_name` parameter (line 40 currently defaults to `EMBEDDING_VECTOR_NAME` but is never used in the search flow). Ponytail audit item #24 sub-item. |

**Estimated effort:** 3-5 days including eval + migration + verify. Skip 3b/3c if 3a shows unacceptable quality loss.

### Wave 4 — Deprecation removals + dep prune

Ponytail audit items with confirmed no-caller status.

| Item | Files | Notes |
|---|---|---|
| **4a. Remove `drain()` deprecated shim** | `src/core/snapshot/embedding_queue.py`, `tests/core/snapshot/test_embedding_queue.py`, `tests/core/snapshot/test_promotion.py` | The deprecation warning has been live since the 2026-06-30 incident. Update remaining test call sites to use `peek_all + remove`, delete the shim. |
| **4b. Drop `--llm` / `--judge` from `extract-keywords`** | `src/cli/commands/keywords.py`, `docs/pipelines/keyword_extraction.md`, `docs/guides/crawling.md` | Docs already flag these as deprecated. Remove after one incremental cycle proves no one is passing them. Reduces `extract-keywords` CLI surface by ~4 flags. |
| **4c. Dep prune (ponytail audit items #10-13)** | `pyproject.toml`, `uv.lock`, `src/collectors/` (if not already dead) | Drop `feedparser`, `python-dateutil`, `auto-mix-prep`, `cachetools`. Requires ponytail audit items #1 (delete collectors) landed first. |
| **4d. Retire `EMBEDDING_VECTOR_NAME` constant** | `src/core/constants.py`, downstream imports | Depends on §3. |
| **4e. Retire Ollama chat CLI fallback for labeling** | `src/cli/commands/labeling.py`, `src/core/labeling/ollama.py`, `src/core/labeling/labeler.py` | Only after 2 clean incremental cycles run entirely on vLLM. Ollama chat then serves nothing (embedding + HyDE use separate models). Keeping it fed will otherwise create the same silent-bit-rot the Gemini backend suffered. |

**Estimated effort:** 1-2 days total. Each item is independent; land as ready.

### Wave 4b — Corpus quality audit (data, not code)

Split from Wave 4 because this is DATA cleanup, not deprecation-removal. Trigger: catchup stable.

Discovered 2026-07-06 during catchup labeling. Two intertwined issues — see [`docs/design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §P3 data-quality gap and [`docs/plans/TODO.md`](../plans/TODO.md).

- **Issue A**: `discover_corpus_gaps` (P3) leaked non-article types (`book`, `peer-review`, `editorial`, …) into the corpus.
- **Issue B**: Ollama-labeled papers (be19's 91 K + last incremental's ~152 K + pre-Path-B ≈ 250-400 K total) have partial `abstract_structure` because Ollama's default `num_ctx` silently truncates long prompts. Their labels only reflect the first ~40 sentences.

Scope is **cross-provenance** — not just P3 — because Issue B touches original-crawler and incremental papers too, and Issue A may exist in trace amounts elsewhere.

| Item | Files / actions |
|---|---|
| **4b-1. Enumerate `type` distribution across the ENTIRE corpus** | new: `scripts/analytics/count_by_type.py` (or a `type-stats` CLI). Report count per (`type`, `provenance`) cell. Provenance derived from: `injected_from_snapshot=true` (P3), `snapshot_filled_at` set but not injected (P2 promotion), rest = original crawler + incremental. |
| **4b-2. Design keep/delete policy** | Whitelist: `article`, `preprint`, `conference-paper`, `dissertation`. Blacklist: `book`, `peer-review`, `editorial`, `letter`, `erratum`, `retraction`, `other`. Confirm against a manual review of borderline types (`book-chapter`, `report`). Document in the audit doc appendix. |
| **4b-3. Delete non-article points + cleanup refs** | new: `scripts/analytics/delete_by_type.sh`. Steps: (a) collect point_ids from blacklist, (b) delete from Qdrant, (c) remove similarity edges (`get_similar_papers` payload), (d) purge from `cited_by` / `external_cited_by` on remaining papers, (e) remove from Dagster asset materialization metadata if any. |
| **4b-4. Spot-check original-crawler edge cases** | Sample 20 papers per crawler (ArXiv, ACL, DBLP, OpenReview, ACM, AAAI). Look for `type=other`, workshop reports, panel discussions, invited talks stored without abstracts. Update policy if a new type surfaces. |
| **4b-5. Re-label Ollama-partial papers with vLLM** | `label-abstracts --force --backend vllm` with a payload filter of `abstract_structure_source=ollama` AND surviving-after-4b-3. Volume ~250-400 K. Uses the 25-sentence truncation contract for consistency with the rest of the vLLM-labeled corpus. Cost ~10-20 h at production vLLM rate. |
| **4b-6. DQ warn-check** | `src/core/pipeline/dq.py`: new `nonarticle_type_share()` check that WARNs when the corpus contains >1 % blacklisted types. Also `ollama_labeled_share()` that WARNs when >5 % of `abstract_structure_source=ollama` remain post-catchup. Wired into `data-quality` CLI + Dagster asset. |
| **4b-7. Filter at source** | `src/core/snapshot/phase3_gap_discovery.py`: add explicit `type` whitelist to `process_one`. Log the count of rejected-by-type per run. Next quarterly P3 will not re-introduce the pollution. |

**Estimated effort:**
- 4b-1 + 4b-2: 1-2 days
- 4b-3: 1 day (cleanup refs is where the work is)
- 4b-4: 1 day
- 4b-5: passive during vLLM run (~10-20 h wall clock, no operator time)
- 4b-6 + 4b-7: half a day each

Total operator time ~5 days spread across a couple of weeks.

### Wave 5 — Test suite reorganization

| Item | Files | Notes |
|---|---|---|
| **5a. Consolidate `tests/mcp/` under `tests/core/mcp/`** | Move directory; keep the `__init__.py`-shadow trap fix noted in `docs/reference/mcp-server.md` visible in the new location too. |
| **5b. Split `tests/test_search_service.py`** | Currently one file covers hybrid, BM25 fallback, year filter, get_paper. Split into concern-specific files under `tests/core/search/`. |
| **5c. Mark integration tests explicitly** | `tests/` scan for tests requiring Qdrant / Ollama / real network. Add `@pytest.mark.integration`. `pytest --ignore=tests/integration` becomes `pytest -m "not integration"`. |
| **5d. Add L4 end-to-end contract test** | New: `tests/integration/test_bootstrap_to_search.py`. Seed 10 papers via a fake snapshot, run bootstrap → catchup, verify every paper has all §1b-required payload fields. This would have caught the 2026-07-04 labeling gap. |

**Estimated effort:** 2 days for moves + markers; ~3 days for the L4 contract test (seed fixtures + orchestration).

---

## Non-goals

- **File-count reduction for aesthetics.** No one is helped by fewer files if the ones remaining are 2000 lines each. Split only when a genuine cognitive boundary exists (§Wave 2's backend split, §Wave 5's search test split).
- **Renaming for renaming's sake.** `granite4.1:8b` vs `ibm-granite/granite-4.1-8b` is intentional (Ollama tag vs HF repo). Don't unify.
- **New abstractions "for later."** The `BaseAbstractLabeler` ABC + two backends is the correct shape; don't add a `LabelerFactory` or `LabelerRegistry` unless a real third backend arrives.
- **Rewriting anything that works.** `enrichment.py` at 1036 lines is annoying to navigate but internally coherent (one CLI per enrichment source). Don't touch.

---

## Order rationale

Wave 1 first because **it makes future gaps impossible**, not because it fixes today's pain. Once the registries + contract exist, Waves 2-5 can be landed independently by anyone without cross-cutting worry.

Wave 3 (vector migration) is high-impact but high-risk — postpone until §1d schema versioning exists to make the rollback story clear.

Wave 4 removals are cheap individually but should NOT be batched into one commit — each deprecated symbol needs one incremental cycle of "no one hit this" evidence before deletion.

---

## Cross-refs

- [2026-06-24 ponytail audit](2026-06-24-ponytail-audit.md) — line-level cut list; merge with §Wave 4 when executing.
- [2026-07-04 bulk vs incremental audit](../design/bulk-vs-incremental-audit.md) — the design-level gap analysis that seeded Wave 1.
- [2026-07-04 vLLM labeling migration](../design/vllm-labeling-migration.md) — the migration that surfaced Wave 2's backend duplication.
- [post-bootstrap catchup](../runbooks/post-bootstrap-catchup.md) — the runbook Wave 1 formalizes into machine-checked contract.

---

## Sign-off before executing

Before landing any wave, verify:

1. All conditions in §Trigger condition for applying are met.
2. The specific wave's items still make sense (recheck for outdated assumptions; codebase evolves).
3. A code-review agent reviews the entire wave as one PR after all items land locally.
4. `uv run pytest tests/ --ignore=tests/integration` fully green.
5. `uv run dagster definitions validate -m src.orchestration.definitions` clean.

Owner: whoever holds the 3-5 days after the trigger fires. Reviewer: a fresh pair of eyes from outside the sessions that produced these debts.
