# Phase 3: MCP Server — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose LexiconArxiv search as MCP tools so Claude and other AI agents can query the corpus directly.

**Architecture:** Thin MCP transport wrapper over the existing SearchService and QdrantStorage. No logic duplication — MCP tool handlers call the same service methods used by the REST API. Returns pre-formatted, LLM-friendly text.

**Tech Stack:** `mcp` Python SDK (stdio transport), existing SearchService, QdrantStorage

**Spec:** `docs/specs/2026-03-18-search-engine-mvp-design.md` — Section 5

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/mcp/__init__.py` | Package init |
| Create | `src/mcp/server.py` | MCP server with tool handlers |
| Create | `src/mcp/formatters.py` | Format search results as LLM-friendly text |
| Create | `tests/test_mcp_formatters.py` | Unit tests for formatters |

---

## Task 1: Add `mcp` dependency

- [ ] **Step 1:** Run `uv add mcp`
- [ ] **Step 2:** Commit: `git add pyproject.toml uv.lock && git commit -m "deps: add mcp Python SDK"`

---

## Task 2: Create LLM-friendly result formatters

**Files:**
- Create: `src/mcp/__init__.py`
- Create: `src/mcp/formatters.py`
- Create: `tests/test_mcp_formatters.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mcp_formatters.py
from src.mcp.formatters import format_search_results, format_paper_detail


class TestFormatSearchResults:
    def test_formats_results_as_text(self):
        results = {
            "results": [
                {
                    "title": "Attention Is All You Need",
                    "authors": ["Vaswani et al."],
                    "venue": "NeurIPS 2017",
                    "tier": 0,
                    "citation_count": 50000,
                    "keywords": ["transformer", "attention"],
                    "score": 0.95,
                },
            ],
            "total": 1,
            "query_time_ms": 50,
            "search_mode": "hybrid",
        }
        text = format_search_results(results)
        assert "Attention Is All You Need" in text
        assert "Vaswani et al." in text
        assert "NeurIPS 2017" in text
        assert "Tier 0" in text
        assert "50,000 citations" in text
        assert "hybrid" in text.lower()

    def test_formats_empty_results(self):
        results = {"results": [], "total": 0, "query_time_ms": 10, "search_mode": "hybrid"}
        text = format_search_results(results)
        assert "No results" in text


class TestFormatPaperDetail:
    def test_formats_paper_as_text(self):
        paper = {
            "title": "BERT",
            "authors": ["Devlin et al."],
            "venue": "NAACL 2019",
            "year": 2019,
            "abstract": "We introduce BERT...",
            "citation_count": 40000,
            "keywords": ["BERT", "pretraining"],
            "reference_count": 50,
            "cited_by_count": 200,
        }
        text = format_paper_detail(paper)
        assert "BERT" in text
        assert "NAACL 2019" in text
        assert "40,000" in text
```

- [ ] **Step 2: Implement formatters**

```python
# src/mcp/formatters.py
"""Format search results as LLM-friendly text."""


def format_search_results(results: dict, max_results: int = 10) -> str:
    """Format search results as concise text for LLM consumption."""
    items = results.get("results", [])
    total = results.get("total", 0)
    time_ms = results.get("query_time_ms", 0)
    mode = results.get("search_mode", "unknown")

    if not items:
        return f"No results found. (Search mode: {mode}, {time_ms}ms)"

    lines = [f"Found {len(items)} results ({total:,} total, {mode}, {time_ms}ms):\n"]

    for i, r in enumerate(items[:max_results], 1):
        authors = ", ".join(r.get("authors", [])[:3])
        if len(r.get("authors", [])) > 3:
            authors += " et al."
        venue = r.get("venue", "Unknown venue")
        tier = f"Tier {r.get('tier')}" if r.get("tier") is not None else ""
        citations = f"{r.get('citation_count', 0):,} citations"
        keywords = ", ".join(r.get("keywords", [])[:5])
        score = r.get("score", 0)

        lines.append(f'{i}. "{r.get("title", "Untitled")}"')
        lines.append(f"   {authors} · {venue} · {tier} · {citations}")
        if keywords:
            lines.append(f"   Keywords: {keywords}")
        lines.append(f"   Score: {score:.2f}")
        if r.get("doi"):
            lines.append(f"   DOI: {r['doi']}")
        if r.get("code_url"):
            lines.append(f"   Code: {r['code_url']}")
        lines.append("")

    return "\n".join(lines)


