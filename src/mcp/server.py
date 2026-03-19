"""MCP server for LexiconArxiv — exposes search and paper tools for AI agents."""

import asyncio
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from qdrant_client.http import models as qdrant_models

from src.core.search.service import SearchService
from src.core.storage.base import QdrantStorage
from src.mcp.formatters import format_paper_detail, format_search_results

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
            name="get_corpus_stats",
            description=(
                "Get summary statistics about the LexiconArxiv corpus: total papers, "
                "venue breakdown, and data quality metrics."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "search_papers":
            return await _handle_search_papers(arguments)
        elif name == "get_paper":
            return await _handle_get_paper(arguments)
        elif name == "get_citations":
            return await _handle_get_citations(arguments)
        elif name == "get_corpus_stats":
            return await _handle_get_corpus_stats(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=f"Error: {e}")]


async def _handle_search_papers(arguments: dict) -> list[TextContent]:
    service = _get_service()
    query = arguments["query"]
    venues = arguments.get("venues")
    year_min = arguments.get("year_min")
    year_max = arguments.get("year_max")
    tiers = arguments.get("tiers")
    limit = min(arguments.get("limit", 20), 50)

    results = await service.search(
        query=query,
        venues=venues,
        year_min=year_min,
        year_max=year_max,
        tiers=tiers,
        limit=limit,
    )

    text = format_search_results(results, max_results=limit)
    return [TextContent(type="text", text=text)]


async def _handle_get_paper(arguments: dict) -> list[TextContent]:
    service = _get_service()
    storage = _get_storage()
    identifier = arguments["identifier"]

    # Try 1: Direct UUID lookup via SearchService
    paper = await service.get_paper(identifier)
    if paper:
        return [TextContent(type="text", text=format_paper_detail(paper))]

    # Try 2: DOI lookup
    # get_paper_by_doi returns payload only (no point ID), so we scroll
    # with the DOI filter to retrieve the point ID for a full detail lookup.
    doi_results = storage.client.scroll(
        collection_name=storage.collection_name,
        scroll_filter=qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="doi",
                    match=qdrant_models.MatchValue(value=identifier),
                )
            ]
        ),
        limit=1,
    )
    doi_points = doi_results[0]
    if doi_points:
        point_id = str(doi_points[0].id)
        paper = await service.get_paper(point_id)
        if paper:
            return [TextContent(type="text", text=format_paper_detail(paper))]
        # Fallback: format the raw payload directly
        detail = dict(doi_points[0].payload or {})
        detail.setdefault("id", point_id)
        return [TextContent(type="text", text=format_paper_detail(detail))]

    # Try 3: arXiv ID lookup
    arxiv_result = storage.queries.get_paper_by_arxiv_id(identifier)
    if arxiv_result is not None:
        point_id, _payload = arxiv_result
        paper = await service.get_paper(point_id)
        if paper:
            return [TextContent(type="text", text=format_paper_detail(paper))]

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


async def _handle_get_corpus_stats(arguments: dict) -> list[TextContent]:
    storage = _get_storage()

    total = storage.count_papers()
    real = storage.count_real_papers()
    stubs = storage.count_stubs()
    venue_stats = storage.get_venue_stats()

    lines = [
        "# LexiconArxiv Corpus Statistics\n",
        f"**Total points:** {total}",
        f"**Real papers:** {real}",
        f"**Stub papers:** {stubs}",
        "",
        "## Papers by Venue\n",
    ]

    # Sort venues by count descending
    for venue, count in sorted(venue_stats.items(), key=lambda x: -x[1]):
        lines.append(f"- {venue}: {count}")

    lines.append("")

    return [TextContent(type="text", text="\n".join(lines))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    global _search_service, _storage

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
