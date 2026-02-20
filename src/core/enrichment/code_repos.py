"""Code repository enrichment via PWC Archive and HuggingFace Papers API.

Enriches papers with links to their GitHub code repositories using two sources:

1. PWC Archive — Frozen HuggingFace dataset (pwc-archive/links-between-paper-and-code)
   with ~300K paper->repo mappings. Indexed by arXiv ID and normalized title.

2. HuggingFace Papers API — Live endpoint GET https://huggingface.co/api/papers/{arxiv_id}.
   Returns githubRepo, githubStars, githubRepoAddedBy. No auth required.

Strategy: Three-phase lookup per paper:
  (1) PWC archive by arXiv ID (extracted from source_id or DOI)
  (2) PWC archive by normalized title (for papers without arXiv ID)
  (3) HuggingFace API by arXiv ID (live, rate-limited, only if arXiv ID available)
"""

import asyncio
import io
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)

# PWC Archive Parquet file URL on HuggingFace Hub
PWC_PARQUET_URL = (
    "https://huggingface.co/datasets/pwc-archive/links-between-paper-and-code"
    "/resolve/main/data/train-00000-of-00001.parquet"
)

# HuggingFace Papers API
HF_PAPERS_API = "https://huggingface.co/api/papers"

# Pattern for arXiv DOI: 10.48550/arxiv.XXXX.XXXXX
_ARXIV_DOI_RE = re.compile(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", re.IGNORECASE)


@dataclass
class CodeRepoEnrichmentProgress:
    """Track code repository enrichment progress."""

    total_to_process: int = 0
    processed: int = 0
    enriched: int = 0
    not_found: int = 0
    errors: int = 0
    pwc_hits: int = 0
    pwc_title_hits: int = 0
    hf_hits: int = 0
    last_offset: str | None = None
    processed_point_ids: set[str] = field(default_factory=set)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_updated: str | None = None


def _normalize_title(title: str) -> str:
    """Normalize a paper title for matching.

    Lowercases, strips accents, removes non-alphanumeric, collapses whitespace.
    """
    title = title.lower().strip()
    # Remove accents
    title = unicodedata.normalize("NFKD", title)
    title = "".join(c for c in title if not unicodedata.combining(c))
    # Keep only alphanumeric and spaces
    title = re.sub(r"[^a-z0-9 ]", "", title)
    # Collapse whitespace
    title = re.sub(r"\s+", " ", title).strip()
    return title


class CodeRepoEnricher:
    """Enrich papers with GitHub code repository URLs."""

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        checkpoint_dir: Path | str | None = None,
        batch_size: int = 100,
        delay: float = 0.05,
        max_concurrent: int = 10,
    ):
        self.storage = storage or QdrantStorage()
        self.batch_size = batch_size
        self.delay = delay
        self.max_concurrent = max_concurrent
        self.checkpoint_dir = Path(checkpoint_dir or "data/core/checkpoints")
        self._checkpoint_file = self.checkpoint_dir / "code_repo_enrichment.json"
        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None
        # Two indexes built from PWC archive
        self._pwc_by_arxiv: dict[str, list[dict]] | None = None
        self._pwc_by_title: dict[str, list[dict]] | None = None

    async def __aenter__(self) -> "CodeRepoEnricher":
        """Enter async context."""
        self._client = httpx.AsyncClient(
            timeout=60.0,
            headers={
                "User-Agent": "LexiconArxiv/1.0 (Academic paper indexing)"
            },
        )
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self

    async def __aexit__(self, *args) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()

    async def _load_pwc_archive(self) -> None:
        """Download and parse the PWC archive Parquet file.

        Builds two lookup indexes:
        - _pwc_by_arxiv: arxiv_id -> [repo_info, ...]
        - _pwc_by_title: normalized_title -> [repo_info, ...]
        """
        import pyarrow.parquet as pq

        cache_path = Path("data/core/cache/pwc_archive.parquet")

        if cache_path.exists():
            logger.info(f"Loading PWC archive from cache: {cache_path}")
            table = pq.read_table(cache_path)
        else:
            logger.info("Downloading PWC archive from HuggingFace Hub...")
            response = await self._client.get(PWC_PARQUET_URL, follow_redirects=True)
            response.raise_for_status()
            data = response.content
            logger.info(f"Downloaded PWC archive: {len(data) / 1024 / 1024:.1f} MB")

            # Cache locally
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(data)
            logger.info(f"Cached PWC archive to {cache_path}")

            table = pq.read_table(io.BytesIO(data))

        # Build lookup dicts
        by_arxiv: dict[str, list[dict]] = {}
        by_title: dict[str, list[dict]] = {}
        df = table.to_pydict()

        arxiv_ids = df.get("paper_arxiv_id", [])
        titles = df.get("paper_title", [])
        repo_urls = df.get("repo_url", [])
        is_officials = df.get("is_official", [])
        frameworks = df.get("framework", [])

        for i in range(len(repo_urls)):
            url = repo_urls[i]
            if not url:
                continue

            repo_info = {
                "url": url,
                "is_official": bool(is_officials[i]) if i < len(is_officials) else False,
                "framework": frameworks[i] if i < len(frameworks) else None,
                "stars": None,
                "source": "pwc_archive",
            }

            # Index by arXiv ID
            arxiv_id = arxiv_ids[i] if i < len(arxiv_ids) else None
            if arxiv_id:
                by_arxiv.setdefault(arxiv_id, []).append(repo_info)

            # Index by normalized title
            title = titles[i] if i < len(titles) else None
            if title:
                norm = _normalize_title(title)
                if len(norm) > 10:  # Skip very short/empty titles
                    by_title.setdefault(norm, []).append(repo_info)

        self._pwc_by_arxiv = by_arxiv
        self._pwc_by_title = by_title
        logger.info(
            f"Loaded PWC archive: {len(by_arxiv)} papers by arXiv ID, "
            f"{len(by_title)} papers by title"
        )

    async def _lookup_hf_api(self, arxiv_id: str) -> list[dict] | None:
        """Look up code repo via HuggingFace Papers API.

        Args:
            arxiv_id: The arXiv ID to look up.

        Returns:
            List with single repo dict, or None if not found.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        url = f"{HF_PAPERS_API}/{arxiv_id}"

        try:
            response = await self._client.get(url)

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 30))
                logger.warning(f"HF rate limited, waiting {retry_after}s...")
                await asyncio.sleep(retry_after)
                return await self._lookup_hf_api(arxiv_id)

            response.raise_for_status()
            data = response.json()

            github_repo = data.get("githubRepo")
            if not github_repo:
                return None

            return [{
                "url": f"https://github.com/{github_repo}",
                "is_official": True,
                "framework": None,
                "stars": data.get("githubStars"),
                "source": "huggingface",
            }]

        except httpx.HTTPStatusError as e:
            logger.warning(f"HF API error for {arxiv_id}: {e}")
            return None
        except Exception as e:
            logger.warning(f"HF API error for {arxiv_id}: {e}")
            return None

    async def _hf_lookup_with_limit(self, arxiv_id: str) -> list[dict] | None:
        """Rate-limited HuggingFace API lookup."""
        async with self._semaphore:
            result = await self._lookup_hf_api(arxiv_id)
            await asyncio.sleep(self.delay)
            return result

    @staticmethod
    def _select_best_url(repos: list[dict]) -> str | None:
        """Select the best repo URL from a list of repos.

        Prefers official repos, then highest stars.
        """
        if not repos:
            return None

        # Sort: official first, then by stars descending
        sorted_repos = sorted(
            repos,
            key=lambda r: (
                r.get("is_official", False),
                r.get("stars") or 0,
            ),
            reverse=True,
        )
        return sorted_repos[0].get("url")

    async def enrich_code_repos(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> CodeRepoEnrichmentProgress:
        """Enrich papers with code repository URLs.

        Three-phase approach per paper:
        1. PWC archive lookup by arXiv ID (extracted from source_id or DOI)
        2. PWC archive lookup by normalized title
        3. HuggingFace API lookup by arXiv ID (live, only if arXiv ID available)

        Args:
            dry_run: Only count papers without updating.
            limit: Maximum papers to process.

        Returns:
            CodeRepoEnrichmentProgress with statistics.
        """
        progress = self._load_checkpoint()
        offset = progress.last_offset

        # Load PWC archive indexes (one-time)
        if self._pwc_by_arxiv is None:
            await self._load_pwc_archive()

        logger.info("Starting code repository enrichment...")

        while True:
            papers, next_offset = self.storage.get_papers_missing_code_repos(
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
                    f"Total: {progress.enriched} enriched "
                    f"(PWC-ID: {progress.pwc_hits}, PWC-title: {progress.pwc_title_hits}, "
                    f"HF: {progress.hf_hits}), "
                    f"{progress.not_found} not found"
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
            f"Code repo enrichment complete: {progress.enriched} enriched "
            f"(PWC-ID: {progress.pwc_hits}, PWC-title: {progress.pwc_title_hits}, "
            f"HF: {progress.hf_hits}), "
            f"{progress.not_found} not found, {progress.errors} errors"
        )
        return progress

    async def _enrich_batch(
        self,
        papers: list[tuple[str, dict]],
        progress: CodeRepoEnrichmentProgress,
    ) -> int:
        """Process a batch of papers through PWC archive (by ID + title) and HF API."""
        to_process = [
            (pid, payload)
            for pid, payload in papers
            if pid not in progress.processed_point_ids
        ]

        if not to_process:
            return 0

        enriched = 0
        updates: list[tuple[str, list[dict], str | None]] = []
        hf_lookups: list[tuple[str, str]] = []  # (point_id, arxiv_id)

        for point_id, payload in to_process:
            progress.processed += 1
            progress.processed_point_ids.add(point_id)

            arxiv_id = self._extract_arxiv_id(payload)
            title = payload.get("title") or ""

            # Phase 1: PWC archive by arXiv ID
            if arxiv_id and self._pwc_by_arxiv.get(arxiv_id):
                repos = self._pwc_by_arxiv[arxiv_id]
                best_url = self._select_best_url(repos)
                updates.append((point_id, repos, best_url))
                progress.enriched += 1
                progress.pwc_hits += 1
                enriched += 1
                continue

            # Phase 2: PWC archive by normalized title
            if title:
                norm_title = _normalize_title(title)
                if len(norm_title) > 10 and self._pwc_by_title.get(norm_title):
                    repos = self._pwc_by_title[norm_title]
                    best_url = self._select_best_url(repos)
                    updates.append((point_id, repos, best_url))
                    progress.enriched += 1
                    progress.pwc_title_hits += 1
                    enriched += 1
                    continue

            # Phase 3: Queue for HuggingFace API (only if we have arXiv ID)
            if arxiv_id:
                hf_lookups.append((point_id, arxiv_id))
            else:
                progress.not_found += 1

        # Phase 3: HuggingFace API for remaining papers with arXiv IDs
        if hf_lookups:
            tasks = [
                self._hf_lookup_with_limit(arxiv_id)
                for _, arxiv_id in hf_lookups
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for (point_id, arxiv_id), result in zip(hf_lookups, results):
                if isinstance(result, Exception):
                    logger.warning(f"HF API error for {arxiv_id}: {result}")
                    progress.errors += 1
                    continue

                if result is None:
                    progress.not_found += 1
                    continue

                best_url = self._select_best_url(result)
                updates.append((point_id, result, best_url))
                progress.enriched += 1
                progress.hf_hits += 1
                enriched += 1

        # Write all updates to Qdrant
        if updates:
            self.storage.batch_update_code_repos(updates)

        return enriched

    @staticmethod
    def _extract_arxiv_id(payload: dict) -> str | None:
        """Extract arXiv ID from paper payload.

        Checks source_id (arXiv:XXXX.XXXXX) and DOI (10.48550/arxiv.XXXX.XXXXX).
        """
        source_id = payload.get("source_id", "") or ""
        if source_id.lower().startswith("arxiv:"):
            return source_id[6:]

        doi = payload.get("doi", "") or ""
        m = _ARXIV_DOI_RE.search(doi)
        if m:
            return m.group(1)

        return None

    def _load_checkpoint(self) -> CodeRepoEnrichmentProgress:
        """Load checkpoint from file."""
        if self._checkpoint_file.exists():
            with open(self._checkpoint_file) as f:
                data = json.load(f)
            progress = CodeRepoEnrichmentProgress(
                total_to_process=data.get("total_to_process", 0),
                processed=data.get("processed", 0),
                enriched=data.get("enriched", 0),
                not_found=data.get("not_found", 0),
                errors=data.get("errors", 0),
                pwc_hits=data.get("pwc_hits", 0),
                pwc_title_hits=data.get("pwc_title_hits", 0),
                hf_hits=data.get("hf_hits", 0),
                last_offset=data.get("last_offset"),
                started_at=data.get("started_at", datetime.now(timezone.utc).isoformat()),
                last_updated=data.get("last_updated"),
            )
            progress.processed_point_ids = set(data.get("processed_point_ids", []))
            return progress
        return CodeRepoEnrichmentProgress()

    def _save_checkpoint(self, progress: CodeRepoEnrichmentProgress) -> None:
        """Save checkpoint to file."""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "total_to_process": progress.total_to_process,
            "processed": progress.processed,
            "enriched": progress.enriched,
            "not_found": progress.not_found,
            "errors": progress.errors,
            "pwc_hits": progress.pwc_hits,
            "pwc_title_hits": progress.pwc_title_hits,
            "hf_hits": progress.hf_hits,
            "last_offset": progress.last_offset,
            "processed_point_ids": list(progress.processed_point_ids),
            "started_at": progress.started_at,
            "last_updated": progress.last_updated,
        }
        with open(self._checkpoint_file, "w") as f:
            json.dump(data, f, indent=2)

    def clear_checkpoint(self) -> None:
        """Clear checkpoint for fresh start."""
        if self._checkpoint_file.exists():
            self._checkpoint_file.unlink()
            logger.info("Code repo enrichment checkpoint cleared")
