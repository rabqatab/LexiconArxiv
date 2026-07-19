"""DBLP structured search — author/venue/title queries DBLP indexes well.

Complements semantic search with exact bibliographic lookup ("papers by X at
Y"). Public API, no key. https://dblp.org/faq/13501473.html
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DBLP_SEARCH_URL = "https://dblp.org/search/publ/api"


def _authors(info: dict) -> list[str]:
    """DBLP returns `author` as a dict for one author, a list for many."""
    auth = (info.get("authors") or {}).get("author")
    if auth is None:
        return []
    if isinstance(auth, dict):
        auth = [auth]
    return [a.get("text", "").strip() for a in auth if a.get("text")]


def parse_dblp_hits(data: dict[str, Any]) -> list[dict]:
    """Parse a DBLP publ-search JSON response into normalized paper dicts."""
    hits = (((data or {}).get("result") or {}).get("hits") or {}).get("hit") or []
    out = []
    for h in hits:
        info = h.get("info") or {}
        title = (info.get("title") or "").rstrip(".")
        if not title:
            continue
        out.append({
            "title": title,
            "authors": _authors(info),
            "venue": info.get("venue"),
            "year": int(info["year"]) if str(info.get("year", "")).isdigit() else None,
            "doi": info.get("doi"),
            "url": info.get("ee") or info.get("url"),
            "type": info.get("type"),
        })
    return out


async def search_dblp(query: str, limit: int = 20, timeout: float = 15.0) -> list[dict]:
    """Search DBLP publications by free-text query (author, title, venue)."""
    params = {"q": query, "format": "json", "h": min(limit, 100)}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(DBLP_SEARCH_URL, params=params)
            resp.raise_for_status()
            return parse_dblp_hits(resp.json())
    except Exception as e:
        logger.warning(f"DBLP search failed for {query!r}: {e}")
        return []
