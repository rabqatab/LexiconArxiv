# MCP search endpoints broken after P2 promotion — 60s timeouts + None arithmetic

**Date:** 2026-07-03
**Severity:** High — every non-UUID paper lookup blocked; search + research_topic + MCP `get_paper` all failing
**Status:** Resolved (commit `<this commit>`)
**Reported by:** Another Claude Code session (tradingR1_qflib tmux) trying to consume LexiconArxiv MCP; the errors happened silently for hours before triage.

## TL;DR

Two independent bugs surfaced together the moment P2 finished promoting 940K stubs to real papers:

1. `get_paper_by_arxiv_id` used a scroll filter on the **unindexed** `source_id` field → 60s timeouts on every arXiv-ID lookup that fell past the direct UUID check. Fix: query the **indexed** `arxiv_id` field first, add a keyword index on `source_id` for the legacy fallback, and make `ensure_identifier_indices()` cover both permanently.
2. The `apply_citation_boost` postprocessor and `research_topic` scoring both did `r.get("citation_count", 0)` — which returns `None` when the payload has `citation_count: None` (P2 sometimes writes it that way from OpenAlex snapshot works with no citations recorded). `math.log(1 + None)` and `None / max_c` raised `TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'`. Fix: normalize with `r.get(k) or 0` on every numeric field in the ranking path.

Both bugs were latent — the P2 write patterns didn't exist before this quarter's bootstrap, and the search unit tests never covered a `None` in the payload numerics. The other Claude session hit both within a few queries.

## Timeline

| Time (UTC+9) | Event |
|---|---|
| 2026-07-01 → 07-03 | P2 promoted 940K stubs to real papers over ~13h (post-index-perf-fix). Some promoted works had `citation_count: None` in payload (OpenAlex snapshot). |
| 2026-07-03 ~08:00 | Another Claude session (tradingR1_qflib) tried to look up 7 papers by arxiv ID via MCP `get_paper` → 60s timeouts. Tried `search_papers` and `research_topic` → `int + NoneType` traceback. |
| 2026-07-03 08:30 | Operator escalated the bug report to this session |
| 2026-07-03 08:45 | Reproduced both bugs; measured single `get_paper_by_arxiv_id` at 60s+. Traced traceback for the ranking bug to `postprocess.py:34` and `research.py:110`. |
| 2026-07-03 09:00 | Both bugs fixed in code; keyword index on `source_id` added; 3 regression tests pass. |

## Root causes

### Bug 1 — `source_id` unindexed → 60s scroll on every arXiv lookup

```python
# src/core/storage/query.py:74 (pre-fix)
def get_paper_by_arxiv_id(self, arxiv_id: str) -> tuple[str, dict] | None:
    results = self.client.scroll(
        collection_name=self.collection_name,
        scroll_filter=models.Filter(
            should=[
                models.FieldCondition(key="source_id", match=models.MatchValue(value=f"arXiv:{arxiv_id}")),
                models.FieldCondition(key="source_id", match=models.MatchValue(value=arxiv_id)),
            ]
        ), limit=1, with_payload=True,
    )
```

Two problems compounded:
1. **`source_id` is not indexed.** Same class of bug as the 2026-06-29 P2 slowdown — every scroll full-scans 3.6M points.
2. **Two `should` conditions on the same unindexed field.** Qdrant evaluates each independently → potentially 2 full scans per lookup.

Meanwhile the collection has a fully-populated `arxiv_id` field (92,670 points) with an existing index. But the code chose the wrong field to query.

### Bug 2 — `.get(k, default)` returns `None` when the payload has `k: None`

```python
# src/core/search/postprocess.py:34 (pre-fix)
max_citations = (
    max((math.log(1 + r.get("citation_count", 0)) for r in results), default=1)
    or 1
)
```

Python's `dict.get(key, default)` returns `default` **only if the key is missing**. When the key exists with value `None`, `.get` returns `None` — not the default. `math.log(1 + None)` then raises `TypeError`.

P2 promotion writes a field like `"citation_count": None` when the OpenAlex snapshot has no external citations data. That was unreachable through the search API before P2 — the pre-P2 real papers (crawled, then enriched) always had `citation_count` set to at least 0. P2 exposed the None state.

The fix pattern is uniform: `r.get(k) or 0` for numeric fields. Same fix applied at three call sites (`postprocess.py:33-42`, `research.py:106-118`).

## Detection

