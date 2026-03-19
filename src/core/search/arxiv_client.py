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
