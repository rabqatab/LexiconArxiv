"""CrossRef API integration for citation enrichment.

CrossRef is the authoritative source for DOI metadata and provides excellent
reference data for ACM and other publisher papers where other APIs fail.

API Documentation: https://api.crossref.org/swagger-ui/index.html

Authentication:
    No API key required. Use mailto parameter for polite pool access:
    - CROSSREF_EMAIL: Your email for polite pool access (recommended)

Rate Limits:
    - Public pool: 50 requests per second
    - Polite pool (with mailto): 50 requests per second (better reliability)
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from src.core.enrichment.base import BaseEnricher, CrossRefMixin

if TYPE_CHECKING:
    from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


@dataclass
class CrossRefEnrichmentProgress:
    """Track CrossRef enrichment progress."""

    total_to_process: int = 0
    processed: int = 0
    enriched: int = 0
    not_found: int = 0
    no_refs: int = 0  # Found but no references
    errors: int = 0
    last_offset: str | None = None
    processed_point_ids: set[str] = field(default_factory=set)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_updated: str | None = None


class CrossRefEnricher(BaseEnricher, CrossRefMixin):
    """Enrich papers with citation data from CrossRef."""

    # CrossRef allows 50 req/sec but practical testing shows lower is safer
    DEFAULT_DELAY = 0.1  # 10 req/sec (conservative)
    DEFAULT_CONCURRENT = 5

    def __init__(
        self,
        storage: "QdrantStorage | None" = None,
        email: str | None = None,
        checkpoint_dir: Path | str | None = None,
        batch_size: int = 100,
        delay: float | None = None,
        max_concurrent: int | None = None,
    ):
        """Initialize CrossRefEnricher.

        Args:
            storage: QdrantStorage instance.
            email: Email for polite pool access.
                   If not provided, checks CROSSREF_EMAIL env var.
            checkpoint_dir: Directory for checkpoint files.
            batch_size: Papers per batch.
            delay: Delay between requests in seconds (default: 0.05s = 20 req/sec).
            max_concurrent: Max concurrent requests (default: 10).
        """
        super().__init__(
            storage=storage,
            delay=delay,
            max_concurrent=max_concurrent,
        )
        self._init_crossref(email=email)
        self.batch_size = batch_size

        self.checkpoint_dir = Path(checkpoint_dir or "data/core/checkpoints")
        self._checkpoint_file = self.checkpoint_dir / "crossref_enrichment.json"

    async def __aenter__(self) -> "CrossRefEnricher":
        """Enter async context."""
        await super().__aenter__()

        if self.crossref_email:
            logger.info(
                f"Using CrossRef polite pool (email: {self.crossref_email}). "
                f"Rate: {1/self.delay:.1f} req/sec, {self.max_concurrent} concurrent"
            )
        else:
            logger.info(
                f"Using CrossRef public pool. "
                f"Rate: {1/self.delay:.1f} req/sec, {self.max_concurrent} concurrent"
            )
        return self

    def _load_checkpoint(self) -> CrossRefEnrichmentProgress:
        """Load checkpoint from file."""
        if self._checkpoint_file.exists():
            try:
                with open(self._checkpoint_file) as f:
                    data = json.load(f)
                progress = CrossRefEnrichmentProgress(
                    total_to_process=data.get("total_to_process", 0),
                    processed=data.get("processed", 0),
                    enriched=data.get("enriched", 0),
                    not_found=data.get("not_found", 0),
                    no_refs=data.get("no_refs", 0),
                    errors=data.get("errors", 0),
                    last_offset=data.get("last_offset"),
                    processed_point_ids=set(data.get("processed_point_ids", [])),
                    started_at=data.get("started_at", datetime.now(timezone.utc).isoformat()),
                    last_updated=data.get("last_updated"),
                )
                logger.info(
                    f"Loaded checkpoint: {progress.processed} processed, "
                    f"{progress.enriched} enriched"
                )
                return progress
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Invalid checkpoint file, starting fresh: {e}")
        return CrossRefEnrichmentProgress()

    def _save_checkpoint(self, progress: CrossRefEnrichmentProgress) -> None:
        """Save checkpoint to file."""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "total_to_process": progress.total_to_process,
            "processed": progress.processed,
            "enriched": progress.enriched,
            "not_found": progress.not_found,
            "no_refs": progress.no_refs,
            "errors": progress.errors,
            "last_offset": progress.last_offset,
            "processed_point_ids": list(progress.processed_point_ids),
            "started_at": progress.started_at,
            "last_updated": progress.last_updated,
        }

        with open(self._checkpoint_file, "w") as f:
            json.dump(data, f, indent=2)

    def clear_checkpoint(self) -> None:
        """Clear checkpoint file."""
        if self._checkpoint_file.exists():
            self._checkpoint_file.unlink()
            logger.info("CrossRef enrichment checkpoint cleared")

    async def fetch_by_doi(self, doi: str, max_retries: int = 3) -> dict[str, Any] | None:
        """Fetch paper data from CrossRef by DOI.

        Args:
            doi: Paper DOI (without 'doi:' prefix).
            max_retries: Maximum retries for rate limiting.

        Returns:
            CrossRef work data or None if not found.
        """
        return await self.fetch_crossref_work(doi, max_retries=max_retries)

    def _extract_references(self, work_data: dict[str, Any]) -> list[str]:
        """Extract reference identifiers from CrossRef work data.

        Args:
            work_data: CrossRef work response data.

        Returns:
            List of reference identifiers (doi:X or title:X format).
        """
        references = work_data.get("reference", [])
        if not references:
            return []

        identifiers = []
        for ref in references:
            # Prefer DOI if available
            if ref.get("DOI"):
                identifiers.append(f"doi:{ref['DOI']}")
            elif ref.get("unstructured"):
                # Store unstructured citation for later resolution
                # Truncate to 200 chars to avoid huge strings
                text = ref["unstructured"][:200]
                identifiers.append(f"title:{text}")
            elif ref.get("article-title"):
                identifiers.append(f"title:{ref['article-title']}")

        return identifiers

    async def _fetch_with_limit(self, doi: str) -> tuple[str, dict[str, Any] | None]:
        """Fetch with rate limiting.

        Note: Semaphore and delay are handled in fetch_crossref_work via the mixin.
        """
        result = await self.fetch_by_doi(doi)
        return doi, result

    async def _enrich_batch(
        self,
        papers: list[tuple[str, dict]],
        progress: CrossRefEnrichmentProgress,
    ) -> int:
        """Enrich a batch of papers with CrossRef data.

        Args:
            papers: List of (point_id, payload) tuples.
            progress: Progress tracker.

        Returns:
            Number of papers enriched in this batch.
        """
        # Filter to papers not yet processed
        to_process = [
            (pid, payload)
            for pid, payload in papers
            if pid not in progress.processed_point_ids and payload.get("doi")
        ]

        if not to_process:
            return 0

        # Fetch all papers in parallel
        tasks = [
            self._fetch_with_limit(payload["doi"])
            for _, payload in to_process
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        enriched = 0
        updates = []

        for (point_id, payload), result in zip(to_process, results):
            progress.processed += 1
            progress.processed_point_ids.add(point_id)

            if isinstance(result, Exception):
                logger.warning(f"Error fetching {payload['doi']}: {result}")
                progress.errors += 1
                continue

            doi, work_data = result

            if work_data is None:
                progress.not_found += 1
                continue

            refs = self._extract_references(work_data)
            if not refs:
                progress.no_refs += 1
                continue

            updates.append((point_id, refs))
            progress.enriched += 1
            enriched += 1

        # Batch update to Qdrant
        if updates:
            self.storage.batch_update_referenced_works(updates)

        return enriched

    async def enrich_by_doi(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> CrossRefEnrichmentProgress:
        """Enrich papers with DOIs using CrossRef.

        This targets papers that have a DOI but no referenced_works.

        Args:
            dry_run: Only count papers without updating.
            limit: Maximum papers to process.

        Returns:
            CrossRefEnrichmentProgress with statistics.
        """
        progress = self._load_checkpoint()
        offset = progress.last_offset

        logger.info("Starting CrossRef DOI-based enrichment...")

        while True:
            # Get papers with DOI but no refs
            papers, next_offset = self.storage.get_papers_missing_references(
                has_doi=True,
                limit=self.batch_size,
                offset=offset,
            )

            if not papers:
                break

            if dry_run:
                progress.total_to_process += len(papers)
                logger.info(f"Found {len(papers)} papers (dry run)")
            else:
                enriched = await self._enrich_batch(papers, progress)
                logger.info(
                    f"Batch: {enriched}/{len(papers)} enriched | "
                    f"Total: {progress.enriched} enriched, "
                    f"{progress.not_found} not found, {progress.no_refs} no refs"
                )

            progress.last_offset = next_offset
            progress.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_checkpoint(progress)

            offset = next_offset
            if offset is None:
                break

            if limit and progress.processed >= limit:
                break

        logger.info(
            f"CrossRef enrichment complete: {progress.enriched} enriched, "
            f"{progress.not_found} not found, {progress.no_refs} no refs, "
            f"{progress.errors} errors"
        )
        return progress
