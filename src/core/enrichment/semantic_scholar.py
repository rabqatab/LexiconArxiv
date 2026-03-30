"""Semantic Scholar API integration for citation enrichment.

Semantic Scholar often has better coverage for ML/AI papers than OpenAlex,
especially for recent conference papers (NeurIPS, ICML, ICLR, ACL).

API Documentation: https://api.semanticscholar.org/api-docs/

Authentication:
    Set one of these environment variables for higher rate limits:
    - S2_API_KEYS: Comma-separated API keys for multi-key rotation
    - S2_API_KEY: Single Semantic Scholar API key
    - SEMANTIC_SCHOLAR_API_KEY: Alternative env var name (single key)

    Get a free API key at: https://www.semanticscholar.org/product/api#api-key

Rate Limits:
    - Without API key: 100 requests per 5 minutes (~0.33 req/sec)
    - With API key: 1 request per second per key (cumulative across all endpoints)
    - With N keys: N concurrent requests, each key limited to 1 req/sec
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.core.constants import S2_BASE_URL, get_s2_api_key, get_s2_api_keys
from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


@dataclass
class S2EnrichmentProgress:
    """Track Semantic Scholar enrichment progress."""

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


class SemanticScholarEnricher:
    """Enrich papers with citation data from Semantic Scholar."""

    # Rate limit defaults
    # S2 API limit with key: 1 req/sec cumulative across all endpoints
    DEFAULT_DELAY_NO_KEY = 3.0  # ~20 req/min without key (conservative)
    DEFAULT_DELAY_WITH_KEY = 1.1  # 1 req/sec with key (slightly under limit for safety)
    DEFAULT_CONCURRENT_NO_KEY = 1
    DEFAULT_CONCURRENT_WITH_KEY = 1  # Must be 1 due to cumulative rate limit

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        api_key: str | None = None,
        api_keys: list[str] | None = None,
        checkpoint_dir: Path | str | None = None,
        batch_size: int = 100,
        delay: float | None = None,  # Auto-set based on API key
        max_concurrent: int | None = None,  # Auto-set based on API key
    ):
        """Initialize SemanticScholarEnricher.

        Args:
            storage: QdrantStorage instance.
            api_key: S2 API key for higher rate limits (backward compat, single key).
                     If not provided, checks S2_API_KEY or SEMANTIC_SCHOLAR_API_KEY env vars.
                     Get one at: https://www.semanticscholar.org/product/api#api-key
            api_keys: List of S2 API keys for multi-key rotation. Takes precedence
                      over api_key. Each key allows 1 req/sec, so N keys = N concurrent.
            checkpoint_dir: Directory for checkpoint files.
            batch_size: Papers per batch.
            delay: Delay between requests in seconds.
                   If None, auto-set: 1.1s with key, 3.0s without.
            max_concurrent: Max concurrent requests.
                            If None, auto-set: len(keys) with keys, 1 without.
        """
        self.storage = storage or QdrantStorage()

        # Resolve API keys: api_keys > api_key > env
        if api_keys:
            self.api_keys = api_keys
        elif api_key:
            self.api_keys = [api_key]
        else:
            self.api_keys = get_s2_api_keys()

        # Backward compat: expose first key as self.api_key
        self.api_key = self.api_keys[0] if self.api_keys else None

        # Auto-adjust rate limits based on API key presence
        if self.api_keys:
            self.delay = delay if delay is not None else self.DEFAULT_DELAY_WITH_KEY
            self.max_concurrent = max_concurrent if max_concurrent is not None else len(self.api_keys)
        else:
            self.delay = delay if delay is not None else self.DEFAULT_DELAY_NO_KEY
            self.max_concurrent = max_concurrent if max_concurrent is not None else self.DEFAULT_CONCURRENT_NO_KEY

        self.batch_size = batch_size
        self._key_index = 0  # Round-robin counter

        self.checkpoint_dir = Path(checkpoint_dir or "data/core/checkpoints")
        self._checkpoint_file_doi = self.checkpoint_dir / "s2_doi_enrichment.json"
        self._checkpoint_file_title = self.checkpoint_dir / "s2_title_enrichment.json"
        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None

    async def __aenter__(self) -> "SemanticScholarEnricher":
        """Enter async context."""
        headers = {
            "User-Agent": "LexiconArxiv/1.0 (Academic paper indexing; https://github.com/your-repo)"
        }

        if self.api_keys:
            logger.info(
                f"Using {len(self.api_keys)} Semantic Scholar API key(s). "
                f"Rate: {len(self.api_keys)} req/sec effective, "
                f"{self.max_concurrent} concurrent"
            )
        else:
            logger.warning(
                f"No S2 API key set. Using conservative rate limits: "
                f"{1/self.delay:.2f} req/sec, {self.max_concurrent} concurrent. "
                f"Set S2_API_KEYS env var for faster processing."
            )

        self._client = httpx.AsyncClient(timeout=30.0, headers=headers)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self

    async def __aexit__(self, *args) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()

    def _get_next_key(self) -> str | None:
        """Round-robin through API keys."""
        if not self.api_keys:
            return None
        key = self.api_keys[self._key_index % len(self.api_keys)]
        self._key_index += 1
        return key

    async def fetch_by_doi(self, doi: str) -> dict[str, Any] | None:
        """Fetch paper data from S2 by DOI.

        Args:
            doi: The DOI to look up.

        Returns:
            Dict with 'references' list or None if not found.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Clean DOI
        if doi.startswith("https://doi.org/"):
            doi = doi[16:]
        elif doi.startswith("http://doi.org/"):
            doi = doi[15:]

        url = f"{S2_BASE_URL}/paper/DOI:{doi}"
        params = {"fields": "paperId,title,references.paperId,references.title,references.externalIds"}

        try:
            key = self._get_next_key()
            req_headers = {"x-api-key": key} if key else {}
            response = await self._client.get(url, params=params, headers=req_headers)

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                # Rate limited - wait and retry
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"S2 rate limited, waiting {retry_after}s...")
                await asyncio.sleep(retry_after)
                return await self.fetch_by_doi(doi)

            response.raise_for_status()
            data = response.json()

            refs = data.get("references") or []  # Handle None case
            if not refs:
                return {"references": [], "s2_id": data.get("paperId")}

            # Extract reference IDs (prefer DOI, fallback to S2 ID)
            ref_ids = []
            for ref in refs:
                if ref is None:
                    continue
                ext_ids = ref.get("externalIds") or {}
                if ext_ids.get("DOI"):
                    ref_ids.append(f"DOI:{ext_ids['DOI']}")
                elif ref.get("paperId"):
                    ref_ids.append(f"S2:{ref['paperId']}")

            return {
                "references": ref_ids,
                "s2_id": data.get("paperId"),
            }

        except httpx.HTTPStatusError as e:
            logger.warning(f"S2 HTTP error for DOI {doi}: {e}")
            return None
        except Exception as e:
            logger.warning(f"S2 error for DOI {doi}: {e}")
            return None

    async def fetch_by_title(self, title: str, min_refs: int = 1) -> dict[str, Any] | None:
        """Search S2 by title and return paper with references.

        Args:
            title: Paper title to search.
            min_refs: Minimum references required.

        Returns:
            Dict with 'references', 'doi', 's2_id' or None.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        url = f"{S2_BASE_URL}/paper/search"
        params = {
            "query": title,
            "fields": "paperId,title,externalIds,references.paperId,references.externalIds",
            "limit": 5,
        }

        try:
            key = self._get_next_key()
            req_headers = {"x-api-key": key} if key else {}
            response = await self._client.get(url, params=params, headers=req_headers)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"S2 rate limited, waiting {retry_after}s...")
                await asyncio.sleep(retry_after)
                return await self.fetch_by_title(title, min_refs)

            response.raise_for_status()
            data = response.json()

            results = data.get("data", [])
            if not results:
                return None

            # Find best match with sufficient references
            title_lower = title.lower().strip()
            for result in results:
                result_title = (result.get("title") or "").lower().strip()
                refs = result.get("references") or []  # Handle None case

                # Check title similarity
                if result_title == title_lower or (
                    len(result_title) > 20
                    and (result_title in title_lower or title_lower in result_title)
                ):
                    if len(refs) >= min_refs:
                        # Extract reference IDs
                        ref_ids = []
                        for ref in refs:
                            if ref is None:
                                continue
                            ext_ids = ref.get("externalIds") or {}
                            if ext_ids.get("DOI"):
                                ref_ids.append(f"DOI:{ext_ids['DOI']}")
                            elif ref.get("paperId"):
                                ref_ids.append(f"S2:{ref['paperId']}")

                        ext_ids = result.get("externalIds") or {}
                        return {
                            "references": ref_ids,
                            "doi": ext_ids.get("DOI"),
                            "s2_id": result.get("paperId"),
                        }

            return None

        except httpx.HTTPStatusError as e:
            logger.warning(f"S2 search error for '{title[:30]}': {e}")
            return None
        except Exception as e:
            logger.warning(f"S2 error for '{title[:30]}': {e}")
            return None

    async def _fetch_with_limit(self, doi: str) -> dict[str, Any] | None:
        """Fetch with rate limiting."""
        async with self._semaphore:
            result = await self.fetch_by_doi(doi)
            await asyncio.sleep(self.delay)
            return result

    async def _search_with_limit(self, title: str, min_refs: int = 1) -> dict[str, Any] | None:
        """Search with rate limiting."""
        async with self._semaphore:
            result = await self.fetch_by_title(title, min_refs)
            await asyncio.sleep(self.delay)
            return result

    async def enrich_by_doi(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> S2EnrichmentProgress:
        """Enrich papers with DOIs using Semantic Scholar.

        This is a fallback for papers where OpenAlex didn't have citation data.

        Args:
            dry_run: Only count papers without updating.
            limit: Maximum papers to process.

        Returns:
            S2EnrichmentProgress with statistics.
        """
        progress = self._load_checkpoint(by_title=False)
        offset = progress.last_offset

        logger.info("Starting Semantic Scholar DOI-based enrichment...")

        while True:
            # Get papers with DOI but no refs (OpenAlex failed)
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
                enriched = await self._enrich_batch_by_doi(papers, progress)
                logger.info(
                    f"Batch: {enriched}/{len(papers)} enriched | "
                    f"Total: {progress.enriched} enriched, "
                    f"{progress.not_found} not found, {progress.no_refs} no refs"
                )

            progress.last_offset = next_offset
            progress.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_checkpoint(progress, by_title=False)

            offset = next_offset
            if offset is None:
                break

            if limit and progress.processed >= limit:
                break

        logger.info(
            f"S2 DOI enrichment complete: {progress.enriched} enriched, "
            f"{progress.not_found} not found, {progress.no_refs} no refs, "
            f"{progress.errors} errors"
        )
        return progress

    async def enrich_by_title(
        self,
        dry_run: bool = False,
        limit: int | None = None,
        venues: list[str] | None = None,
        min_refs: int = 1,
    ) -> S2EnrichmentProgress:
        """Enrich papers without DOIs by searching S2 by title.

        Args:
            dry_run: Only count papers without updating.
            limit: Maximum papers to process.
            venues: Filter by venue names.
            min_refs: Minimum refs required for match.

        Returns:
            S2EnrichmentProgress with statistics.
        """
        progress = self._load_checkpoint(by_title=True)
        offset = progress.last_offset

        logger.info("Starting Semantic Scholar title-based enrichment...")

        while True:
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
                enriched = await self._enrich_batch_by_title(papers, progress, min_refs)
                logger.info(
                    f"Batch: {enriched}/{len(papers)} enriched | "
                    f"Total: {progress.enriched} enriched, "
                    f"{progress.not_found} not found"
                )

            progress.last_offset = next_offset
            progress.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_checkpoint(progress, by_title=True)

            offset = next_offset
            if offset is None:
                break

            if limit and progress.processed >= limit:
                break

        logger.info(
            f"S2 title enrichment complete: {progress.enriched} enriched, "
            f"{progress.not_found} not found, {progress.errors} errors"
        )
        return progress

    async def _enrich_batch_by_doi(
        self,
        papers: list[tuple[str, dict]],
        progress: S2EnrichmentProgress,
    ) -> int:
        """Enrich batch using DOI lookup."""
        to_process = [
            (pid, payload)
            for pid, payload in papers
            if payload.get("doi") and pid not in progress.processed_point_ids
        ]

        if not to_process:
            return 0

        tasks = [self._fetch_with_limit(payload.get("doi")) for _, payload in to_process]
        results = await asyncio.gather(*tasks, return_exceptions=True)

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

            refs = result.get("references", [])
            if refs:
                updates.append((point_id, refs))
                progress.enriched += 1
                enriched += 1
                logger.debug(f"S2 enriched {payload.get('doi')}: {len(refs)} refs")
            else:
                progress.no_refs += 1

        if updates:
            self.storage.batch_update_referenced_works(updates)

        return enriched

    async def _enrich_batch_by_title(
        self,
        papers: list[tuple[str, dict]],
        progress: S2EnrichmentProgress,
        min_refs: int = 1,
    ) -> int:
        """Enrich batch using title search."""
        to_process = [
            (pid, payload)
            for pid, payload in papers
            if payload.get("title") and pid not in progress.processed_point_ids
        ]

        if not to_process:
            return 0

        tasks = [
            self._search_with_limit(payload.get("title"), min_refs)
            for _, payload in to_process
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched = 0
        updates = []

        for (point_id, payload), result in zip(to_process, results):
            progress.processed += 1
            progress.processed_point_ids.add(point_id)

            if isinstance(result, Exception):
                progress.errors += 1
                continue

            if result is None:
                progress.not_found += 1
                continue

            refs = result.get("references", [])
            doi = result.get("doi")
            if refs:
                if doi:
                    updates.append((point_id, doi, refs))
                else:
                    # No DOI found, just update refs
                    self.storage.batch_update_referenced_works([(point_id, refs)])
                progress.enriched += 1
                enriched += 1
            else:
                progress.not_found += 1

        if updates:
            self.storage.batch_update_papers_with_doi_and_refs(updates)

        return enriched

    def _load_checkpoint(self, by_title: bool = False) -> S2EnrichmentProgress:
        """Load checkpoint from file."""
        checkpoint_file = self._checkpoint_file_title if by_title else self._checkpoint_file_doi
        if checkpoint_file.exists():
            with open(checkpoint_file) as f:
                data = json.load(f)
            progress = S2EnrichmentProgress(
                total_to_process=data.get("total_to_process", 0),
                processed=data.get("processed", 0),
                enriched=data.get("enriched", 0),
                not_found=data.get("not_found", 0),
                no_refs=data.get("no_refs", 0),
                errors=data.get("errors", 0),
                last_offset=data.get("last_offset"),
                started_at=data.get("started_at", datetime.now(timezone.utc).isoformat()),
                last_updated=data.get("last_updated"),
            )
            progress.processed_point_ids = set(data.get("processed_point_ids", []))
            return progress
        return S2EnrichmentProgress()

    def _save_checkpoint(self, progress: S2EnrichmentProgress, by_title: bool = False) -> None:
        """Save checkpoint to file."""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_file = self._checkpoint_file_title if by_title else self._checkpoint_file_doi
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
        with open(checkpoint_file, "w") as f:
            json.dump(data, f, indent=2)

    def clear_checkpoint(self, by_title: bool = False) -> None:
        """Clear checkpoint for fresh start."""
        checkpoint_file = self._checkpoint_file_title if by_title else self._checkpoint_file_doi
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            mode = "title" if by_title else "DOI"
            logger.info(f"S2 {mode} enrichment checkpoint cleared")

    def clear_all_checkpoints(self) -> None:
        """Clear all S2 checkpoints."""
        self.clear_checkpoint(by_title=False)
        self.clear_checkpoint(by_title=True)