Followed `systematic-debugging` Phase 1:

1. **Reproduce** — direct Python calls to `queries.get_paper_by_arxiv_id('2504.13837')` (a P2-promoted paper) and `research_topic('transformer attention')`. Both failed immediately with clear tracebacks.
2. **Read errors carefully** — Bug 2's `int + NoneType` message pointed directly at the `math.log(1 + None)` expression. Bug 1's `Timeout error: scroll_by_id timed out after 60s` said "unindexed scroll".
3. **Check recent changes** — nothing changed in the search code. What changed: **P2 write patterns**. P2 populated arxiv_id and left citation_count as None for many promoted stubs. Both bugs were latent, waiting for that specific data shape.
4. **Truth source** — `curl` on the Qdrant `payload_schema` showed `arxiv_id: keyword (92,670 pts)` was indexed, while `source_id` was not. Immediately revealed the "wrong field queried" bug.

## Resolution

### `src/core/storage/query.py:get_paper_by_arxiv_id`

Try the **indexed** `arxiv_id` field first (both raw and `arXiv:` prefixed formats). Fall through to the legacy `source_id` scroll only if the arxiv_id path misses. The `source_id` field is now also indexed (permanent via `ensure_identifier_indices()`), so the fallback is fast too.

### `src/core/storage/base.py:ensure_identifier_indices`

Add `source_id` to the auto-created keyword indices. The method now covers `doi`, `openalex_id`, `arxiv_id`, `source_id` — every payload field used as a scroll filter in `find_real_by_identifier` and `get_paper_by_*`. Called at `ensure_collection()` + `phase2_stub_resolution.run()` startup.

### `src/core/search/postprocess.py:apply_citation_boost`

Normalize with `r.get("citation_count") or 0` and `r.get("pagerank") or 0` at every numeric-field read. Also fixed `retrieval = r.get("reranker_score") or r.get("score") or 0` — previously the `.get("score", 0)` at the end could return None from a None-scored candidate.

### `src/core/search/research.py`

Same pattern applied at three locations: `max_citations`, `max_pagerank`, `max_search_score`, `relevance_score`, `citation_count`, `pagerank`. Wrap every payload numeric read with `... or 0` before arithmetic.

### `tests/core/search/test_none_safe_ranking.py`

Three new tests directly reproduce the incident's data shapes:
- `test_apply_citation_boost_handles_none_citation_count` — paper with `citation_count=None` doesn't crash
- `test_apply_citation_boost_handles_none_score` — paper with `score=None` doesn't crash
- `test_apply_citation_boost_all_none_does_not_crash` — extreme case: every numeric is None → score degrades to 0 not TypeError

**103/103 unit tests pass** after fix.

## Test gap analysis

The unit tests for search/postprocess only exercised **complete payloads** — every fixture had `score`, `citation_count`, `pagerank` set to real numbers. No test covered `None` values, so both `math.log(1 + None)` and `None / n` were unreachable.

The unit tests for storage-query methods used mock storage that didn't distinguish "unindexed" from "indexed" fields — every scroll was O(1) dict lookup. So no test failed on the `source_id` scroll pattern; only production scale (3.6M points) exposed the 60s timeout.

Both gaps generalize: **any test that runs against a mock or against a full-payload fixture is not a substitute for adversarial input at scale**. The next audit item (see `docs/refactoring/2026-06-24-ponytail-audit.md`) is a startup-check that scans call sites for `Filter(must=[FieldCondition(key=X, ...)])` patterns where `X` isn't in the target collection's `payload_schema`.

## Follow-up bugs discovered after State-1 fix

The other Claude session reported two more bugs after reconnecting MCP to the
patched server. Both were latent — same root cause class as the first two.

### Bug 3 — `sequence item 0: expected str instance, dict found` (search_papers + research_topic)

`src/mcp/formatters.py` did `", ".join(authors[:3])` at line 33 and
`", ".join(authors)` at line 95, both assuming `authors` is a list of
strings. **P2 promotion writes OpenAlex `authorships` payload** — a list
of dicts like `{"display_name": "A. Vaswani", "orcid": "..."}` or the
nested `{"author": {"display_name": ...}, "position": "middle"}` shape.
The old crawler wrote plain strings; the formatter never learned about
the new shape.

Fix: `_author_name(a)` helper that accepts str, dict-with-display_name,
or nested-authorship dict and returns a display string. Both `join()`
sites now use `[n for n in (_author_name(a) for a in authors) if n]`
so empty-name entries are filtered out. 8 regression tests in
`tests/mcp/test_formatters_dict_authors.py` pin every author shape.

