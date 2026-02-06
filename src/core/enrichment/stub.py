"""Stub paper enrichment via OpenAlex and CrossRef APIs.

Enriches stub papers (external references) with metadata like title, authors,
year, venue, and abstract by looking up their identifiers in external APIs.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)

OPENALEX_BASE_URL = "https://api.openalex.org"
CROSSREF_BASE_URL = "https://api.crossref.org"


@dataclass
class StubEnrichmentProgress:
    """Track stub enrichment progress."""

    total_to_process: int = 0
    processed: int = 0
    enriched: int = 0
    not_found: int = 0
    merged: int = 0  # Duplicates detected and merged
    errors: int = 0
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_updated: str | None = None


class StubEnricher:
    """Enricher for stub papers (external references).

    Fetches metadata for stub papers using OpenAlex (for DOI/arXiv/OpenAlex IDs)
    and CrossRef (as fallback for DOIs). Prioritizes most-cited stubs.
    """

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        email: str | None = None,
        api_key: str | None = None,
        delay: float = 0.1,
        max_concurrent: int = 5,
    ):
        """Initialize StubEnricher.

        Args:
            storage: QdrantStorage instance.
            email: Email for API polite pools.
            api_key: OpenAlex API key.
            delay: Delay between API calls in seconds.
            max_concurrent: Maximum concurrent API requests.
        """
        self.storage = storage or QdrantStorage()
        self.email = email or os.getenv("OPENALEX_EMAIL")
        self.crossref_email = os.getenv("CROSSREF_EMAIL") or self.email
        self.api_key = api_key or os.getenv("OPENALEX_API_KEY")
        self.delay = delay
        self.max_concurrent = max_concurrent

        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None

    async def __aenter__(self) -> "StubEnricher":
        """Enter async context."""
        self._client = httpx.AsyncClient(timeout=30.0)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self

    async def __aexit__(self, *args) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()

    async def enrich_stubs(
        self,
        limit: int = 100,
        identifier_type: str | None = None,
        min_citations: int = 1,
        dry_run: bool = False,
    ) -> StubEnrichmentProgress:
        """Enrich stub papers with metadata from external APIs.

        Args:
            limit: Maximum stubs to enrich.
            identifier_type: Only enrich stubs of this type ('doi', 'arxiv', 'openalex').
            min_citations: Only enrich stubs cited at least this many times.
            dry_run: If True, count stubs without enriching.

        Returns:
            StubEnrichmentProgress with statistics.
        """
        progress = StubEnrichmentProgress()

        # Get most-cited stubs that need enrichment
        stubs = self.storage.get_most_cited_stubs(
            limit=limit,
            min_citations=min_citations,
        )

        # Filter by type if specified
        if identifier_type:
            stubs = [
                (stub_id, payload)
                for stub_id, payload in stubs
                if payload.get("identifier_type") == identifier_type
            ]

        # Filter out already-enriched stubs (have title)
        stubs_to_enrich = [
            (stub_id, payload)
            for stub_id, payload in stubs
            if not payload.get("title")
        ]

        progress.total_to_process = len(stubs_to_enrich)

        if dry_run:
            logger.info(f"Dry run: {progress.total_to_process} stubs would be enriched")
            return progress

        logger.info(f"Enriching {len(stubs_to_enrich)} stub papers...")

        # Process stubs in parallel
        tasks = []
        for stub_id, payload in stubs_to_enrich:
            tasks.append(self._enrich_single_stub(stub_id, payload, progress))

        await asyncio.gather(*tasks)

        progress.last_updated = datetime.now(timezone.utc).isoformat()
        logger.info(
            f"Stub enrichment complete: {progress.enriched} enriched, "
            f"{progress.merged} merged, {progress.not_found} not found, "
            f"{progress.errors} errors"
        )

        return progress

    async def _enrich_single_stub(
        self,
        stub_id: str,
        payload: dict[str, Any],
        progress: StubEnrichmentProgress,
    ) -> None:
        """Enrich a single stub paper.

        Args:
            stub_id: The stub's point ID.
            payload: The stub's current payload.
            progress: Progress tracker to update.
        """
        async with self._semaphore:
            await asyncio.sleep(self.delay)

            progress.processed += 1
            identifier = payload.get("identifier", "")
            id_type = payload.get("identifier_type", "")

            try:
                metadata = None

                if id_type == "doi":
                    # Try OpenAlex first, then CrossRef
                    doi = identifier.replace("DOI:", "").replace("doi:", "")
                    metadata = await self._fetch_from_openalex_doi(doi)
                    if not metadata:
                        metadata = await self._fetch_from_crossref(doi)

                elif id_type == "arxiv":
                    arxiv_id = identifier.replace("arXiv:", "").replace("arxiv:", "")
                    # Try direct arXiv lookup first
                    metadata = await self._fetch_from_openalex_arxiv(arxiv_id)
                    if not metadata:
                        # Try arXiv DOI format: 10.48550/arXiv.{id}
                        arxiv_doi = f"10.48550/arXiv.{arxiv_id}"
                        metadata = await self._fetch_from_openalex_doi(arxiv_doi)

                elif id_type == "openalex":
                    work_id = identifier.replace("W", "").replace("w", "")
                    metadata = await self._fetch_from_openalex_id(work_id)

                if metadata:
                    # Check for duplicate stubs with discovered identifiers
                    duplicate_stub = await self._check_for_duplicate(
                        stub_id=stub_id,
                        current_type=id_type,
                        metadata=metadata,
                    )

                    if duplicate_stub:
                        # Merge current stub into the duplicate
                        dup_id, dup_payload = duplicate_stub
                        success = self.storage.merge_stubs(
                            keep_stub_id=dup_id,
                            merge_stub_id=stub_id,
                        )
                        if success:
                            progress.merged += 1
                            logger.info(
                                f"Merged duplicate stub {stub_id} ({id_type}) "
                                f"into {dup_id}"
                            )
                            # Also update the kept stub with metadata if needed
                            if not dup_payload.get("title"):
                                self.storage.update_stub_metadata(
                                    stub_id=dup_id,
                                    title=metadata.get("title"),
                                    year=metadata.get("year"),
                                    authors=metadata.get("authors"),
                                    venue=metadata.get("venue"),
                                    abstract=metadata.get("abstract"),
                                    citation_count=metadata.get("citation_count"),
                                )
                        else:
                            progress.errors += 1
                    else:
                        # No duplicate, just update metadata and add alternate identifiers
                        success = self.storage.update_stub_metadata(
                            stub_id=stub_id,
                            title=metadata.get("title"),
                            year=metadata.get("year"),
                            authors=metadata.get("authors"),
                            venue=metadata.get("venue"),
                            abstract=metadata.get("abstract"),
                            citation_count=metadata.get("citation_count"),
                        )

                        # Add discovered alternate identifiers
                        if id_type != "doi" and metadata.get("doi"):
                            self.storage.add_stub_alternate_identifier(
                                stub_id, "doi", metadata["doi"]
                            )
                        if id_type != "arxiv" and metadata.get("arxiv_id"):
                            self.storage.add_stub_alternate_identifier(
                                stub_id, "arxiv", metadata["arxiv_id"]
                            )
                        if id_type != "openalex" and metadata.get("openalex_id"):
                            self.storage.add_stub_alternate_identifier(
                                stub_id, "openalex", metadata["openalex_id"]
                            )

                        if success:
                            progress.enriched += 1
                            logger.debug(f"Enriched stub {stub_id}: {metadata.get('title', '')[:50]}")
                        else:
                            progress.errors += 1
                else:
                    progress.not_found += 1

            except Exception as e:
                logger.warning(f"Error enriching stub {stub_id}: {e}")
                progress.errors += 1

            # Progress logging
            if progress.processed % 100 == 0:
                logger.info(
                    f"Stub enrichment progress: {progress.processed}/{progress.total_to_process}, "
                    f"{progress.enriched} enriched, {progress.merged} merged"
                )

    async def _check_for_duplicate(
        self,
        stub_id: str,
        current_type: str,
        metadata: dict[str, Any],
    ) -> tuple[str, dict] | None:
        """Check if a duplicate stub exists with discovered identifiers.

        When we enrich an arXiv stub and discover its DOI, check if a DOI stub
        already exists (or vice versa).

        Args:
            stub_id: The current stub's ID.
            current_type: The current stub's identifier type.
            metadata: The enrichment metadata with discovered identifiers.

        Returns:
            Tuple of (duplicate_stub_id, payload) if found, None otherwise.
        """
        # Check each identifier type that's different from current
        checks = []
        if current_type != "doi" and metadata.get("doi"):
            checks.append(("doi", metadata["doi"]))
        if current_type != "arxiv" and metadata.get("arxiv_id"):
            checks.append(("arxiv", metadata["arxiv_id"]))
        if current_type != "openalex" and metadata.get("openalex_id"):
            checks.append(("openalex", metadata["openalex_id"]))

        for id_type, id_value in checks:
            # Try to find existing stub with this identifier
            # OpenAlex IDs are stored as just "W123..." without prefix
            if id_type == "openalex":
                prefixed = id_value.upper() if id_value.startswith(('w', 'W')) else f"W{id_value}"
            else:
                prefixed = f"{id_type.upper()}:{id_value}"
            existing = self.storage.get_stub_by_identifier(prefixed)

            if existing:
                existing_id, existing_payload = existing
                # Don't match with self
                if existing_id != stub_id:
                    return existing

            # Also check via alternate identifiers
            existing = self.storage.find_stub_by_alternate_identifier(
                doi=id_value if id_type == "doi" else None,
                arxiv_id=id_value if id_type == "arxiv" else None,
                openalex_id=id_value if id_type == "openalex" else None,
            )

            if existing:
                existing_id, existing_payload = existing
                if existing_id != stub_id:
                    return existing

        return None

    async def _fetch_from_openalex_doi(self, doi: str) -> dict[str, Any] | None:
        """Fetch paper metadata from OpenAlex by DOI.

        Args:
            doi: The DOI to look up.

        Returns:
            Metadata dict or None if not found.
        """
        url = f"{OPENALEX_BASE_URL}/works/https://doi.org/{doi}"
        params = {}
        if self.api_key:
            params["api_key"] = self.api_key
        elif self.email:
            params["mailto"] = self.email

        return await self._fetch_openalex_work(url, params)

    async def _fetch_from_openalex_arxiv(self, arxiv_id: str) -> dict[str, Any] | None:
        """Fetch paper metadata from OpenAlex by arXiv ID.

        Args:
            arxiv_id: The arXiv ID to look up.

        Returns:
            Metadata dict or None if not found.
        """
        url = f"{OPENALEX_BASE_URL}/works/arXiv:{arxiv_id}"
        params = {}
        if self.api_key:
            params["api_key"] = self.api_key
        elif self.email:
            params["mailto"] = self.email

        return await self._fetch_openalex_work(url, params)

    async def _fetch_from_openalex_id(self, work_id: str) -> dict[str, Any] | None:
        """Fetch paper metadata from OpenAlex by Work ID.

        Args:
            work_id: The OpenAlex Work ID (without W prefix).

        Returns:
            Metadata dict or None if not found.
        """
        url = f"{OPENALEX_BASE_URL}/works/W{work_id}"
        params = {}
        if self.api_key:
            params["api_key"] = self.api_key
        elif self.email:
            params["mailto"] = self.email

        return await self._fetch_openalex_work(url, params)

    async def _fetch_openalex_work(
        self, url: str, params: dict[str, str]
    ) -> dict[str, Any] | None:
        """Fetch and parse OpenAlex work data.

        Args:
            url: The API URL.
            params: Query parameters.

        Returns:
            Parsed metadata dict or None.
        """
        try:
            response = await self._client.get(url, params=params)

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                logger.warning("Rate limited by OpenAlex, waiting 60s...")
                await asyncio.sleep(60)
                return await self._fetch_openalex_work(url, params)

            response.raise_for_status()
            data = response.json()

            # Extract metadata
            title = data.get("title")
            year = data.get("publication_year")

            # Extract authors
            authors = []
            for authorship in data.get("authorships", [])[:10]:  # Limit to 10 authors
                author = authorship.get("author", {})
                name = author.get("display_name")
                if name:
                    authors.append(name)

            # Extract venue
            venue = None
            primary_location = data.get("primary_location", {})
            if primary_location:
                source = primary_location.get("source", {})
                if source:
                    venue = source.get("display_name")

            # Reconstruct abstract
            abstract = None
            inverted_index = data.get("abstract_inverted_index")
            if inverted_index:
                abstract = self._reconstruct_abstract(inverted_index)

            # Citation count
            citation_count = data.get("cited_by_count")

            # Extract identifiers for cross-reference
            doi = data.get("doi")
            if doi:
                # Clean DOI URL format
                if doi.startswith("https://doi.org/"):
                    doi = doi[16:]
                elif doi.startswith("http://doi.org/"):
                    doi = doi[15:]

            # Extract arXiv ID from IDs list
            arxiv_id = None
            for id_obj in data.get("ids", {}).values():
                if isinstance(id_obj, str) and "arxiv.org" in id_obj:
                    # Extract arXiv ID from URL like https://arxiv.org/abs/2303.08774
                    parts = id_obj.split("/")
                    if len(parts) >= 2:
                        arxiv_id = parts[-1]
                        break

            # Extract OpenAlex ID
            openalex_id = data.get("id", "")
            if openalex_id:
                openalex_id = openalex_id.replace("https://openalex.org/", "")

            return {
                "title": title,
                "year": year,
                "authors": authors if authors else None,
                "venue": venue,
                "abstract": abstract,
                "citation_count": citation_count,
                # Identifiers for cross-reference
                "doi": doi,
                "arxiv_id": arxiv_id,
                "openalex_id": openalex_id,
            }

        except Exception as e:
            logger.debug(f"OpenAlex fetch error: {e}")
            return None

    async def _fetch_from_crossref(self, doi: str) -> dict[str, Any] | None:
        """Fetch paper metadata from CrossRef by DOI.

        Args:
            doi: The DOI to look up.

        Returns:
            Metadata dict or None if not found.
        """
        url = f"{CROSSREF_BASE_URL}/works/{doi}"
        headers = {}
        if self.crossref_email:
            headers["User-Agent"] = f"LexiconArxiv/1.0 (mailto:{self.crossref_email})"

        try:
            response = await self._client.get(url, headers=headers)

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                logger.warning("Rate limited by CrossRef, waiting 60s...")
                await asyncio.sleep(60)
                return await self._fetch_from_crossref(doi)

            response.raise_for_status()
            data = response.json()
            message = data.get("message", {})

            # Extract title
            titles = message.get("title", [])
            title = titles[0] if titles else None

            # Extract year
            year = None
            published = message.get("published", {}) or message.get("published-print", {})
            date_parts = published.get("date-parts", [[]])
            if date_parts and date_parts[0]:
                year = date_parts[0][0]

            # Extract authors
            authors = []
            for author in message.get("author", [])[:10]:
                given = author.get("given", "")
                family = author.get("family", "")
                name = f"{given} {family}".strip()
                if name:
                    authors.append(name)

            # Extract venue
            venue = None
            container = message.get("container-title", [])
            if container:
                venue = container[0]

            return {
                "title": title,
                "year": year,
                "authors": authors if authors else None,
                "venue": venue,
                "abstract": None,  # CrossRef rarely has abstracts
                "citation_count": message.get("is-referenced-by-count"),
            }

        except Exception as e:
            logger.debug(f"CrossRef fetch error: {e}")
            return None

    def _reconstruct_abstract(self, inverted_index: dict | None) -> str | None:
        """Reconstruct abstract from OpenAlex inverted index.

        Args:
            inverted_index: OpenAlex abstract_inverted_index format.

        Returns:
            Reconstructed abstract text or None.
        """
        if not inverted_index:
            return None

        try:
            # Find max position
            max_pos = 0
            for positions in inverted_index.values():
                if positions:
                    max_pos = max(max_pos, max(positions))

            # Build word array
            words = [""] * (max_pos + 1)
            for word, positions in inverted_index.items():
                for pos in positions:
                    words[pos] = word

            return " ".join(words)
        except Exception:
            return None
