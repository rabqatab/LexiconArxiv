# Ponytail Audit — Deferred Cleanups

**Audit date:** 2026-06-24
**Source:** `/ponytail:ponytail-audit` whole-repo scan after Plan 5 merge (main HEAD `a330349`).
**Status:** **DEFERRED — do NOT apply until trigger below is met.**

## Trigger condition for applying

Apply only **after**:
1. Snapshot bootstrap (Plans 1–4 phases) has been executed end-to-end against the live corpus, AND
2. The corpus is verified stable (search API returns sensible results, DQ asset_checks all PASS, no regressions on the 88-unit + 12-integration test baseline), AND
3. At least 1 week of clean operation has passed.

**Why deferred:** the bootstrap mutates the corpus (stub→real promotion, gap injection). If we simultaneously delete 1800 lines of code and the corpus shows odd behavior, we cannot isolate which change caused it. Refactor on a known-good codebase, not while the data layer is in motion.

## Findings (ranked, biggest cut first)

| # | Tag | What to cut | Replacement | Path |
|---|---|---|---|---|
| 1 | `delete` | entire `src/collectors/` package (BaseCollector, OpenAlexCollector, ArxivCollector, ACLAnthologyCollector) | replaced by `src/core/crawler/`; zero external importers | `src/collectors/*.py` (~1160 lines) |
| 2 | `delete` | `src/core/checkpoint_mixin.py` — class never imported anywhere in src/ (only docs reference it) | nothing | `src/core/checkpoint_mixin.py` (~141 lines) |
| 3 | `shrink` | `src/core/__init__.py` re-exports 40+ symbols. No external code uses `from src.core import X` (callers use submodules) | trim to empty | `src/core/__init__.py` (~140 lines) |
| 4 | `yagni` | `BaseLLMExtractor` + `BaseLLMJudge` ABCs (one impl each: OllamaKeywordExtractor, OllamaJudge) | inline into ollama.py; drop ABC | `src/core/keyword/llm_base.py:116-167` |
| 5 | `yagni` | `BaseAbstractLabeler` ABC (only OllamaAbstractLabeler implements) | drop ABC; type-hint the concrete class | `src/core/labeling/llm_base.py:121-142` |
| 6 | `yagni` | `KeywordJudge` wrapper class — 30 lines wrapping a single `backend.judge_keywords()` call | inline `filter_keywords` into KeywordExtractor | `src/core/keyword/judge.py` |
| 7 | `yagni` | 13 `*_ENV` constants in constants.py — never referenced outside that file | inline literals into getters | `src/core/constants.py:34-61` |
| 8 | `yagni` | `src/core/exceptions.py` — 9 unused exception classes (only `APIRateLimitError` is used) | delete 9 unused | `src/core/exceptions.py` |
| 9 | `yagni` | 4 package `__init__.py` files re-export every symbol with `__all__` — every caller imports from the submodule directly | replace each with empty file or just docstring | `src/core/{labeling,keyword,resolution,citation_graph}/__init__.py` (~85 lines) |
| 10 | `native` | `cachetools.TTLCache` used once in on_demand.py | use `functools.lru_cache` (static) or a 10-line `{key: (expiry, val)}` dict with `time.monotonic()`. Drop cachetools dep | `src/core/search/on_demand.py:8,27` |
| 11 | `native` | `feedparser` only used by `src/collectors/arxiv.py` (dead) | `xml.etree` (already imported in same file). Drop feedparser dep | `pyproject.toml` + dead collector |
| 12 | `yagni` | `python-dateutil>=2.8.0` dep — zero importers in src/ | drop dep | `pyproject.toml` |
| 13 | `yagni` | `auto-mix-prep>=0.2.0` dep — zero importers in src/ | drop dep | `pyproject.toml` |
| 14 | `delete` | `FlushingFileHandler` overrides `flush()` to call super then `flush()` — Python's logging does this on shutdown anyway | use `RotatingFileHandler` directly | `src/cli/_logging.py:21-26` |
| 15 | `yagni` | `GraphServices.reset_services()` + global `_services` pattern alongside `@lru_cache get_services` — only docs reference reset_services | delete `reset_services` + the global; rely on `lru_cache.cache_clear()` | `src/api/dependencies.py:138-159` |
| 16 | `yagni` | `BaseCollector.MAX_RETRIES` class attr declared but never read (retry decorator hardcodes 3) | delete (moot if `src/collectors/` is deleted) | `src/collectors/base.py:43` |
| 17 | `yagni` | `BaseCollector.collect_all` default offset-based loop — concrete subclasses all override or never call it | drop (moot if collectors/ deleted) | `src/collectors/base.py:159-183` |
| 18 | `shrink` | `PhaseSummary.to_dagster_metadata` reimplements `{**asdict(self), **self.extra}` minus `'phase'` and `'extra'` | replace with `{**asdict(self), **self.extra}` (1 line) | `src/core/snapshot/stats.py:27-37` |
| 19 | `stdlib` | `src/core/checkpoint.py` + `src/core/checkpoint_mixin.py` duplicate the per-checkpoint `json.dump`/`json.load` + `asdict` pattern | pick one (the snapshot `checkpoint.py` is the live one; `checkpoint_mixin.py` is dead per #2) | both files |

**Estimated impact:** -1800 lines, -4 dependencies (`cachetools`, `feedparser`, `python-dateutil`, `auto-mix-prep`).

## Out of scope

- Correctness bugs (use `/code-review` for those).
- Performance.
- Snapshot system internals (design is intentional per `docs/superpowers/specs/2026-06-21-snapshot-utilization-design.md`; the items above that touch the snapshot package are clear hand-rolled stdlib equivalents only).

## How to apply (when the trigger is met)

1. Cut a worktree `git worktree add .claude/worktrees/ponytail-cuts -b ponytail-cleanup`.
2. Apply items in order — biggest cuts first. After each tag's worth of cuts, run `uv run --extra dev pytest` + `uv run dagster definitions validate -m src.orchestration.definitions`.
3. Items #1, #2, #16, #17 are all "delete `src/collectors/`" — handle as a single commit (the dead package), then `pyproject.toml` dep removal (#11) lands cleanly.
4. The ABC removals (#4, #5, #6) need a quick check that no test/fixture references the abstract names; they all use the concrete classes.
5. Final whole-branch review with the most capable available model; merge FF.

Owner: whoever next has 2–3 hours to spend on cleanup. Reviewer: a fresh pair of eyes from outside this audit (so the report doesn't bias the review).

## Addendum — 2026-06-24 (during bootstrap)

**20.** `yagni` `QdrantStorage.get_payload` alias added in commit `5cc3bac` as a bootstrap hotfix. Replace by renaming mock + 2 phase callsites + 17 test callsites to `get_paper_by_id`; then drop the alias. The bug it papered over: real storage and mock storage diverged on the name (mock was written first without checking real's interface). The regression test in `tests/core/snapshot/test_storage_compat.py` is permanent and should stay — it catches future drift on any phase-called method. [src/core/storage/base.py:297-305 — the `# ponytail:` block names this exact follow-up]

**21.** `delete` — `find_real_by_identifier` made 1-3 sequential scroll calls per stub promotion. Now O(log N) via `ensure_identifier_indices()` (commit `82ef621`, 2026-06-29). **Full postmortem:** [`docs/incidents/2026-06-29-p2-missing-payload-indices.md`](../incidents/2026-06-29-p2-missing-payload-indices.md). The audit item this fix surfaces: there is **no startup check that warns when query-hot payload fields lack indices**. A quick `assert_indices_for_phases()` that runs at every phase startup and logs `WARNING: field X used by P{n} is unindexed — expect ~250x slowdown` would prevent future repeats. Code lives in `src/core/storage/base.py:ensure_identifier_indices`; pattern extends naturally to P1/P3/P4 fields if any future phase grows new query patterns. [test_storage_compat.py already pins the method's existence on real storage]

## Addendum — 2026-07-03 (MCP polish wave, after 07-03 incident)

Five commits landed to harden the MCP surface after the 2026-07-03 incident.
The theme was "install smoke detectors along the edges the incident exposed."
See full context in [`docs/incidents/2026-07-03-mcp-search-endpoints-broken.md`](../incidents/2026-07-03-mcp-search-endpoints-broken.md) §Follow-up hardening.

**22.** `yagni` — Author-shape adapter should live at the storage boundary, not inside every formatter. `_author_name(a)` is currently defined in `src/mcp/formatters.py` and called at three sites (search, detail, research). The right home is a `_normalize_authors_on_read()` hook inside `QdrantStorage.retrieve()` / `.scroll()` return path, so payload consumers always see `list[str]` regardless of what P2 wrote. Cost of the current setup: 3 identical adapter calls, 9 formatter tests that pin the shape at the formatter (should pin at storage). Deferred with the audit — same trigger. When applied, `_author_name` collapses out of formatters entirely; formatter tests migrate to a storage-layer contract test. [`src/mcp/formatters.py:6-29`, applied 3 sites: L59, L122, L248]

**23.** `yagni` — Startup indexed-field linter (from item #21 above and 2026-07-03 incident Lesson 4). The 2026-07-03 hang was `source_id` unindexed — a payload-field-condition scan that nobody's startup would catch. A `verify_indexed_scroll_filters(storage)` at server start could `grep`-equivalent all call sites for `Filter(must=[FieldCondition(key=X, …)])` and emit `WARNING: field X is not indexed — expect scans to full-scan the collection` if `X` isn't in Qdrant's `payload_schema`. Now redundant-with-defense: the per-handler 5s timeout budget (commit `253afcf`) will surface the same failure fast, so this becomes "nice-to-have" rather than "must-have" — the timeout catches the pain, the linter would catch the *cause*.

**24.** `yagni` `abstract-qwen3-8b` vector is generated for every paper (~33% of every embed drain's GPU time) but never queried by the search pipeline. Only caller: `src/core/analytics/clustering.py:55` (UMAP + HDBSCAN topic clustering, runs weekly at most). Migration path:

1. Change `clustering.py:55,64` to load `structured-abstract` instead of `EMBEDDING_VECTOR_NAME`.
2. Run one small `compute_clusters(sample=10_000)` before + after; compare HDBSCAN cluster silhouette scores and topic labels. Expect similar or better quality (role-tagged text is at least as semantically rich as raw abstract).
3. If the eval passes: remove `EMBEDDING_VECTOR_NAME` from `constants.ALL_DENSE_VECTORS`, drop the vector generation block in `embedder.py:183-184`, migrate the collection via `client.delete_vectors(names=["abstract-qwen3-8b"])`.

**Not applied during 2026-07-03 embed drain planning** because the bootstrap is actively mutating the corpus and layering a vector-schema migration on top would confuse root-cause analysis of any drain-side issue. The 33% savings tradeoff was correctly deferred; see the drain runbook for the alternatives (parallelism scaling, batch tuning) that do NOT require schema changes.

Trigger: same as the whole audit — corpus stable ≥1 week AND bootstrap complete. Owner: whoever runs the eval + migration. Reviewer: someone who wasn't in the audit conversation. [full context in [`docs/incidents/2026-07-03-mcp-search-endpoints-broken.md`](../incidents/2026-07-03-mcp-search-endpoints-broken.md) §Follow-up hardening + verification #3]

**25.** **STATUS: IN PROGRESS 2026-07-04** — Migrate abstract labeling from Ollama to vLLM. Ollama's single-GPU serial pipeline hit its ceiling at ~750 papers/hr regardless of concurrency (measured 2026-07-04). At bootstrap scale (3M papers to label from P2 promotions + P3 injections) this projects to 167 days — infeasible. vLLM's continuous batching targets 30K+ papers/hr on the same model family (`ibm-granite/granite-4.1-8b`), reducing the labeling window to ~4 days. Backend abstraction landed; POC + quality eval + throughput bench blocked on P3 completion. Full design in [`docs/design/vllm-labeling-migration.md`](../design/vllm-labeling-migration.md). Files touched: `src/core/labeling/vllm.py` (new), `src/core/labeling/labeler.py` (dispatch extended), `src/cli/commands/labeling.py` (--backend flag), `scripts/labeling/serve_vllm.sh` (sparkq launcher). Ollama remains the default and only backend for incremental (post-bootstrap) labeling — vLLM's serve-time overhead isn't worth it below ~10K papers/month.

### Polish work completed 2026-07-03 (not deferred)

These landed during the wave rather than being marked "when the trigger is met" — they were user-pain fixes, not stylistic cleanups.

| ✅ | Item | Commit |
|---|---|---|
| ✅ | **MCP polish A** — `get_corpus_stats` top-N venue cap (was 1.6MB / 38K lines) | `f90934e` |
| ✅ | **MCP polish B** — `get_mcp_version` tool + startup version log for cross-session drift detection | `2f8cf12` |
| ✅ | **MCP polish C** — Per-handler `asyncio.wait_for` timeout budget (5s default + per-handler overrides) | `253afcf` |
| ✅ | **Test fix G** — SearchService fixture rebuilt from `ALL_DENSE_VECTORS` (structured-abstract drift) | `880c639` |
| ✅ | **Test net F** — L3 crash-safety regression suite for `drain_snapshot_queue()` | `25a262a` |

Test count: 382 → 417 passing across suites; MCP subtree grew from 9 → 29 tests.

## Application record — 2026-07-08 (trigger met: bootstrap complete + first clean end-to-end incremental `6283`)

A second repo-wide `/ponytail:ponytail-audit` ran 2026-07-07 (fresh list, 16 items,
~1,300 lines) and the user green-lit application. Both lists were worked in one
wave — **17 commits `2569563`..`1566a48`, net ≈ −3,600 lines, −4 deps**.

### Applied (fresh-audit numbering)

| # | Item | Commit |
|---|---|---|
| 2 | Retry unify → `src/core/storage/_retry.retry_qdrant` (Wave 1e-bis) | `c708ae4` |
| 3+12 | Dead keyword LLM path (ollama/llm_base/judge + ABCs + CLI flags + 636-line test module) | `e865217` |
| 4 | `external_search` + `_search_and_add_paper` + `_search_openalex_by_title` | `8956134` |
| 5–9 | Stale one-off scripts (tracked + untracked) | `2569563` |
| 10 | Deprecated `run_snapshot_enrichment` chain (runner, CLI cmd, matcher candidate path, reader/writer/facade methods) | `819eb61` |
| 11 | Single canonical title normalizer (`Deduplicator.normalize_title` + NFKD; 2 local copies deleted) | `22d1b60` |
| 14 | `get_payload` alias dropped, all callsites → `get_paper_by_id` (also closes old-audit #20) | `b69da64` |

### Applied (old-audit 2026-06-24 numbering)

| # | Item | Commit |
|---|---|---|
| 1/2/16/17/19 | `src/collectors/` package + `checkpoint_mixin.py` deleted | `af7eb07` |
| 11 | `feedparser` dep dropped (only user was dead collectors/arxiv.py) | `af7eb07` |
| 3/8 | `src/core/__init__.py` → docstring-only; `exceptions.py` → only `APIRateLimitError` | `06b7b83` |
| 10/12/13 | `cachetools` (TTLCache → 10-line dict), `python-dateutil`, `auto-mix-prep` deps dropped | `aa11faf` |
| 14/15/18 | `FlushingFileHandler`, `reset_services`, `PhaseSummary.to_dagster_metadata` asdict | `1566a48` |
| 4/6/20 | Subsumed by fresh-audit #3+#12/#14 above | — |

### Skipped, with reasons (do not re-attempt without re-verifying)

- **Fresh #1 (facade ~70 delegation methods)** — max cut but widest blast radius; bundle with Wave 5 test re-org as the audit itself recommended.
- **Fresh #13 (stub ID → uuid5)** — WRONG in practice: `_generate_stub_id`'s sha256-derived IDs are persisted on ~2.6 M live stubs; switching algorithms breaks idempotent upserts and duplicates stubs.
- **Fresh #15 (keyword loop dedup)** — the CLI loop carries an interactive contract (dry-run, sample preview, live progress) the Dagster stage doesn't; unifying needs flags/callbacks that outweigh ~30 lines.
- **Fresh #16 (`fuzzy_matching` flag removal)** — audit claim was wrong: the live incremental script runs Step 7 with fuzzy **off**; hardcoding True adds an O(corpus) SequenceMatcher scan per unresolved title.
- **Old #5 (BaseAbstractLabeler ABC)** — obsolete: since the vLLM migration there are two implementations (Ollama + vLLM); the ABC now earns its keep.
- **Old #7 (`*_ENV` constants)** — claim stale: `GITHUB_TOKEN_ENV` is imported by `github_search.py`.
- **Old #9 (package `__init__` re-exports)** — claim stale: e.g. `from src.core.keyword import KeywordExtractor` is a live import path.
- **Old #22 (author-shape adapter → storage boundary)** — real but needs a 9-test migration; keep deferred.
- **Old #23 (startup index linter)** — superseded in urgency by per-handler timeouts; fold into Wave 1e-ter if built.
- **Old #24 (drop `abstract-qwen3-8b` vector)** — DB schema migration + clustering eval; run as its own planned change, not a code-cleanup side effect.
