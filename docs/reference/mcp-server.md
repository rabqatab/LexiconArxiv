# MCP Server Reference

**Location:** `src/mcp/server.py` (dispatch + tool registration), `src/mcp/formatters.py` (pure renderers).
**Protocol:** [Model Context Protocol](https://modelcontextprotocol.io) stdio transport.
**Purpose:** Expose the LexiconArxiv corpus to AI-agent callers (Claude Code sessions, other MCP-aware clients) as a set of typed tools over its search, paper-detail, and citation-graph surfaces.

---

## Runtime lifecycle

MCP servers run as **per-Claude-session subprocesses** with **no hot reload**. When a new commit lands, existing subprocesses keep running the old code until the client explicitly reconnects (`/mcp reconnect lexiconarxiv` in Claude Code). This has caused enough cross-session confusion that the server now advertises its build identity — see [Version identity](#version-identity--stale-subprocess-detection) below.

### Startup

`main()` in `src/mcp/server.py`:

1. Captures `_VERSION = {sha, startup_ts, python}` at **import time** (frozen for the process lifetime).
2. Logs `MCP server starting: sha=<short-sha> startup=<iso-utc> python=<version>`.
3. Initializes `QdrantStorage` and `SearchService` (async context — `SearchService.__aenter__` warms Ollama).
4. Serves `stdio_server()` until stdin closes.

Failures during (3) surface as `ConnectionError` at the transport layer; the client sees the tool call fail with an error message.

---

## Tools

Eleven tools registered as of 2026-07-19 (eight core + three external-integration tools). Every tool goes through the `_dispatch(name, arguments)` gate, which applies a **timeout budget** (see [Handler timeouts](#handler-timeouts) below) and a top-level exception catcher.

| Tool | Purpose | Timeout budget | Handler |
|------|---------|----------------|---------|
| `search_papers` | Hybrid dense+BM25 search with filters (venue, year, tier, section) | 5s | `_handle_search_papers` |
| `get_paper` | Fetch one paper by any of: UUID / DOI / arXiv ID / `arxiv:`-prefixed DOI variant | 5s | `_handle_get_paper` |
| `get_citations` | References + cited-by for a paper | 5s | `_handle_get_citations` |
| `get_similar_papers` | Typed similarity edges (same_method / same_task / same_result / method_transfer / overall) | 5s | `_handle_get_similar_papers` |
| `get_corpus_stats` | Total-points + top-N venues with long-tail summary | 60s (perf ticket) | `_handle_get_corpus_stats` |
| `expand_search` | Live arXiv + OpenAlex expansion for on-demand papers | 20s | `_handle_expand_search` |
| `research_topic` | Full research overview: notable papers + trends + summary | 15s | `_handle_research_topic` |
| `get_mcp_version` | Return `{sha, startup_ts, python}` — for stale-subprocess detection | 5s | `_handle_get_mcp_version` |
| `dblp_search` | Structured DBLP author/venue/title search (no key) | 20s | `_handle_dblp_search` |
| `get_open_citations` | Open citation count + citing DOIs for a DOI (OpenCitations) | 25s | `_handle_get_open_citations` |
| `core_fulltext_search` | Full-text OA search over 200M+ papers (CORE; needs `CORE_API_KEY`) | 25s | `_handle_core_fulltext_search` |

### `search_papers`

Inputs: `query` (str, required), optional `venues: list[str]`, `year_min: int`, `year_max: int`, `tiers: list[int]`, `section: str` (task/method/…), `limit: int` (default 20, capped at 50).

Section filtering routes the retrieval to the corresponding section-level vector (`section-method`, `section-task`, …) instead of `structured-abstract`, giving section-specific ranking.

Response shape: numbered markdown list of results — see `src/mcp/formatters.py:format_search_results`.

### `get_paper`

Input: `paper_id` (str, required).

Resolution order — first hit wins:

1. If input matches UUID regex → `SearchService.get_paper()` (direct point retrieve).
2. If input matches arXiv-ID regex `^\d{4}\.\d{4,5}(v\d+)?$` → probe DOI variants `10.48550/arxiv.<id>` **and** `10.48550/arXiv.<id>` (P2 snapshot mixes both casings).
3. Otherwise treat as DOI and scroll on the indexed `doi` field.
4. Fall through to `arxiv_id` field (indexed via `ensure_identifier_indices()`) — raw and `arXiv:`-prefixed formats.

The multi-path lookup was hardened after the 2026-07-03 incident when the Attention paper (`1706.03762`) was reported as "not found" — it existed as a stub keyed by DOI variant.

### `get_corpus_stats`

Inputs: `top_venues: int` (default 30, hard-capped at 200).

Response is bounded: previously dumped every one of thousands of unique venues (1.6MB / 38K lines). Now shows the top-N + a `_…and <M> more venues covering <K> papers._` summary line so callers still see the long-tail shape.

Storage-layer `get_venue_stats()` still full-scrolls the collection (~30–60s at 3.6M points). That's the 60s timeout budget in the table above; it also motivates the deferred perf ticket in the ponytail audit (histogram cache).

### `get_mcp_version`

Inputs: none.

Returns `_VERSION` (frozen at import time). Compare the reported `git sha` against `git rev-parse --short HEAD` on disk — mismatch means the MCP subprocess is stale and needs `/mcp reconnect lexiconarxiv`.

Example response:

```markdown
# MCP Server Version

- **git sha:** `25a262a`
- **startup:** 2026-07-03T10:33:00+00:00
- **python:** 3.12.3

_If this SHA is older than `git rev-parse HEAD` on disk, the server is stale
— reconnect the MCP to pick up recent commits._
```

Falls back gracefully to `sha="unknown"` when git isn't on PATH (wheel-installed server, sandboxed environment) — the other fields still populate.

---

## Handler timeouts

Every handler runs under `asyncio.wait_for` with a strict budget. The default catches unindexed-scroll bugs like the 2026-07-03 `source_id` 60s hang before they burn the caller's turn. Known-slow handlers have explicit overrides.

```python
# src/mcp/server.py (constants)
_DEFAULT_HANDLER_TIMEOUT_SEC: float = 5.0
_HANDLER_TIMEOUTS: dict[str, float] = {
    "research_topic":    15.0,  # semantic rerank + trend analysis
    "expand_search":     20.0,  # external arxiv + openalex roundtrips
    "get_corpus_stats":  60.0,  # ponytail: get_venue_stats() full-scrolls
                                # 3.6M points; drop when histogram is cached
}
```

**On timeout**, the response is a text error:

```
Error: '<tool>' exceeded its <N>s time budget. This typically means the
query hits an unindexed payload field or a stalled backend. Try narrower
filters, or file a bug if this keeps happening.
```

This is deliberately diagnostic — future-us or another Claude session should be able to guess the failure mode without reading the source.

**Sanity guardrail** (locked in by `tests/mcp/test_dispatch_timeout.py::test_slow_handler_overrides_are_sane`): no override may be *tighter* than the default. A typo like `60.0 → 6.0` in the overrides table would tighten `get_corpus_stats` and break the assertion at test time.

### When to bump a timeout

- Handler *legitimately* needs more time (external API, rerank pass) → add an entry to `_HANDLER_TIMEOUTS`.
- Handler is hitting an unindexed field or hanging backend → **do not** bump the timeout. Fix the underlying cause: add the index, or add a warning-log at storage layer.

---

## Version identity & stale-subprocess detection

**The problem.** MCP subprocesses have no hot reload. If session A commits a fix and session B is still running an old subprocess, session B keeps hitting the old bug. Session B has no built-in way to notice.

**The protocol.**

1. Session B suspects staleness (a tool still fails after a fix landed).
2. Session B calls `get_mcp_version` → gets running SHA.
3. Session B shells out `git rev-parse --short HEAD` → gets on-disk SHA.
4. If they differ, session B reconnects (`/mcp reconnect lexiconarxiv`) and re-tries.

Cross-session Claude Code sessions can co-ordinate this manually. Nothing automatic yet; a future improvement could have the server ping stdout with the SHA on every response header — but that's a protocol change and out of scope for this doc.

---

## Formatter contract

Every response is `list[TextContent(type="text", text=<markdown>)]`. Formatters are pure functions in `src/mcp/formatters.py`:

- `format_search_results(results, max_results=10)` — numbered list with title, authors (first 3 + `et al.`), venue, year, tier, citations, keywords, score, id.
- `format_paper_detail(paper)` — full markdown page: identifiers, authors, venue, tier, metrics, flags, abstract, structured abstract, keywords, code repos, PDF URL.
- `format_research_results(data)` — Key Papers / Trends / Summary sections.
- `format_corpus_stats(*, total, real, stubs, venue_stats, top_venues=30)` — see [`get_corpus_stats`](#get_corpus_stats) above.

**Author-shape adapter.** `_author_name(a)` handles str / dict-with-`display_name` / nested-OpenAlex-authorship shapes. P2 stub promotion writes the OpenAlex `authorships` dict list; older crawler paths wrote plain strings. See [ponytail audit item #22](../refactoring/2026-06-24-ponytail-audit.md) for the deferred plan to move this normalization to the storage read boundary so formatters can go back to assuming `list[str]`.

---

## Testing

`tests/mcp/` — 29 tests across three files:

| File | Tests | What it locks in |
|------|-------|------------------|
| `test_formatters_dict_authors.py` | 9 | Author-shape handling across all three formatters — pins the 2026-07-03 State-4 incident |
| `test_format_corpus_stats.py` | 7 | Response-size bound (<10KB for 5000 venues), top-N cap, long-tail footer, thousands separators |
| `test_dispatch_timeout.py` | 7 | Budget respected, per-handler overrides, unknown-tool handling, exception passthrough, registration completeness, sanity guardrail |
| `test_version.py` | 6 | Real SHA resolution, missing-git fallback, cache-at-import invariant, handler + dispatch end-to-end |

**Import-shadowing gotcha.** `tests/mcp/` intentionally has **no** `__init__.py` (it was removed in commit `253afcf`). If a future contributor adds one back, `from src.mcp.server import …` will crash at collect time because pytest inserts `tests/mcp/` on `sys.path` and shadows the real `mcp` SDK package. If tests suddenly stop collecting with `ModuleNotFoundError: No module named 'mcp.server'`, that's the cause — delete the file.

---

## Related documents

- [Incident postmortem 2026-07-03](../incidents/2026-07-03-mcp-search-endpoints-broken.md) — the four bugs and the follow-up hardening wave that produced this reference
- [Ponytail audit 2026-06-24](../refactoring/2026-06-24-ponytail-audit.md) — items #22 (author boundary) and #23 (unindexed-field linter) tracked here
- [Architecture: API](../architecture/api.md) §10 MCP Tools — protocol-level tool schema
