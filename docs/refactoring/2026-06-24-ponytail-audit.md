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
