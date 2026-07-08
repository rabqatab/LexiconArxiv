"""Unified paper enrichment via OpenAlex DOI lookup.

Enriches papers with citation data (referenced_works) and abstracts by looking up
papers in OpenAlex via DOI. Supports parallel processing for faster enrichment.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher

from src.core.deduplication import Deduplicator
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from src.core.enrichment.base import OPENALEX_BASE_URL, BaseEnricher, OpenAlexMixin
from src.core.exceptions import APIRateLimitError
from src.core.openalex_keys import OpenAlexKeyManager

if TYPE_CHECKING:
    from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)



# --- Title matching helpers ---

_TITLE_MATCH_THRESHOLD = 0.90


def _titles_match(norm_a: str, norm_b: str) -> bool:
    """Check if two normalized titles refer to the same paper.

    Uses a length ratio pre-filter followed by SequenceMatcher ratio
    with a threshold of 0.90. This catches minor variations (acronym
    prefixes, punctuation, word differences) while rejecting clearly
    different papers.
    """
    if not norm_a or not norm_b:
        return False
    if norm_a == norm_b:
        return True
    # Fast rejection: if lengths differ by more than 30%, skip expensive ratio
    len_ratio = min(len(norm_a), len(norm_b)) / max(len(norm_a), len(norm_b))
    if len_ratio < 0.70:
        return False
    return SequenceMatcher(None, norm_a, norm_b).ratio() >= _TITLE_MATCH_THRESHOLD


class EnrichmentType(Enum):
    """Type of enrichment to perform."""

    CITATIONS = "citations"
    ABSTRACTS = "abstracts"
    TITLE_CITATIONS = "title_citations"  # Title-based lookup for papers without DOIs
    RESOLVE_TITLE_REFS = "resolve_title_refs"  # Resolve TITLE:xxx refs to DOI/OpenAlex IDs


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


class PaperEnricher(BaseEnricher, OpenAlexMixin):
    """Unified enricher for citations and abstracts from OpenAlex."""

    DEFAULT_DELAY = 0.1
    DEFAULT_CONCURRENT_API_KEY = 3  # Stay under 10 req/s with delay=0.1
    DEFAULT_CONCURRENT_EMAIL = 1  # Lower limit for email-based polite pool

    def __init__(
        self,
        storage: "QdrantStorage | None" = None,
        email: str | None = None,
        api_key: str | None = None,
        key_manager: OpenAlexKeyManager | None = None,
        checkpoint_dir: Path | str | None = None,
        batch_size: int = 100,
        delay: float = 0.1,
        max_concurrent: int | None = None,
    ):
        """Initialize PaperEnricher.

        Args:
            storage: QdrantStorage instance. Created if not provided.
            email: OpenAlex email for polite pool. Uses OPENALEX_EMAIL env if not set.
            api_key: OpenAlex API key. Uses OPENALEX_API_KEY env if not set.
            key_manager: Pre-configured OpenAlexKeyManager instance.
            checkpoint_dir: Directory for checkpoint files.
            batch_size: Number of papers to process per batch.
            delay: Delay between API calls in seconds.
            max_concurrent: Maximum concurrent API requests. If None, uses 3 for API key, 1 for email.
        """
        # Initialize OpenAlex first to determine if API keys are available
        self._init_openalex(email=email, api_key=api_key, key_manager=key_manager)

        # Set default concurrency based on auth method
        if max_concurrent is None:
            max_concurrent = (
                self.DEFAULT_CONCURRENT_API_KEY
                if self._key_manager.has_available_keys
                else self.DEFAULT_CONCURRENT_EMAIL
            )

        super().__init__(
            storage=storage,
            delay=delay,
            max_concurrent=max_concurrent,
        )
        self._original_max_concurrent = max_concurrent
        self.batch_size = batch_size

        # Checkpoint
        self.checkpoint_dir = Path(checkpoint_dir or "data/core/checkpoints")

    def _get_checkpoint_file(self, enrichment_type: EnrichmentType) -> Path:
        """Get checkpoint file path for enrichment type."""
        return self.checkpoint_dir / f"{enrichment_type.value}_enrichment.json"

    async def fetch_paper_data(self, doi: str) -> dict[str, Any] | None:
        """Fetch full paper data from OpenAlex by DOI.

        Args:
            doi: The DOI to look up.

        Returns:
            Paper data dict with 'referenced_works' and 'abstract', or None if not found.
        """
        # Clean DOI - remove https://doi.org/ prefix if present
        if doi.startswith("https://doi.org/"):
            doi = doi[16:]
        elif doi.startswith("http://doi.org/"):
            doi = doi[15:]

        raw_data = await self.fetch_openalex_work(doi, identifier_type="doi")
        if not raw_data:
            return None

        # Extract relevant fields using the parse method
        parsed = self.parse_openalex_work(raw_data)
        return {
            "referenced_works": parsed.get("referenced_works", []),
            "abstract": parsed.get("abstract"),
        }

    async def _fetch_with_limit(self, doi: str) -> dict[str, Any] | None:
        """Fetch paper data (semaphore is handled by fetch_openalex_work).

        Args:
            doi: The DOI to look up.

        Returns:
            Paper data or None.
        """
        # Note: semaphore and delay are handled in fetch_openalex_work via the mixin
        return await self.fetch_paper_data(doi)

    async def search_by_title(
        self, title: str, min_refs: int = 1, _retry_count: int = 0,
    ) -> dict[str, Any] | None:
        """Search OpenAlex by title and return paper with citations.

        Only returns papers that have at least min_refs references.

        Args:
            title: The paper title to search for.
            min_refs: Minimum number of references required (default 1).
            _retry_count: Internal retry counter (do not set manually).

        Returns:
            Dict with 'doi', 'referenced_works', 'abstract', or None if not found.
        """
        max_retries = 3

        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Build search URL
        url = f"{OPENALEX_BASE_URL}/works"
        params = {"search": title, "per_page": 5}
        openalex_params = self._get_openalex_params()
        used_key = openalex_params.get("api_key")
        params.update(openalex_params)

        try:
            async with self._semaphore:
                response = await self._client.get(url, params=params)
                await asyncio.sleep(self.delay)
            if response.status_code == 429:
                # Check if API key credits exhausted - if so, rotate key and retry
                if self._handle_api_key_exhaustion(response, used_key):
                    if self._key_manager.has_available_keys:
                        if hasattr(self, "_semaphore") and self._semaphore is not None:
                            self._semaphore = asyncio.Semaphore(
                                self._original_max_concurrent
                            )
                    return await self.search_by_title(title, min_refs, _retry_count=0)
                # Regular rate limiting - wait and retry (with max retries)
                if _retry_count >= max_retries:
                    logger.warning(
                        f"OpenAlex rate limit: max retries ({max_retries}) reached "
                        f"for title search '{title[:50]}', skipping."
                    )
                    raise APIRateLimitError(
                        f"Max retries ({max_retries}) for title: {title[:50]}"
                    )
                logger.warning(
                    f"Rate limited, waiting 60s... "
                    f"(retry {_retry_count + 1}/{max_retries})"
                )
                await asyncio.sleep(60)
                return await self.search_by_title(title, min_refs, _retry_count=_retry_count + 1)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return None

            # Find best match with sufficient references
            title_norm = Deduplicator.normalize_title(title)
            for result in results:
                result_title = result.get("title") or ""
                refs = result.get("referenced_works", [])

                # Check title similarity via normalized SequenceMatcher
                if _titles_match(title_norm, Deduplicator.normalize_title(result_title)):
                    if len(refs) >= min_refs:
                        refs_clean = [
                            ref.replace("https://openalex.org/", "") for ref in refs
                        ]
                        doi = result.get("doi")
                        if doi:
                            doi = doi.replace("https://doi.org/", "")

                        abstract = self.reconstruct_abstract(
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
        """Search by title with concurrency control (managed inside search_by_title)."""
        return await self.search_by_title(title, min_refs)

    async def search_title_for_identifier(
        self, title: str, _retry_count: int = 0,
    ) -> str | None:
        """Search OpenAlex by title and return just an identifier string.

        Lighter variant of search_by_title — only returns an identifier,
        not full paper data. Used for resolving TITLE:xxx references.

        Args:
            title: The paper title to search for.
            _retry_count: Internal retry counter (do not set manually).

        Returns:
            "DOI:xxx" if DOI available, "Wxxx" (OpenAlex work ID) if not, or None.
        """
        max_retries = 3

        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        url = f"{OPENALEX_BASE_URL}/works"
        params = {"search": title, "per_page": 5}
        openalex_params = self._get_openalex_params()
        used_key = openalex_params.get("api_key")
        params.update(openalex_params)

        try:
            async with self._semaphore:
                response = await self._client.get(url, params=params)
                await asyncio.sleep(self.delay)
            if response.status_code == 429:
                if self._handle_api_key_exhaustion(response, used_key):
                    if self._key_manager.has_available_keys:
                        if hasattr(self, "_semaphore") and self._semaphore is not None:
                            self._semaphore = asyncio.Semaphore(
                                self._original_max_concurrent
                            )
                    return await self.search_title_for_identifier(title, _retry_count=0)
                if _retry_count >= max_retries:
                    logger.warning(
                        f"OpenAlex rate limit: max retries ({max_retries}) reached "
                        f"for title identifier search '{title[:50]}', skipping."
                    )
                    raise APIRateLimitError(
                        f"Max retries ({max_retries}) for title: {title[:50]}"
                    )
                logger.warning(
                    f"Rate limited, waiting 60s... "
                    f"(retry {_retry_count + 1}/{max_retries})"
                )
                await asyncio.sleep(60)
                return await self.search_title_for_identifier(title, _retry_count=_retry_count + 1)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return None

            title_norm = Deduplicator.normalize_title(title)
            for result in results:
                result_title = result.get("title") or ""
                if _titles_match(title_norm, Deduplicator.normalize_title(result_title)):
                    # Prefer DOI, fall back to OpenAlex work ID
                    doi = result.get("doi")
                    if doi:
                        return f"DOI:{doi.replace('https://doi.org/', '')}"
                    openalex_id = result.get("id", "")
                    if openalex_id:
                        return openalex_id.replace("https://openalex.org/", "")
                    return None

            return None

        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error searching title identifier '{title[:50]}': {e}")
            return None
        except Exception as e:
            logger.warning(f"Error searching title identifier '{title[:50]}': {e}")
            return None

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

            if isinstance(result, APIRateLimitError):
                # Don't mark as processed — will retry on next run
                progress.errors += 1
                continue

            # Mark as processed (success, not-found, or other error)
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

            if isinstance(result, APIRateLimitError):
                # Don't mark as processed — will retry on next run
                progress.errors += 1
                continue

            # Mark as processed (success, not-found, or other error)
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
        fetched_since: str | None = None,
    ) -> EnrichmentProgress:
        """Enrich all papers missing abstracts.

        Args:
            dry_run: If True, only count papers without updating.
            limit: Maximum papers to process (None for all).
            fetched_since: ISO date string (e.g., "2026-07-06"). When set,
                only scans papers fetched after this date — critical for
                incremental cycles at corpus scale. Without this, Qdrant
                does a full scan on the unindexed ``abstract`` field and
                blows past its 60s scroll_by_id server-side timeout
                (2026-07-06 incremental fatal).

        Returns:
            EnrichmentProgress with final statistics.
        """
        return await self._enrich(
            enrichment_type=EnrichmentType.ABSTRACTS,
            dry_run=dry_run,
            limit=limit,
            fetched_since=fetched_since,
        )

    async def _enrich(
        self,
        enrichment_type: EnrichmentType,
        dry_run: bool = False,
        limit: int | None = None,
        fetched_since: str | None = None,
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
                    fetched_since=fetched_since,
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

    async def resolve_title_references(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> EnrichmentProgress:
        """Resolve TITLE:xxx entries in referenced_works to DOI/OpenAlex identifiers.

        Searches OpenAlex by title for each unique TITLE:xxx reference and
        replaces matched entries with proper identifiers.

        Args:
            dry_run: If True, only count papers without updating.
            limit: Maximum papers to process (None for all).

        Returns:
            EnrichmentProgress with final statistics.
        """
        enrichment_type = EnrichmentType.RESOLVE_TITLE_REFS
        progress = self._load_checkpoint(enrichment_type)
        title_cache = self._load_title_cache(enrichment_type)
        offset = progress.last_offset

        logger.info("Starting TITLE:xxx reference resolution...")

        while True:
            papers, next_offset = self.storage.get_papers_with_title_refs(
                limit=self.batch_size,
                offset=offset,
            )

            # Filter to papers not yet processed
            batch = [
                (pid, payload) for pid, payload in papers
                if pid not in progress.processed_point_ids
            ]

            if batch:
                if dry_run:
                    progress.total_to_process += len(batch)
                    logger.info(f"Found {len(batch)} papers with TITLE: refs (dry run)")
                else:
                    enriched = await self._resolve_title_batch(batch, progress, title_cache)
                    logger.info(
                        f"Batch: {enriched}/{len(batch)} resolved | "
                        f"Total: {progress.enriched} resolved, "
                        f"{progress.not_found} unresolvable"
                    )

            # Update checkpoint
            progress.last_offset = next_offset
            progress.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_resolve_checkpoint(progress, enrichment_type, title_cache)

            offset = next_offset
            if offset is None:
                break

            if limit and progress.processed >= limit:
                break

        logger.info(
            f"Title reference resolution complete: "
            f"{progress.enriched} resolved, {progress.not_found} unresolvable, "
            f"{progress.errors} errors"
        )
        return progress

    async def _resolve_title_batch(
        self,
        papers: list[tuple[str, dict]],
        progress: EnrichmentProgress,
        title_cache: dict[str, str | None],
    ) -> int:
        """Resolve TITLE:xxx refs in a batch of papers.

        Args:
            papers: List of (point_id, payload) tuples.
            progress: EnrichmentProgress to update.
            title_cache: Cache mapping TITLE:xxx -> resolved identifier or None.

        Returns:
            Number of papers with at least one resolved reference.
        """
        if not papers:
            return 0

        # Collect unique TITLE: values that aren't cached yet
        uncached_titles: set[str] = set()
        for _, payload in papers:
            refs = payload.get("referenced_works", [])
            for ref in refs:
                if ref.startswith("TITLE:") and ref not in title_cache:
                    uncached_titles.add(ref)

        # Lookup uncached titles in parallel
        if uncached_titles:
            titles_list = list(uncached_titles)
            tasks = [
                self.search_title_for_identifier(title_ref[6:])  # Strip "TITLE:" prefix
                for title_ref in titles_list
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for title_ref, result in zip(titles_list, results):
                if isinstance(result, APIRateLimitError):
                    # Don't cache rate limit errors — will retry next run
                    continue
                if isinstance(result, Exception):
                    logger.warning(f"Error resolving '{title_ref[:50]}': {result}")
                    continue
                # Cache result (None means not found, which IS cached)
                title_cache[title_ref] = result

        # Rebuild each paper's referenced_works with resolved entries
        enriched = 0
        updates: list[tuple[str, list[str]]] = []

        for point_id, payload in papers:
            refs = payload.get("referenced_works", [])
            new_refs = []
            changed = False
            has_uncached = False

            for ref in refs:
                if ref.startswith("TITLE:"):
                    if ref in title_cache:
                        resolved = title_cache[ref]
                        if resolved is not None:
                            new_refs.append(resolved)
                            changed = True
                        else:
                            # Not found in OpenAlex, keep original
                            new_refs.append(ref)
                            progress.not_found += 1
                    else:
                        # Rate-limited — not yet cached
                        new_refs.append(ref)
                        has_uncached = True
                else:
                    new_refs.append(ref)

            progress.processed += 1
            if has_uncached:
                # Don't mark as processed — will retry on next run
                progress.errors += 1
            else:
                progress.processed_point_ids.add(point_id)

            if changed:
                updates.append((point_id, new_refs))
                progress.enriched += 1
                enriched += 1

        # Batch update storage
        if updates:
            self.storage.batch_update_referenced_works(updates)

        return enriched

    def _load_title_cache(self, enrichment_type: EnrichmentType) -> dict[str, str | None]:
        """Load title resolution cache from checkpoint file.

        Args:
            enrichment_type: Type of enrichment.

        Returns:
            Dict mapping TITLE:xxx keys to resolved identifiers or None.
        """
        checkpoint_file = self._get_checkpoint_file(enrichment_type)
        if checkpoint_file.exists():
            with open(checkpoint_file) as f:
                data = json.load(f)
            return data.get("title_cache", {})
        return {}

    def _save_resolve_checkpoint(
        self,
        progress: EnrichmentProgress,
        enrichment_type: EnrichmentType,
        title_cache: dict[str, str | None],
    ) -> None:
        """Save progress and title cache to checkpoint file.

        Args:
            progress: EnrichmentProgress to save.
            enrichment_type: Type of enrichment.
            title_cache: Title resolution cache to persist.
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
            "title_cache": title_cache,
        }
        checkpoint_file = self._get_checkpoint_file(enrichment_type)
        with open(checkpoint_file, "w") as f:
            json.dump(data, f, indent=2)

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
