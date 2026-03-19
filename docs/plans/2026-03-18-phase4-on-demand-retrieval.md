# Phase 4: On-demand Retrieval — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** User-triggered expansion of search results beyond the core corpus via live arXiv + OpenAlex queries. Results are labeled as core/connected/external and cached in-memory.

**Architecture:** On-demand module with arXiv Atom feed client + OpenAlex works client. Deduplicates against core corpus, detects connections (cites core or cited by core), caches results with TTL. Exposed via REST API endpoint and wired into the existing search UI.

**Tech Stack:** httpx (async arXiv/OpenAlex clients), feedparser (arXiv Atom), cachetools (TTL cache), existing QdrantStorage for dedup/connection detection

**Spec:** `docs/specs/2026-03-18-search-engine-mvp-design.md` — Section 6

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/core/search/arxiv_client.py` | Async arXiv Atom feed search client |
| Create | `src/core/search/openalex_client.py` | Async OpenAlex works search client |
| Create | `src/core/search/on_demand.py` | On-demand orchestrator: query, dedup, label, cache |
| Modify | `src/core/search/service.py` | Add expand_search() method delegating to on_demand |
| Create | `src/api/models/on_demand.py` | Pydantic models for expansion response |
| Modify | `src/api/routes/search.py` | Add POST /api/search/expand endpoint |
| Modify | `src/api/static/search.html` | Add "Expand search" button + expanded results display |
| Create | `tests/test_on_demand.py` | Unit tests for arXiv/OpenAlex clients and on-demand orchestrator |

**New dependency:** `cachetools` for TTL cache.

---

## Task 1: Add cachetools dependency + create Pydantic models

**Files:**
- Create: `src/api/models/on_demand.py`

- [ ] **Step 1:** Run `uv add cachetools`

- [ ] **Step 2:** Create on-demand response models

```python
# src/api/models/on_demand.py
"""Request and response models for on-demand search expansion."""

from pydantic import BaseModel, Field


class ExpandRequest(BaseModel):
    """On-demand expansion request."""
    query: str = Field(..., min_length=1, max_length=500)
    sources: str = Field(default="both", pattern="^(arxiv|openalex|both)$")
    limit: int = Field(default=20, ge=1, le=50)


class ConnectedPaper(BaseModel):
    """A core paper connected to an expanded result."""
    id: str
    title: str
    relation: str  # "cites" or "cited_by"


class ExpandedResultItem(BaseModel):
    """A single result from on-demand expansion."""
    title: str
    authors: list[str] = []
    source: str  # "arxiv" or "openalex"
    arxiv_id: str | None = None
    doi: str | None = None
    abstract: str | None = None
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    connection: str  # "core", "connected", "external"
    connected_papers: list[ConnectedPaper] = []


class ExpansionStats(BaseModel):
    """Stats about the expansion operation."""
    arxiv_fetched: int = 0
    openalex_fetched: int = 0
    deduplicated: int = 0
    connected: int = 0
    external: int = 0


class ExpandResponse(BaseModel):
    """On-demand expansion response."""
    expanded_results: list[ExpandedResultItem]
    expansion_stats: ExpansionStats
    query_time_ms: int
    cached: bool = False
```

- [ ] **Step 3:** Commit

```bash
git add pyproject.toml uv.lock src/api/models/on_demand.py
git commit -m "feat: add cachetools dependency and on-demand expansion models"
```

---

## Task 2: Create arXiv search client

**Files:**
- Create: `src/core/search/arxiv_client.py`
- Create: `tests/test_on_demand.py`

- [ ] **Step 1: Write test**

```python
# tests/test_on_demand.py
"""Tests for on-demand retrieval."""

import pytest
import respx
from httpx import Response

from src.core.search.arxiv_client import ArxivClient


SAMPLE_ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>Test Paper About Transformers</title>
    <summary>This paper explores transformer architectures.</summary>
    <author><name>Author A</name></author>
    <author><name>Author B</name></author>
    <published>2023-01-01T00:00:00Z</published>
    <link href="http://arxiv.org/abs/2301.00001v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2301.00001v1" rel="related" type="application/pdf" title="pdf"/>
  </entry>
