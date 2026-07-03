"""MCP server for LexiconArxiv — exposes search and paper tools for AI agents."""

import asyncio
import logging
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from qdrant_client.http import models as qdrant_models

from src.core.search.service import SearchService
from src.core.storage.base import QdrantStorage
from src.core.search.research import research_topic
from src.mcp.formatters import (
    format_corpus_stats,
    format_paper_detail,
    format_research_results,
    format_search_results,
)


def _resolve_mcp_version() -> dict[str, str]:
    """Version fingerprint frozen at import time.

    MCP servers are per-Claude-session subprocesses with no hot-reload. When
    session A commits a fix and session B still holds an old subprocess, the
    only way session B can tell is by comparing this SHA against `git rev-parse
    HEAD` on disk. Capturing at import (not per-call) makes the answer honest.
    """
    repo = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo,
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip() or "unknown"
    except Exception:
        sha = "unknown"
    return {
        "sha": sha,
        "startup_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
    }


_VERSION: dict[str, str] = _resolve_mcp_version()

logger = logging.getLogger(__name__)

app = Server("lexiconarxiv")

# Module-level references; initialized in main().
_search_service: SearchService | None = None
_storage: QdrantStorage | None = None


def _get_service() -> SearchService:
    assert _search_service is not None, "SearchService not initialized"
    return _search_service


def _get_storage() -> QdrantStorage:
    assert _storage is not None, "QdrantStorage not initialized"
    return _storage


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_papers",
            description=(
                "Search the LexiconArxiv corpus for academic papers using hybrid "
                "retrieval (dense embedding + BM25). Supports filtering by venue, "
                "year range, and tier."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query",
                    },
                    "venues": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by venue names (e.g. ['NeurIPS', 'ICML'])",
                    },
                    "year_min": {
                        "type": "integer",
                        "description": "Minimum publication year (inclusive)",
                    },
                    "year_max": {
                        "type": "integer",
                        "description": "Maximum publication year (inclusive)",
                    },
                    "section": {
                        "type": "string",
                        "enum": ["task", "method", "result", "approach", "background", "domain", "contribution"],
                        "description": "Target a specific paper section for more precise matching (e.g. 'method' to find papers that USE a technique, 'result' for papers that ACHIEVE something)",
                    },
                    "tiers": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Filter by tier levels (0=top, 1=high, 2=mid)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 20, max 50)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_paper",
            description=(
                "Get full details for a paper by its identifier. Accepts a Qdrant "
                "point UUID, a DOI, or an arXiv ID. The identifier is tried in that "
                "order until a match is found."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": (
                            "Paper identifier: UUID, DOI (e.g. '10.1234/...'), "
                            "or arXiv ID (e.g. '2303.08774')"
                        ),
                    },
                },
                "required": ["identifier"],
            },
        ),
        Tool(
            name="get_citations",
            description=(
                "Get citation relationships for a paper. Returns the papers this "
                "paper references, the papers that cite it, or both."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {
                        "type": "string",
                        "description": "Qdrant point UUID of the paper",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["refs", "cited_by", "both"],
                        "description": "Which direction: 'refs' (outgoing), 'cited_by' (incoming), 'both'",
                        "default": "both",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max papers to return per direction (default 20)",
                        "default": 20,
                    },
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="get_mcp_version",
            description=(
                "Return the running MCP server's git SHA, startup timestamp, "
                "and Python version. Use this to diagnose stale MCP subprocesses "
                "across Claude Code sessions — if a fix was committed but the "
                "reported SHA is older than `git rev-parse HEAD`, this server "
                "needs a restart (`/mcp reconnect lexiconarxiv`)."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_corpus_stats",
            description=(
                "Get summary statistics about the LexiconArxiv corpus: total papers, "
                "distinct-venue count, and the top-N venues by paper count with a "
                "long-tail summary. Response is bounded — the corpus has thousands "
                "of unique venues, so full dumps used to blow past 1MB."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "top_venues": {
                        "type": "integer",
                        "description": (
                            "Number of top venues to list by paper count "
                            "(default 30, hard-capped at 200)."
                        ),
                        "default": 30,
                    },
                },
            },
        ),
        Tool(
            name="get_similar_papers",
            description=(
                "Get precomputed semantically similar papers for a given paper. "
                "Returns typed similarity edges: same_method (papers using similar methods), "
                "same_task (papers addressing similar tasks), same_result (papers with similar results), "
                "method_transfer (papers whose methods relate to this paper's results), "
                "and overall (holistic similarity). Optionally filter to a single edge type."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {
                        "type": "string",
                        "description": "Qdrant point UUID of the paper",
                    },
                    "edge_type": {
                        "type": "string",
                        "enum": ["same_method", "same_task", "same_result", "method_transfer", "overall"],
                        "description": "Optional: filter to a single edge type",
                    },
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="expand_search",
            description=(
                "Expand a search query beyond the local corpus by fetching results "
                "from arXiv and/or OpenAlex. Returns external papers and indicates "
                "which ones are already in the LexiconArxiv corpus."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query",
                    },
                    "sources": {
                        "type": "string",
                        "enum": ["arxiv", "openalex", "both"],
                        "description": "Which external sources to query (default: both)",
                        "default": "both",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 20, max 50)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="research_topic",
            description=(
                "Research an academic topic: finds the most notable and relevant papers, "
                "shows trending keywords, and summarizes the research landscape. "
                "Use this when a user wants to understand a research area or find important papers to read."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Research topic or question",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of papers to return (default: 20)",
                        "default": 20,
                    },
                    "year_min": {
                        "type": "integer",
                        "description": "Minimum publication year",
                    },
                    "exclude_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Paper types to exclude: 'benchmark', 'dataset', 'survey'. "
                            "Papers whose title contains related keywords are filtered out."
                        ),
                    },
                },
                "required": ["query"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

# Fail-fast timeout budgets. The default catches the cheap-path failure
# mode (unindexed field scroll, hung Ollama) — the 2026-07-03 incident had
# get_paper_by_arxiv_id blocking for 60s on an unindexed source_id scroll.
# Known-slow handlers get explicit overrides; the table doubles as a "fix
# this" list. Values in seconds.
_DEFAULT_HANDLER_TIMEOUT_SEC: float = 5.0
_HANDLER_TIMEOUTS: dict[str, float] = {
    "research_topic": 15.0,    # semantic rerank + trend analysis
    "expand_search": 20.0,     # external arxiv + openalex roundtrips
    "get_corpus_stats": 60.0,  # ponytail: get_venue_stats() full-scrolls 3.6M points; drop when histogram is cached
}


async def _dispatch(name: str, arguments: dict) -> list[TextContent]:
    handler = _HANDLERS.get(name)
    if handler is None:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    timeout = _HANDLER_TIMEOUTS.get(name, _DEFAULT_HANDLER_TIMEOUT_SEC)
    try:
        return await asyncio.wait_for(handler(arguments), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("MCP tool %s exceeded %.1fs budget", name, timeout)
        return [TextContent(
            type="text",
            text=(
                f"Error: '{name}' exceeded its {timeout:.0f}s time budget. "
                f"This typically means the query hits an unindexed payload "
                f"field or a stalled backend. Try narrower filters, or file "
                f"a bug if this keeps happening."
            ),
        )]
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=f"Error: {e}")]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    return await _dispatch(name, arguments)