def format_paper_detail(paper: dict) -> str:
    """Format a single paper as detailed text."""
    lines = []
    lines.append(f"# {paper.get('title', 'Untitled')}\n")

    authors = ", ".join(paper.get("authors", []))
    if authors:
        lines.append(f"**Authors:** {authors}")

    venue = paper.get("venue", "")
    year = paper.get("year", "")
    if venue:
        lines.append(f"**Venue:** {venue} ({year})")

    citations = paper.get("citation_count", 0)
    lines.append(f"**Citations:** {citations:,}")
    lines.append(f"**References:** {paper.get('reference_count', 0)} | **Cited by:** {paper.get('cited_by_count', 0)}")

    if paper.get("doi"):
        lines.append(f"**DOI:** {paper['doi']}")
    if paper.get("arxiv_id"):
        lines.append(f"**arXiv:** {paper['arxiv_id']}")

    keywords = paper.get("keywords", [])
    if keywords:
        lines.append(f"**Keywords:** {', '.join(keywords)}")

    if paper.get("code_url"):
        lines.append(f"**Code:** {paper['code_url']}")
    if paper.get("pdf_url"):
        lines.append(f"**PDF:** {paper['pdf_url']}")

    abstract = paper.get("abstract", "")
    if abstract:
        lines.append(f"\n**Abstract:**\n{abstract}")

    return "\n".join(lines)
```

- [ ] **Step 3: Run tests and commit**

```bash
uv run pytest tests/test_mcp_formatters.py -v
git add src/mcp/ tests/test_mcp_formatters.py
git commit -m "feat: add LLM-friendly search result formatters for MCP"
```

---

## Task 3: Create MCP server

**Files:**
- Create: `src/mcp/server.py`

- [ ] **Step 1: Implement MCP server**

```python
# src/mcp/server.py
"""MCP server exposing LexiconArxiv search tools."""

import asyncio
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from src.core.search.service import SearchService
from src.core.storage.base import QdrantStorage
from src.mcp.formatters import format_search_results, format_paper_detail

logger = logging.getLogger(__name__)

app = Server("lexiconarxiv")


