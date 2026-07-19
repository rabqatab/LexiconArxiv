"""Zotero Web API — push corpus papers into a user's Zotero library.

Writes items via the Zotero write API (max 50/request). Requires
ZOTERO_API_KEY and ZOTERO_LIBRARY_ID (+ ZOTERO_LIBRARY_TYPE user|group,
default user). https://www.zotero.org/support/dev/web_api/v3/write_requests
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ZOTERO_BASE = "https://api.zotero.org"


def get_zotero_config() -> dict | None:
    """Return {api_key, library_id, library_type} or None if unconfigured."""
    key = os.getenv("ZOTERO_API_KEY")
    lib_id = os.getenv("ZOTERO_LIBRARY_ID")
    if not key or not lib_id:
        return None
    return {
        "api_key": key,
        "library_id": lib_id,
        "library_type": os.getenv("ZOTERO_LIBRARY_TYPE", "user"),
    }


def _creators(authors: list) -> list[dict]:
    """Convert 'First Last' author strings to Zotero creator objects.

    Two-field (firstName/lastName) when the name splits, single-field (name)
    otherwise — Zotero accepts both, and single-field avoids mangling
    mononyms or org names.
    """
    creators = []
    for a in authors or []:
        name = a.strip() if isinstance(a, str) else (a or {}).get("display_name", "").strip()
        if not name:
            continue
        parts = name.split()
        if len(parts) >= 2:
            creators.append({"creatorType": "author",
                             "firstName": " ".join(parts[:-1]), "lastName": parts[-1]})
        else:
            creators.append({"creatorType": "author", "name": name})
    return creators


def paper_to_zotero_item(paper: dict[str, Any]) -> dict:
    """Convert a corpus paper dict to a Zotero item.

    conferencePaper when the venue/type looks like a conference, else
    journalArticle. Only sets fields Zotero recognizes for that type.
    """
    venue = (paper.get("venue") or "")
    ptype = (paper.get("type") or "").lower()
    is_conf = "conference" in ptype or any(
        k in venue.lower() for k in ("conference", "proceedings", "workshop", "symposium"))
    item_type = "conferencePaper" if is_conf else "journalArticle"

    item: dict[str, Any] = {
        "itemType": item_type,
        "title": paper.get("title") or "",
        "creators": _creators(paper.get("authors")),
        "abstractNote": paper.get("abstract") or "",
        "DOI": paper.get("doi") or "",
        "url": paper.get("pdf_url") or paper.get("url") or "",
        "date": str(paper.get("year") or ""),
    }
    venue_field = "proceedingsTitle" if item_type == "conferencePaper" else "publicationTitle"
    item[venue_field] = venue
    return item


async def push_to_zotero(papers: list[dict], timeout: float = 30.0) -> dict:
    """Push papers to the configured Zotero library. Returns Zotero's write result.

    Raises RuntimeError if unconfigured. Zotero caps writes at 50 items/request,
    so callers should chunk; this sends one request (first 50) and reports.
    """
    cfg = get_zotero_config()
    if cfg is None:
        raise RuntimeError("Zotero not configured (set ZOTERO_API_KEY + ZOTERO_LIBRARY_ID)")
    items = [paper_to_zotero_item(p) for p in papers[:50]]
    url = f"{ZOTERO_BASE}/{cfg['library_type']}s/{cfg['library_id']}/items"
    headers = {
        "Zotero-API-Key": cfg["api_key"],
        "Zotero-API-Version": "3",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=items)
        resp.raise_for_status()
        result = resp.json()
    return {
        "sent": len(items),
        "successful": len(result.get("successful", {})),
        "failed": len(result.get("failed", {})),
        "raw": result,
    }