async def _handle_search_papers(arguments: dict) -> list[TextContent]:
    service = _get_service()
    query = arguments["query"]
    venues = arguments.get("venues")
    year_min = arguments.get("year_min")
    year_max = arguments.get("year_max")
    tiers = arguments.get("tiers")
    section = arguments.get("section")
    limit = min(arguments.get("limit", 20), 50)

    results = await service.search(
        query=query,
        venues=venues,
        year_min=year_min,
        year_max=year_max,
        tiers=tiers,
        section=section,
        limit=limit,
    )

    text = format_search_results(results, max_results=limit)
    return [TextContent(type="text", text=text)]


def _looks_like_arxiv_id(s: str) -> bool:
    """Heuristic: bare arXiv id like 1706.03762 or 2504.13837."""
    import re
    return bool(re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", s.strip()))


def _looks_like_uuid(s: str) -> bool:
    """Heuristic: Qdrant point ids are UUIDs. Skips the retrieve()
    400-error round-trip when the identifier is clearly not a UUID."""
    import re
    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", s.strip().lower()))


async def _handle_get_paper(arguments: dict) -> list[TextContent]:
    service = _get_service()
    storage = _get_storage()
    identifier = arguments["identifier"].strip()

    # Try 1: Direct UUID lookup via SearchService (fast, always O(1)).
    # Skip when the identifier is clearly not a UUID — otherwise Qdrant returns
    # 400 which fills the log with noise (2026-07-03 incident).
    if _looks_like_uuid(identifier):
        paper = await service.get_paper(identifier)
        if paper:
            return [TextContent(type="text", text=format_paper_detail(paper))]

    # Build candidate DOI variants to try. If identifier looks like a bare
    # arXiv id, also probe the canonical 10.48550/arxiv.<id> DOI convention —
    # many older arXiv papers exist ONLY as stubs (referenced by corpus but
    # never crawled or promoted), keyed by that DOI (2026-07-03 incident:
    # 1706.03762 "Attention Is All You Need" was such a stub).
    doi_candidates: list[str] = []
    if identifier.startswith("10.") or "/" in identifier:
        doi_candidates.append(identifier)
    if _looks_like_arxiv_id(identifier):
        # Strip version suffix for the DOI probe (arxiv DOIs never carry versions)
        bare = identifier.split("v")[0]
        # Try both casings — snapshot corpus mixes them
        doi_candidates.extend([
            f"10.48550/arxiv.{bare}",
            f"10.48550/arXiv.{bare}",
        ])

    for candidate in doi_candidates:
        doi_points, _ = storage.client.scroll(
            collection_name=storage.collection_name,
            scroll_filter=qdrant_models.Filter(
                must=[qdrant_models.FieldCondition(
                    key="doi",
                    match=qdrant_models.MatchValue(value=candidate),
                )]
            ),
            limit=1,
        )
        if doi_points:
            point_id = str(doi_points[0].id)
            paper = await service.get_paper(point_id)
            if paper:
                return [TextContent(type="text", text=format_paper_detail(paper))]
            detail = dict(doi_points[0].payload or {})
            detail.setdefault("id", point_id)
            return [TextContent(type="text", text=format_paper_detail(detail))]

    # Try 3: arXiv ID lookup (indexed arxiv_id field first, then legacy source_id fallback)
    if _looks_like_arxiv_id(identifier):
        arxiv_result = storage.queries.get_paper_by_arxiv_id(identifier)
        if arxiv_result is not None:
            point_id, payload = arxiv_result
            paper = await service.get_paper(point_id)
            if paper:
                return [TextContent(type="text", text=format_paper_detail(paper))]
            detail = dict(payload or {})
            detail.setdefault("id", point_id)
            return [TextContent(type="text", text=format_paper_detail(detail))]

    return [TextContent(type="text", text="Paper not found.")]


async def _handle_get_citations(arguments: dict) -> list[TextContent]:
    service = _get_service()
    storage = _get_storage()
    paper_id = arguments["paper_id"]
    direction = arguments.get("direction", "both")
    limit = min(arguments.get("limit", 20), 50)

    # Retrieve the paper's payload to get resolved_references and cited_by
    payload = storage.queries.get_paper_by_id(paper_id)
    if payload is None:
        return [TextContent(type="text", text=f"Paper {paper_id} not found.")]

    title = payload.get("title", "Untitled")
    lines = [f"# Citations for: {title}\n"]

    if direction in ("refs", "both"):
        resolved_refs = payload.get("resolved_references", [])
        lines.append(f"## References ({len(resolved_refs)} total)\n")
        if resolved_refs:
            for ref_id in resolved_refs[:limit]:
                ref_paper = await service.get_paper(ref_id)
                if ref_paper:
                    ref_title = ref_paper.get("title", "Untitled")
                    ref_venue = ref_paper.get("venue", "")
                    ref_year = ref_paper.get("year", "")
                    ref_cites = ref_paper.get("citation_count", 0)
                    lines.append(
                        f"- **{ref_title}** ({ref_venue} {ref_year}) "
                        f"[citations: {ref_cites}] ID: {ref_id}"
                    )
                else:
                    lines.append(f"- _{ref_id}_ (not found in corpus)")
            if len(resolved_refs) > limit:
                lines.append(f"\n... and {len(resolved_refs) - limit} more references")
        else:
            lines.append("No resolved references.")
        lines.append("")

    if direction in ("cited_by", "both"):
        cited_by = payload.get("cited_by", [])
        lines.append(f"## Cited By ({len(cited_by)} total)\n")
        if cited_by:
            for citer_id in cited_by[:limit]:
                citer_paper = await service.get_paper(citer_id)
                if citer_paper:
                    citer_title = citer_paper.get("title", "Untitled")
                    citer_venue = citer_paper.get("venue", "")
                    citer_year = citer_paper.get("year", "")
                    citer_cites = citer_paper.get("citation_count", 0)
                    lines.append(
                        f"- **{citer_title}** ({citer_venue} {citer_year}) "
                        f"[citations: {citer_cites}] ID: {citer_id}"
                    )
                else:
                    lines.append(f"- _{citer_id}_ (not found in corpus)")
            if len(cited_by) > limit:
                lines.append(f"\n... and {len(cited_by) - limit} more citing papers")
        else:
            lines.append("No citing papers found.")
        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_get_similar_papers(arguments: dict) -> list[TextContent]:
    storage = _get_storage()
    paper_id = arguments["paper_id"]
    edge_type = arguments.get("edge_type")

    points = storage.client.retrieve(
        collection_name=storage.collection_name,
        ids=[paper_id],
        with_payload=["title", "similar_papers"],
    )
    if not points:
        return [TextContent(type="text", text=f"Paper {paper_id} not found.")]

    title = points[0].payload.get("title", "Untitled")
    similar = points[0].payload.get("similar_papers", {})

    if edge_type and edge_type in similar:
        similar = {edge_type: similar[edge_type]}
    elif edge_type:
        similar = {}

    if not similar:
        return [TextContent(
            type="text",
            text=f"# Similar Papers for: {title}\n\nNo precomputed similarity edges found."
            + (" Try without edge_type filter." if edge_type else ""),
        )]

    lines = [f"# Similar Papers for: {title}\n"]

    edge_labels = {
        "same_method": "Same Method",
        "same_task": "Same Task",
        "same_result": "Same Result",
        "method_transfer": "Method Transfer",
        "overall": "Overall Similarity",
    }

    for etype, neighbors in similar.items():
        label = edge_labels.get(etype, etype)
        lines.append(f"## {label} ({len(neighbors)} papers)\n")
        for n in neighbors:
            n_title = n.get("title", "Untitled")
            n_venue = n.get("venue", "")
            n_year = n.get("year", "")
            n_score = n.get("score", 0.0)
            venue_str = f"{n_venue} {n_year}".strip() if n_venue else str(n_year)
            lines.append(
                f"- **{n_title}** ({venue_str}) "
                f"[score: {n_score}] ID: {n['id']}"
            )
        lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_get_mcp_version(arguments: dict) -> list[TextContent]:
    lines = [
        "# MCP Server Version",
        "",
        f"- **git sha:** `{_VERSION['sha']}`",
        f"- **startup:** {_VERSION['startup_ts']}",
        f"- **python:** {_VERSION['python']}",
        "",
        "_If this SHA is older than `git rev-parse HEAD` on disk, "
        "the server is stale — reconnect the MCP to pick up recent commits._",
    ]
    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_get_corpus_stats(arguments: dict) -> list[TextContent]:
    storage = _get_storage()
    top_venues = min(int(arguments.get("top_venues", 30)), 200)

    text = format_corpus_stats(
        total=storage.count_papers(),
        real=storage.count_real_papers(),
        stubs=storage.count_stubs(),
        venue_stats=storage.get_venue_stats(),
        top_venues=top_venues,
    )
    return [TextContent(type="text", text=text)]


async def _handle_expand_search(arguments: dict) -> list[TextContent]:
    service = _get_service()
    query = arguments["query"]
    sources = arguments.get("sources", "both")
    limit = min(arguments.get("limit", 20), 50)

    results = await service.expand_search(query=query, sources=sources, limit=limit)

    if "error" in results:
        return [TextContent(type="text", text=f"Error: {results['error']}")]

    expanded = results.get("expanded_results", [])
    stats = results.get("expansion_stats", {})

    lines = [f"Expanded search for '{query}' ({sources}):\n"]
    lines.append(
        f"arXiv: {stats.get('arxiv_fetched', 0)} | "
        f"OpenAlex: {stats.get('openalex_fetched', 0)} | "
        f"Connected: {stats.get('connected', 0)} | "
        f"External: {stats.get('external', 0)}\n"
    )

    for i, r in enumerate(expanded, 1):
        conn = r.get("connection", "external").upper()
        title = r.get("title", "Untitled")
        source = r.get("source", "?")
        year = r.get("year", "?")
        lines.append(f"{i}. [{conn}] {title} ({source}, {year})")
        for cp in r.get("connected_papers", []):
            lines.append(f"   -> {cp.get('relation', '?')}: {cp.get('title', '?')}")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_research_topic(arguments: dict) -> list[TextContent]:
    service = _get_service()
    storage = _get_storage()
    query = arguments["query"]
    limit = min(arguments.get("limit", 20), 50)
    year_min = arguments.get("year_min")
    exclude_types = arguments.get("exclude_types")

    result = await research_topic(
        query=query,
        search_service=service,
        storage=storage,
        limit=limit,
        year_min=year_min,
        exclude_types=exclude_types,
    )

    text = format_research_results(result)
    return [TextContent(type="text", text=text)]


# ---------------------------------------------------------------------------
# Dispatch table (must be after handler defs so name lookup finds them)
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, callable] = {
    "search_papers": _handle_search_papers,
    "get_paper": _handle_get_paper,
    "get_citations": _handle_get_citations,
    "get_corpus_stats": _handle_get_corpus_stats,
    "get_similar_papers": _handle_get_similar_papers,
    "expand_search": _handle_expand_search,
    "research_topic": _handle_research_topic,
    "get_mcp_version": _handle_get_mcp_version,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    global _search_service, _storage

    logger.info(
        "MCP server starting: sha=%s startup=%s python=%s",
        _VERSION["sha"], _VERSION["startup_ts"], _VERSION["python"],
    )

    _storage = QdrantStorage()
    _search_service = SearchService(storage=_storage)

    async with _search_service:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )


if __name__ == "__main__":
    asyncio.run(main())