# Global service instances (initialized in main)
_search_service: SearchService | None = None
_storage: QdrantStorage | None = None


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_papers",
            description="Search AI/ML/NLP research papers using hybrid semantic + keyword search. Returns ranked results from top-tier venues (NeurIPS, ICML, ICLR, ACL, EMNLP, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "venues": {"type": "array", "items": {"type": "string"}, "description": "Filter by venue names (e.g., ['ACL', 'EMNLP'])"},
                    "year_min": {"type": "integer", "description": "Minimum publication year"},
                    "year_max": {"type": "integer", "description": "Maximum publication year"},
                    "tiers": {"type": "array", "items": {"type": "integer"}, "description": "Filter by venue tiers (0=top, 1=strong, 2=niche)"},
                    "limit": {"type": "integer", "description": "Max results to return (default: 10)", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_paper",
            description="Get full details of a specific paper by its ID, DOI, or arXiv ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "Paper ID (UUID), DOI, or arXiv ID"},
                },
                "required": ["identifier"],
            },
        ),
        Tool(
            name="get_citations",
            description="Get papers that cite or are cited by a given paper.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string", "description": "Paper ID (UUID)"},
                    "direction": {"type": "string", "enum": ["refs", "cited_by", "both"], "description": "Direction: refs (papers this cites), cited_by (papers citing this), both", "default": "both"},
                    "limit": {"type": "integer", "description": "Max results per direction (default: 10)", "default": 10},
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="get_corpus_stats",
            description="Get statistics about the LexiconArxiv corpus (total papers, venues, coverage).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "search_papers":
        return await _handle_search(arguments)
    elif name == "get_paper":
        return await _handle_get_paper(arguments)
    elif name == "get_citations":
        return await _handle_get_citations(arguments)
    elif name == "get_corpus_stats":
        return await _handle_corpus_stats(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _handle_search(args: dict) -> list[TextContent]:
    results = await _search_service.search(
        query=args["query"],
        venues=args.get("venues"),
        year_min=args.get("year_min"),
        year_max=args.get("year_max"),
        tiers=args.get("tiers"),
        limit=args.get("limit", 10),
    )
    text = format_search_results(results, max_results=args.get("limit", 10))
    return [TextContent(type="text", text=text)]


async def _handle_get_paper(args: dict) -> list[TextContent]:
    identifier = args["identifier"]

    # Try direct ID first
    paper = await _search_service.get_paper(identifier)

    # Try DOI lookup
    if paper is None and "/" in identifier:
        result = _storage.queries.get_paper_by_doi(identifier)
        if result:
            paper = await _search_service.get_paper(result[0] if isinstance(result, tuple) else str(result))

    # Try arXiv ID lookup
    if paper is None and identifier.replace(".", "").replace("/", "").replace(":", "").isalnum():
        result = _storage.queries.get_paper_by_arxiv_id(identifier)
        if result:
            point_id, _ = result
            paper = await _search_service.get_paper(point_id)

    if paper is None:
        return [TextContent(type="text", text=f"Paper not found: {identifier}")]

    text = format_paper_detail(paper)
    return [TextContent(type="text", text=text)]


async def _handle_get_citations(args: dict) -> list[TextContent]:
    paper_id = args["paper_id"]
    direction = args.get("direction", "both")
    limit = args.get("limit", 10)

    paper = await _search_service.get_paper(paper_id)
    if paper is None:
        return [TextContent(type="text", text=f"Paper not found: {paper_id}")]

    lines = [f'Citations for "{paper["title"]}":\n']

    # Get references (papers this paper cites)
    if direction in ("refs", "both"):
        try:
            point = _storage.client.retrieve(
                _storage.collection_name,
                ids=[paper_id],
                with_payload=["resolved_references"],
            )
            ref_ids = point[0].payload.get("resolved_references", []) if point else []
            if ref_ids:
                lines.append(f"**References** ({len(ref_ids)} total, showing {min(limit, len(ref_ids))}):")
                for ref_id in ref_ids[:limit]:
                    ref = await _search_service.get_paper(ref_id)
                    if ref:
                        lines.append(f"  - {ref['title']} ({ref.get('venue', 'Unknown')}, {ref.get('year', '?')})")
                lines.append("")
            else:
                lines.append("**References:** None resolved\n")
        except Exception:
            lines.append("**References:** Error fetching\n")

    # Get cited_by (papers that cite this paper)
    if direction in ("cited_by", "both"):
        try:
            point = _storage.client.retrieve(
                _storage.collection_name,
                ids=[paper_id],
                with_payload=["cited_by"],
            )
            cited_by_ids = point[0].payload.get("cited_by", []) if point else []
            if cited_by_ids:
                lines.append(f"**Cited by** ({len(cited_by_ids)} total, showing {min(limit, len(cited_by_ids))}):")
                for cb_id in cited_by_ids[:limit]:
                    cb = await _search_service.get_paper(cb_id)
                    if cb:
                        lines.append(f"  - {cb['title']} ({cb.get('venue', 'Unknown')}, {cb.get('year', '?')})")
                lines.append("")
            else:
                lines.append("**Cited by:** None in corpus\n")
        except Exception:
            lines.append("**Cited by:** Error fetching\n")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_corpus_stats(args: dict) -> list[TextContent]:
    from qdrant_client import models

    total = _storage.client.count(_storage.collection_name).count
    stubs = _storage.client.count(
        _storage.collection_name,
        count_filter=models.Filter(must=[
            models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))
        ]),
    ).count
    real = total - stubs

    lines = [
        "# LexiconArxiv Corpus Statistics\n",
        f"**Total points:** {total:,}",
        f"**Core papers:** {real:,}",
        f"**Stub papers:** {stubs:,} (external references)",
    ]

    return [TextContent(type="text", text="\n".join(lines))]


async def main():
    global _search_service, _storage

    _storage = QdrantStorage()
    _search_service = SearchService(storage=_storage)
    await _search_service.__aenter__()

    logger.info("LexiconArxiv MCP server starting...")

    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    finally:
        await _search_service.__aexit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `uv run python -c "from src.mcp.server import app; print('MCP server imports OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/mcp/server.py
git commit -m "feat: add MCP server with search_papers, get_paper, get_citations, get_corpus_stats tools"
```

---

## Execution Checklist

| Task | Description | Estimated Time |
|------|-------------|---------------|
| 1 | Add mcp dependency | 2 min |
| 2 | Result formatters + tests | 10 min |
| 3 | MCP server | 10 min |

**After implementation:**
- Run: `uv run python -m src.mcp.server` (starts stdio MCP server)
- Configure in Claude Code: add to `.claude/settings.json` or `claude_desktop_config.json`
