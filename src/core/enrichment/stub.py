"""Stub paper enrichment via OpenAlex and CrossRef APIs.

Enriches stub papers (external references) with metadata like title, authors,
year, venue, and abstract by looking up their identifiers in external APIs.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.core.enrichment.base import BaseEnricher, CrossRefMixin, OpenAlexMixin

if TYPE_CHECKING:
    from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


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


class StubEnricher(BaseEnricher, OpenAlexMixin, CrossRefMixin):
    """Enricher for stub papers (external references).

    Fetches metadata for stub papers using OpenAlex (for DOI/arXiv/OpenAlex IDs)
    and CrossRef (as fallback for DOIs). Prioritizes most-cited stubs.
    """

    def __init__(
        self,
        storage: "QdrantStorage | None" = None,
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
        super().__init__(
            storage=storage,
            delay=delay,
            max_concurrent=max_concurrent,
        )
        self._init_openalex(email=email, api_key=api_key)
        self._init_crossref(email=email)

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
                    raw_data = await self.fetch_openalex_work(doi, "doi")
                    if raw_data:
                        metadata = self.parse_openalex_work(raw_data)
                    else:
                        raw_data = await self.fetch_crossref_work(doi)
                        if raw_data:
                            metadata = self.parse_crossref_work(raw_data)

                elif id_type == "arxiv":
                    arxiv_id = identifier.replace("arXiv:", "").replace("arxiv:", "")
                    # Try direct arXiv lookup first
                    raw_data = await self.fetch_openalex_work(arxiv_id, "arxiv")
                    if raw_data:
                        metadata = self.parse_openalex_work(raw_data)
                    else:
                        # Try arXiv DOI format: 10.48550/arXiv.{id}
                        arxiv_doi = f"10.48550/arXiv.{arxiv_id}"
                        raw_data = await self.fetch_openalex_work(arxiv_doi, "doi")
                        if raw_data:
                            metadata = self.parse_openalex_work(raw_data)

                elif id_type == "openalex":
                    work_id = identifier.replace("W", "").replace("w", "")
                    raw_data = await self.fetch_openalex_work(work_id, "openalex")
                    if raw_data:
                        metadata = self.parse_openalex_work(raw_data)

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