</feed>"""


class TestArxivClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_search_returns_normalized_results(self):
        respx.get("http://export.arxiv.org/api/query").mock(
            return_value=Response(200, text=SAMPLE_ARXIV_ATOM),
        )
        client = ArxivClient()
        async with client:
            results = await client.search("transformers", max_results=10)
        assert len(results) == 1
        assert results[0]["title"] == "Test Paper About Transformers"
        assert results[0]["arxiv_id"] == "2301.00001"
        assert results[0]["source"] == "arxiv"
        assert results[0]["authors"] == ["Author A", "Author B"]
        assert results[0]["year"] == 2023

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_handles_empty_response(self):
        empty_feed = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        respx.get("http://export.arxiv.org/api/query").mock(
            return_value=Response(200, text=empty_feed),
        )
        client = ArxivClient()
        async with client:
            results = await client.search("nonexistent topic", max_results=10)
        assert results == []
```

- [ ] **Step 2: Implement arXiv client**

```python
# src/core/search/arxiv_client.py
"""Async arXiv API client using Atom feed."""

import logging
import re
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"


class ArxivClient:
    """Search arXiv via the Atom feed API."""

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ArxivClient":
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def search(self, query: str, max_results: int = 20) -> list[dict]:
        """Search arXiv and return normalized results."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        try:
            response = await self._client.get(
                ARXIV_API_URL,
                params={
                    "search_query": f"all:{query}",
                    "start": 0,
                    "max_results": max_results,
                    "sortBy": "relevance",
                    "sortOrder": "descending",
                },
            )
            response.raise_for_status()
            return self._parse_feed(response.text)
        except Exception as e:
            logger.error(f"arXiv search failed: {e}")
            return []

    def _parse_feed(self, xml_text: str) -> list[dict]:
        """Parse Atom feed XML into normalized paper dicts."""
        results = []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return []

        for entry in root.findall(f"{ATOM_NS}entry"):
            arxiv_url = entry.findtext(f"{ATOM_NS}id", "")
            arxiv_id = re.sub(r"v\d+$", "", arxiv_url.split("/abs/")[-1]) if "/abs/" in arxiv_url else ""

            title = entry.findtext(f"{ATOM_NS}title", "").strip().replace("\n", " ")
            abstract = entry.findtext(f"{ATOM_NS}summary", "").strip().replace("\n", " ")
            authors = [a.findtext(f"{ATOM_NS}name", "") for a in entry.findall(f"{ATOM_NS}author")]
            published = entry.findtext(f"{ATOM_NS}published", "")
            year = int(published[:4]) if published and len(published) >= 4 else None

            pdf_url = None
            for link in entry.findall(f"{ATOM_NS}link"):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href")

            if title and arxiv_id:
                results.append({
                    "title": title,
                    "abstract": abstract,
                    "authors": authors,
                    "arxiv_id": arxiv_id,
                    "doi": None,
                    "year": year,
                    "venue": None,
                    "url": arxiv_url,
                    "pdf_url": pdf_url,
                    "source": "arxiv",
                })

        return results
```

- [ ] **Step 3:** Run tests and commit

```bash
uv run pytest tests/test_on_demand.py::TestArxivClient -v
git add src/core/search/arxiv_client.py tests/test_on_demand.py
git commit -m "feat: add async arXiv Atom feed search client"
```

---

## Task 3: Create OpenAlex search client

**Files:**
- Create: `src/core/search/openalex_client.py`
- Append tests to: `tests/test_on_demand.py`

- [ ] **Step 1: Write test and implement**

The OpenAlex client uses the works endpoint: `GET https://api.openalex.org/works?search={query}&per_page={limit}`. It reuses the existing multi-key management from `src/core/constants.py`.

Test should mock the OpenAlex response and verify normalized output (title, authors, doi, year, venue, source="openalex").

Implementation follows the existing `httpx` async pattern with key rotation via `get_openalex_api_keys()` and `get_openalex_email()`.

- [ ] **Step 2:** Commit

```bash
git add src/core/search/openalex_client.py tests/test_on_demand.py
git commit -m "feat: add async OpenAlex works search client"
```

---

## Task 4: Create on-demand orchestrator

**Files:**
- Create: `src/core/search/on_demand.py`
- Append tests to: `tests/test_on_demand.py`

The orchestrator:
1. Queries arXiv + OpenAlex in parallel
2. Normalizes results to common schema
3. Deduplicates against core corpus (DOI / arXiv ID match via QdrantStorage.queries)
4. Labels results: "core" (already in corpus), "connected" (cites/cited-by core), "external"
5. Caches results with `cachetools.TTLCache` guarded by `asyncio.Lock`

Connection detection:
- DOI/arXiv ID match → "core"
- Check stub index (external paper's DOI in stubs → "connected", cited by core)
- Otherwise → "external"

- [ ] **Step 1: Implement and test**
- [ ] **Step 2:** Commit

```bash
git add src/core/search/on_demand.py tests/test_on_demand.py
git commit -m "feat: add on-demand search orchestrator with dedup, connection detection, and TTL cache"
```

---

## Task 5: Wire into API + SearchService

**Files:**
- Modify: `src/core/search/service.py` — add `expand_search()` method
- Modify: `src/api/routes/search.py` — add `POST /api/search/expand` endpoint
- Modify: `src/api/dependencies.py` — init on-demand service in lifespan

- [ ] **Step 1: Add expand_search to SearchService**
- [ ] **Step 2: Add API endpoint**
- [ ] **Step 3: Update on_demand_available flag** — set to `True` now that Phase 4 is deployed
- [ ] **Step 4:** Commit

```bash
git add src/core/search/service.py src/api/routes/search.py src/api/dependencies.py
git commit -m "feat: add POST /api/search/expand endpoint for on-demand retrieval"
```

---

## Task 6: Update search UI with expansion button

**Files:**
- Modify: `src/api/static/search.html`

Add:
- "Expand to arXiv & OpenAlex" button below core results
- Expanded results section with core/connected/external labels
- Connection badges (cyan for connected, gray for external)

- [ ] **Step 1: Update UI**
- [ ] **Step 2:** Commit

```bash
git add src/api/static/search.html
git commit -m "feat: add on-demand expansion button and expanded results to search UI"
```

---

## Execution Checklist

| Task | Description | Estimated Time |
|------|-------------|---------------|
| 1 | cachetools dep + Pydantic models | 5 min |
| 2 | arXiv search client + tests | 10 min |
| 3 | OpenAlex search client + tests | 10 min |
| 4 | On-demand orchestrator (dedup, label, cache) | 15 min |
| 5 | Wire into API + SearchService | 10 min |
| 6 | Update search UI | 10 min |
