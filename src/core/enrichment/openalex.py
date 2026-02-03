"""Unified paper enrichment via OpenAlex DOI lookup.

Enriches papers with citation data (referenced_works) and abstracts by looking up
papers in OpenAlex via DOI. Supports parallel processing for faster enrichment.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)

OPENALEX_BASE_URL = "https://api.openalex.org"


class EnrichmentType(Enum):
    """Type of enrichment to perform."""

    CITATIONS = "citations"
    ABSTRACTS = "abstracts"
    TITLE_CITATIONS = "title_citations"  # Title-based lookup for papers without DOIs


@dataclass
class EnrichmentProgress:
    """Track enrichment progress for checkpointing."""

    total_to_process: int = 0
    processed: int = 0
    enriched: int = 0  # Successfully enriched
    not_found: int = 0  # DOI not in OpenAlex
    errors: int = 0
    last_offset: str | None = None
    processed_point_ids: set[str] = field(default_factory=set)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_updated: str | None = None


class PaperEnricher:
    """Unified enricher for citations and abstracts from OpenAlex."""

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        email: str | None = None,
        api_key: str | None = None,
        checkpoint_dir: Path | str | None = None,
        batch_size: int = 100,
        delay: float = 0.1,
        max_concurrent: int = 1,
    ):
        """Initialize PaperEnricher.

        Args:
            storage: QdrantStorage instance. Created if not provided.
            email: OpenAlex email for polite pool. Uses OPENALEX_EMAIL env if not set.
            api_key: OpenAlex API key. Uses OPENALEX_API_KEY env if not set.
            checkpoint_dir: Directory for checkpoint files.
            batch_size: Number of papers to process per batch.
            delay: Delay between API calls in seconds.
            max_concurrent: Maximum concurrent API requests (for parallel mode).
        """
        self.storage = storage or QdrantStorage()
        self.email = email or os.getenv("OPENALEX_EMAIL")
        self.api_key = api_key or os.getenv("OPENALEX_API_KEY")
        self.batch_size = batch_size
        self.delay = delay
        self.max_concurrent = max_concurrent

        # Checkpoint
        self.checkpoint_dir = Path(checkpoint_dir or "data/core/checkpoints")
        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None

    async def __aenter__(self) -> "PaperEnricher":
        """Enter async context."""
        self._client = httpx.AsyncClient(timeout=30.0)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self

    async def __aexit__(self, *args) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()

    def _get_checkpoint_file(self, enrichment_type: EnrichmentType) -> Path:
        """Get checkpoint file path for enrichment type."""
        return self.checkpoint_dir / f"{enrichment_type.value}_enrichment.json"

    def _build_url(self, doi: str) -> str:
        """Build OpenAlex API URL for DOI lookup.

        Args:
            doi: The DOI to look up.

        Returns:
            Full API URL with authentication parameters.
        """
        # Clean DOI - remove https://doi.org/ prefix if present
        if doi.startswith("https://doi.org/"):
            doi = doi[16:]
        elif doi.startswith("http://doi.org/"):
            doi = doi[15:]

        base = f"{OPENALEX_BASE_URL}/works/https://doi.org/{doi}"
        params = []
        if self.api_key:
            params.append(f"api_key={self.api_key}")
        elif self.email:
            params.append(f"mailto={self.email}")
        return f"{base}?{'&'.join(params)}" if params else base

    async def fetch_paper_data(self, doi: str) -> dict[str, Any] | None:
        """Fetch full paper data from OpenAlex by DOI.

        Args:
            doi: The DOI to look up.

        Returns:
            Paper data dict with 'referenced_works' and 'abstract', or None if not found.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        url = self._build_url(doi)
        try:
            response = await self._client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()

            # Extract relevant fields
            refs = data.get("referenced_works", [])
            refs_clean = [ref.replace("https://openalex.org/", "") for ref in refs]

            # Reconstruct abstract from inverted index
            abstract = self._reconstruct_abstract(data.get("abstract_inverted_index"))

            return {
                "referenced_works": refs_clean,
                "abstract": abstract,
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Rate limited, waiting 60 seconds...")
                await asyncio.sleep(60)
                return await self.fetch_paper_data(doi)
            logger.warning(f"HTTP error for DOI {doi}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Error fetching DOI {doi}: {e}")
            return None

    def _reconstruct_abstract(
        self, inverted_index: dict[str, list[int]] | None
    ) -> str | None:
        """Reconstruct abstract from OpenAlex inverted index format.

        Args:
            inverted_index: OpenAlex abstract_inverted_index field.

        Returns:
            Reconstructed abstract string, or None if not available.
        """
        if not inverted_index:
            return None

        # Find max position
        max_pos = 0
        for positions in inverted_index.values():
            if positions:
                max_pos = max(max_pos, max(positions))

        # Build word list
        words = [""] * (max_pos + 1)
        for word, positions in inverted_index.items():
            for pos in positions:
                words[pos] = word

        return " ".join(words)

    async def _fetch_with_limit(self, doi: str) -> dict[str, Any] | None:
        """Fetch with semaphore-controlled concurrency.

        Args:
            doi: The DOI to look up.

        Returns:
            Paper data or None.
        """
        async with self._semaphore:
            result = await self.fetch_paper_data(doi)
            await asyncio.sleep(self.delay)
            return result

    async def search_by_title(
        self, title: str, min_refs: int = 1
    ) -> dict[str, Any] | None:
        """Search OpenAlex by title and return paper with citations.

        Only returns papers that have at least min_refs references.

        Args:
            title: The paper title to search for.
            min_refs: Minimum number of references required (default 1).

        Returns:
            Dict with 'doi', 'referenced_works', 'abstract', or None if not found.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Build search URL
        url = f"{OPENALEX_BASE_URL}/works"
        params = {"search": title, "per_page": 5}
        if self.api_key:
            params["api_key"] = self.api_key
        elif self.email:
            params["mailto"] = self.email

        try:
            response = await self._client.get(url, params=params)
            if response.status_code == 429:
                logger.warning("Rate limited, waiting 60 seconds...")
                await asyncio.sleep(60)
                return await self.search_by_title(title, min_refs)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return None

            # Find best match with sufficient references
            title_lower = title.lower().strip()
            for result in results:
                result_title = (result.get("title") or "").lower().strip()
                refs = result.get("referenced_works", [])

                # Check title similarity (exact or very close match)
                if result_title == title_lower or (
                    len(result_title) > 20
                    and (result_title in title_lower or title_lower in result_title)
                ):
                    if len(refs) >= min_refs:
                        refs_clean = [
                            ref.replace("https://openalex.org/", "") for ref in refs
                        ]
                        doi = result.get("doi")
                        if doi:
                            doi = doi.replace("https://doi.org/", "")

                        abstract = self._reconstruct_abstract(
                            result.get("abstract_inverted_index")
                        )

                        return {
                            "doi": doi,
                            "referenced_works": refs_clean,
                            "abstract": abstract,
                        }

            return None

        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error searching title '{title[:50]}': {e}")
            return None
        except Exception as e:
            logger.warning(f"Error searching title '{title[:50]}': {e}")
            return None

    async def _search_title_with_limit(
        self, title: str, min_refs: int = 1
    ) -> dict[str, Any] | None:
        """Search by title with semaphore-controlled concurrency."""
        async with self._semaphore:
            result = await self.search_by_title(title, min_refs)
            await asyncio.sleep(self.delay)
            return result

    async def enrich_batch_parallel(
        self,
        papers: list[tuple[str, dict]],
        progress: EnrichmentProgress,
        enrichment_type: EnrichmentType,
    ) -> int:
        """Enrich batch with parallel API calls.

        Args:
            papers: List of (point_id, payload) tuples.
            progress: EnrichmentProgress to update.
            enrichment_type: Type of enrichment (citations or abstracts).

        Returns:
            Number of papers successfully enriched.
        """
        # Filter papers that need processing
        to_process = [
            (point_id, payload)
            for point_id, payload in papers
            if payload.get("doi") and point_id not in progress.processed_point_ids
        ]

        if not to_process:
            return 0

        # Create tasks for parallel fetching
        tasks = [self._fetch_with_limit(payload.get("doi")) for _, payload in to_process]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        enriched = 0
        updates = []

        for (point_id, payload), result in zip(to_process, results):
            progress.processed += 1
            progress.processed_point_ids.add(point_id)

            if isinstance(result, Exception):
                logger.warning(f"Error for {payload.get('doi')}: {result}")
                progress.errors += 1
                continue

            if result is None:
                progress.not_found += 1
                continue

            # Extract relevant data based on enrichment type
            if enrichment_type == EnrichmentType.CITATIONS:
                refs = result.get("referenced_works", [])
                if refs:
                    updates.append((point_id, {"referenced_works": refs}))
                    progress.enriched += 1
                    enriched += 1
                    logger.debug(f"Enriched citations for {payload.get('doi')}: {len(refs)} refs")
                else:
                    progress.not_found += 1
            elif enrichment_type == EnrichmentType.ABSTRACTS:
                abstract = result.get("abstract")
                if abstract:
                    updates.append((point_id, {"abstract": abstract}))
                    progress.enriched += 1
                    enriched += 1
                    logger.debug(f"Enriched abstract for {payload.get('doi')}")
                else:
                    progress.not_found += 1

        # Batch update storage
        if updates:
            if enrichment_type == EnrichmentType.CITATIONS:
                self.storage.batch_update_referenced_works(
                    [(pid, data["referenced_works"]) for pid, data in updates]
                )
            elif enrichment_type == EnrichmentType.ABSTRACTS:
                self.storage.batch_update_abstracts(
                    [(pid, data["abstract"]) for pid, data in updates]
                )

        return enriched

    async def enrich_batch_by_title(
        self,
        papers: list[tuple[str, dict]],
        progress: EnrichmentProgress,
        min_refs: int = 1,
    ) -> int:
        """Enrich batch by searching titles in OpenAlex.

        Args:
            papers: List of (point_id, payload) tuples.
            progress: EnrichmentProgress to update.
            min_refs: Minimum references required for a match.

        Returns:
            Number of papers successfully enriched.
        """
        # Filter papers that need processing
        to_process = [
            (point_id, payload)
            for point_id, payload in papers
            if payload.get("title") and point_id not in progress.processed_point_ids
        ]

        if not to_process:
            return 0

        # Create tasks for parallel title search
        tasks = [
            self._search_title_with_limit(payload.get("title"), min_refs)
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
                logger.warning(f"Error for title '{payload.get('title')[:30]}': {result}")
                progress.errors += 1
                continue

            if result is None:
                progress.not_found += 1
                continue

            refs = result.get("referenced_works", [])
            doi = result.get("doi")
            if refs and doi:
                updates.append((point_id, doi, refs))
                progress.enriched += 1
                enriched += 1
                logger.debug(
                    f"Enriched via title search: {payload.get('title')[:40]}... "
                    f"-> DOI: {doi}, {len(refs)} refs"
                )
            else:
                progress.not_found += 1

        # Batch update storage
        if updates:
            self.storage.batch_update_papers_with_doi_and_refs(updates)

        return enriched

    async def enrich_citations_by_title(
        self,
        dry_run: bool = False,
        limit: int | None = None,
        venues: list[str] | None = None,
        min_refs: int = 1,
    ) -> EnrichmentProgress:
        """Enrich papers without DOIs by searching OpenAlex by title.

        This is useful for OpenReview papers (NeurIPS, ICML, ICLR) that
        don't have DOIs but may have arXiv versions indexed in OpenAlex.

        Args:
            dry_run: If True, only count papers without updating.
            limit: Maximum papers to process (None for all).
            venues: Optional list of venue names to filter by.
            min_refs: Minimum number of references required for a match.

        Returns:
            EnrichmentProgress with final statistics.
        """
        progress = self._load_checkpoint(EnrichmentType.TITLE_CITATIONS)
        offset = progress.last_offset

        logger.info("Starting title-based citation enrichment...")

        while True:
            # Get batch of papers without DOIs needing enrichment
            papers, next_offset = self.storage.get_papers_without_doi_missing_references(
                limit=self.batch_size,
                offset=offset,
                venues=venues,
            )

            if not papers:
                break

            if dry_run:
                progress.total_to_process += len(papers)
                logger.info(f"Found {len(papers)} papers without DOIs (dry run)")
            else:
                enriched = await self.enrich_batch_by_title(papers, progress, min_refs)
                logger.info(
                    f"Batch: {enriched}/{len(papers)} enriched via title | "
                    f"Total: {progress.enriched} enriched, "
                    f"{progress.not_found} not found"
                )

            # Update checkpoint
            progress.last_offset = next_offset
            progress.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_checkpoint(progress, EnrichmentType.TITLE_CITATIONS)

            offset = next_offset
            if offset is None:
                break

            if limit and progress.processed >= limit:
                break

        logger.info(
            f"Title-based citation enrichment complete: "
            f"{progress.enriched} enriched, {progress.not_found} not found, "
            f"{progress.errors} errors"
        )
        return progress

    async def enrich_citations(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> EnrichmentProgress:
        """Enrich all papers missing referenced_works.

        Args:
            dry_run: If True, only count papers without updating.
            limit: Maximum papers to process (None for all).

        Returns:
            EnrichmentProgress with final statistics.
        """
        return await self._enrich(
            enrichment_type=EnrichmentType.CITATIONS,
            dry_run=dry_run,
            limit=limit,
        )

    async def enrich_abstracts(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> EnrichmentProgress:
        """Enrich all papers missing abstracts.

        Args:
            dry_run: If True, only count papers without updating.
            limit: Maximum papers to process (None for all).

        Returns:
            EnrichmentProgress with final statistics.
        """
        return await self._enrich(
            enrichment_type=EnrichmentType.ABSTRACTS,
            dry_run=dry_run,
            limit=limit,
        )

    async def _enrich(
        self,
        enrichment_type: EnrichmentType,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> EnrichmentProgress:
        """Internal enrichment method.

        Args:
            enrichment_type: Type of enrichment to perform.
            dry_run: If True, only count papers without updating.
            limit: Maximum papers to process (None for all).

        Returns:
            EnrichmentProgress with final statistics.
        """
        progress = self._load_checkpoint(enrichment_type)
        offset = progress.last_offset

        logger.info(f"Starting {enrichment_type.value} enrichment...")

        while True:
            # Get batch of papers needing enrichment
            if enrichment_type == EnrichmentType.CITATIONS:
                papers, next_offset = self.storage.get_papers_missing_references(
                    has_doi=True,
                    limit=self.batch_size,
                    offset=offset,
                )
            else:  # ABSTRACTS
                papers, next_offset = self.storage.get_papers_missing_abstracts(
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
                enriched = await self.enrich_batch_parallel(papers, progress, enrichment_type)
                logger.info(
                    f"Batch: {enriched}/{len(papers)} enriched | "
                    f"Total: {progress.enriched} enriched, "
                    f"{progress.not_found} not found"
                )

            # Update checkpoint
            progress.last_offset = next_offset
            progress.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_checkpoint(progress, enrichment_type)

            offset = next_offset
            if offset is None:
                break

            if limit and progress.processed >= limit:
                break

        logger.info(
            f"{enrichment_type.value.capitalize()} enrichment complete: "
            f"{progress.enriched} enriched, {progress.not_found} not found, "
            f"{progress.errors} errors"
        )
        return progress

    def _load_checkpoint(self, enrichment_type: EnrichmentType) -> EnrichmentProgress:
        """Load progress from checkpoint file.

        Args:
            enrichment_type: Type of enrichment.

        Returns:
            EnrichmentProgress with saved state or fresh instance.
        """
        checkpoint_file = self._get_checkpoint_file(enrichment_type)
        if checkpoint_file.exists():
            with open(checkpoint_file) as f:
                data = json.load(f)
            progress = EnrichmentProgress(
                total_to_process=data.get("total_to_process", 0),
                processed=data.get("processed", 0),
                enriched=data.get("enriched", 0),
                not_found=data.get("not_found", 0),
                errors=data.get("errors", 0),
                last_offset=data.get("last_offset"),
                started_at=data.get("started_at", datetime.now(timezone.utc).isoformat()),
                last_updated=data.get("last_updated"),
            )
            progress.processed_point_ids = set(data.get("processed_point_ids", []))
            return progress
        return EnrichmentProgress()

    def _save_checkpoint(
        self, progress: EnrichmentProgress, enrichment_type: EnrichmentType
    ) -> None:
        """Save progress to checkpoint file.

        Args:
            progress: EnrichmentProgress to save.
            enrichment_type: Type of enrichment.
        """
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "total_to_process": progress.total_to_process,
            "processed": progress.processed,
            "enriched": progress.enriched,
            "not_found": progress.not_found,
            "errors": progress.errors,
            "last_offset": progress.last_offset,
            "processed_point_ids": list(progress.processed_point_ids),
            "started_at": progress.started_at,
            "last_updated": progress.last_updated,
        }
        checkpoint_file = self._get_checkpoint_file(enrichment_type)
        with open(checkpoint_file, "w") as f:
            json.dump(data, f, indent=2)

    def clear_checkpoint(self, enrichment_type: EnrichmentType) -> None:
        """Clear enrichment checkpoint for fresh start.

        Args:
            enrichment_type: Type of enrichment checkpoint to clear.
        """
        checkpoint_file = self._get_checkpoint_file(enrichment_type)
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            logger.info(f"{enrichment_type.value.capitalize()} enrichment checkpoint cleared")


# Backwards compatibility aliases
CitationEnricher = PaperEnricher