### Bug 4 — `get_paper` "Paper not found" for canonical arXiv IDs (e.g. 1706.03762 "Attention Is All You Need")

The Attention paper exists in the corpus **only as a stub**, keyed by DOI
`10.48550/arxiv.1706.03762`. `arxiv_id` and `title` are both None on the
stub because P2 hasn't promoted it (either the snapshot's match key didn't
line up, or the paper's OpenAlex work was skipped). The MCP `get_paper`
handler tried UUID → DOI-scroll → arxiv-id scroll but never tried the
canonical `10.48550/arxiv.<id>` DOI variant for arXiv-shaped identifiers.

Fix: when the identifier matches the arXiv-ID regex (`^\d{4}\.\d{4,5}(v\d+)?$`),
also probe `10.48550/arxiv.<bare>` and `10.48550/arXiv.<bare>` variants
(snapshot corpus mixes both casings). Also added `_looks_like_uuid()` guard
before the direct UUID retrieve so a non-UUID identifier doesn't cause a
noisy 400-error round-trip to Qdrant.

## Action items

| # | Item | Status |
|---|---|---|
| 1 | Query indexed `arxiv_id` field first in `get_paper_by_arxiv_id` | ✅ This commit |
| 2 | Add `source_id` to `ensure_identifier_indices()` | ✅ This commit |
| 3 | Normalize `None` → 0 in `postprocess.apply_citation_boost` | ✅ This commit |
| 4 | Normalize `None` → 0 in `research.research_topic` scoring | ✅ This commit |
| 5 | Add regression tests for None-safe ranking | ✅ This commit |
| 6 | Postmortem doc in `docs/incidents/` + index in `docs/README.md` | ✅ This commit |
| 7 | Startup-check linter for unindexed payload-field filters (audit item #21) | ⏳ Post-bootstrap polish wave |
| 8 | Ollama-side fix for `get_corpus_stats` returning 1.6MB (top-N venue limit) | ⏳ Post-bootstrap polish wave |

## Lessons learned

1. **`dict.get(k, default)` is dangerous with untrusted numeric payloads.** The default is applied only when the key is missing. When the value is explicitly `None`, `.get` returns None — not the default. Every numeric read from an external payload needs `... or 0` (or `or 0.0`). Consider a strict-typed wrapper that raises on None instead of silently propagating.

2. **P2's write patterns changed the payload shape.** Every downstream consumer that had assumed "citation_count is always an int, never None" was silently wrong for months — the invariant just happened to hold because no code path was writing None. Bootstraps that mutate the payload surface should trigger a **downstream contract review**: search, ranking, MCP formatters, analytics — anything that reads from Qdrant needs to accept the new data shape.

3. **Wrong-field queries have the same symptom as slow-field queries.** Bug 1 looked like a "scroll is slow" bug — same class as the 2026-06-29 P2 incident. But the actual issue was we were querying the wrong field entirely. The correct field (`arxiv_id`) was already indexed. Bug fix ≠ Bug root cause; asking "should this be querying this field at all?" catches a subclass the "add an index" fix would have papered over.

4. **Silent 60s waits corrupt downstream reasoning.** The other Claude session spent hours trying to use LexiconArxiv, hit 60s waits per query, and eventually gave up and used WebSearch instead. Even after the operator escalated, they were still uncertain whether MCP was "down". A **timeout budget** at the MCP handler level (e.g., 5s max per lookup) would surface the failure fast instead of hanging.

5. **Two independent bugs surfacing at the same time is not a coincidence.** Both were exposed by the same trigger (P2 promotion). When a bootstrap mutates data at scale, expect a *cluster* of latent bugs to fire together — not just one. Triage in parallel, not serially.

## References

- Preceding incidents in this bootstrap:
  - [`2026-06-29-p2-missing-payload-indices.md`](2026-06-29-p2-missing-payload-indices.md) — Bug 1 shares root class
  - [`2026-06-30-embed-queue-data-loss.md`](2026-06-30-embed-queue-data-loss.md)
- Code fix: this commit
- Audit reference: [`docs/refactoring/2026-06-24-ponytail-audit.md`](../refactoring/2026-06-24-ponytail-audit.md) item #21
- Regression tests: `tests/core/search/test_none_safe_ranking.py`
