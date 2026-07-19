"""OpenCitations index — open citation counts and citing/cited DOIs by DOI.

Augments the local citation graph with cross-corpus citations. Public API
(no key; a token raises rate limits). Endpoints 301-redirect, so
follow_redirects is required. https://opencitations.net/index/api/v2
"""

import logging

import httpx

logger = logging.getLogger(__name__)

OC_BASE = "https://opencitations.net/index/api/v2"


def _extract_ids(field: str) -> dict:
    """A citing/cited field packs space-separated ids: 'omid:.. doi:.. openalex:..'."""
    ids = {}
    for tok in (field or "").split():
        if tok.startswith("doi:"):
            ids["doi"] = tok[4:]
        elif tok.startswith("openalex:"):
            ids["openalex"] = tok[9:]
    return ids


def parse_citations(data: list, key: str = "citing") -> list[dict]:
    """Parse OC citation objects into {doi, openalex, creation} rows.

    key='citing' for who-cites-this; key='cited' for this-cites-what.
    """
    out = []
    for c in data or []:
        ids = _extract_ids(c.get(key, ""))
        if ids:
            out.append({**ids, "creation": c.get("creation")})
    return out


async def _get(path: str, timeout: float) -> list:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(f"{OC_BASE}/{path}")
        resp.raise_for_status()
        return resp.json()


async def get_citation_count(doi: str, timeout: float = 15.0) -> int:
    """Open citation count for a DOI (0 on error/not-found)."""
    doi = doi.replace("https://doi.org/", "").replace("doi:", "")
    try:
        data = await _get(f"citation-count/doi:{doi}", timeout)
        return int(data[0]["count"]) if data else 0
    except Exception as e:
        logger.warning(f"OpenCitations count failed for {doi}: {e}")
        return 0


async def get_citing_papers(doi: str, limit: int = 50, timeout: float = 20.0) -> list[dict]:
    """DOIs/OpenAlex IDs of papers that cite the given DOI."""
    doi = doi.replace("https://doi.org/", "").replace("doi:", "")
    try:
        data = await _get(f"citations/doi:{doi}", timeout)
        return parse_citations(data, key="citing")[:limit]
    except Exception as e:
        logger.warning(f"OpenCitations citations failed for {doi}: {e}")
        return []
