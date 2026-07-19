"""CORE — full-text search over 200M+ open-access papers (beyond abstracts).

Reaches OA full text the local corpus (abstract-level) can't. Requires a free
API key in CORE_API_KEY. https://api.core.ac.uk/docs/v3
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CORE_SEARCH_URL = "https://api.core.ac.uk/v3/search/works"


def get_core_api_key() -> str | None:
    return os.getenv("CORE_API_KEY")


def parse_core_results(data: dict[str, Any]) -> list[dict]:
    """Parse a CORE v3 search response into normalized paper dicts."""
    out = []
    for r in (data or {}).get("results", []):
        title = r.get("title")
        if not title:
            continue
        authors = [a.get("name", "").strip() for a in (r.get("authors") or []) if a.get("name")]
        out.append({
            "title": title.strip(),
            "authors": authors,
            "year": r.get("yearPublished"),
            "doi": r.get("doi"),
            "download_url": r.get("downloadUrl"),
            "abstract": r.get("abstract"),
            "publisher": r.get("publisher"),
        })
    return out


async def search_core(query: str, limit: int = 20, timeout: float = 20.0) -> list[dict]:
    """Full-text search CORE. Returns [] if CORE_API_KEY is unset or on error."""
    key = get_core_api_key()
    if not key:
        logger.warning("CORE_API_KEY not set — skipping CORE search")
        return []
    headers = {"Authorization": f"Bearer {key}"}
    body = {"q": query, "limit": min(limit, 100)}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(CORE_SEARCH_URL, headers=headers, json=body)
            resp.raise_for_status()
            return parse_core_results(resp.json())
    except Exception as e:
        logger.warning(f"CORE search failed for {query!r}: {e}")
        return []
