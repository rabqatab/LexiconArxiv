"""Code repository enrichment via GitHub API search.

Two-tier search strategy:
  Tier A: Search for arXiv ID in README files (high precision)
  Tier B: Search repositories by paper title (with validation heuristics)

Rate limits:
  - With token: 30 search requests/min
  - Without token: 10 search requests/min
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.core.constants import GITHUB_TOKEN_ENV, get_github_token
from src.core.enrichment.code_repos import CodeRepoEnricher
from src.core.enrichment.grobid_code_repos import GITHUB_BLOCKLIST
from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"

# Pattern for arXiv DOI: 10.48550/arxiv.XXXX.XXXXX
_ARXIV_DOI_RE = re.compile(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", re.IGNORECASE)

# Common English stop words for title similarity
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "must",
    "not", "no", "nor", "so", "as", "if", "than", "that", "this",
    "these", "those", "it", "its", "we", "our", "us", "via", "using",
})


@dataclass
class GitHubSearchProgress:
    """Track GitHub search enrichment progress."""

    total_to_process: int = 0
    processed: int = 0
    enriched: int = 0
    tier_a_hits: int = 0
    tier_b_hits: int = 0
    not_found: int = 0
    rate_limited: int = 0
    errors: int = 0
    last_offset: str | None = None
    processed_point_ids: set[str] = field(default_factory=set)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_updated: str | None = None


class GitHubSearchEnricher:
    """Enrich papers with code repos via GitHub API search."""

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        github_token: str | None = None,
        checkpoint_dir: Path | str | None = None,
        batch_size: int = 50,
        max_concurrent: int = 1,
    ):
        self.storage = storage or QdrantStorage()
        self.github_token = github_token or get_github_token()
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent

        # Rate limits: 30/min with token, 10/min without
        rate_limit = 30 if self.github_token else 10
        self._request_interval = 60.0 / rate_limit

        self.checkpoint_dir = Path(checkpoint_dir or "data/core/checkpoints")
        self._checkpoint_file = self.checkpoint_dir / "github_search_enrichment.json"
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "GitHubSearchEnricher":
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "LexiconArxiv/1.0 (Academic paper indexing)",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            logger.info("GitHub API: authenticated (30 req/min)")
        else:
            logger.warning(
                f"GitHub API: unauthenticated (10 req/min). "
                f"Set {GITHUB_TOKEN_ENV} for higher rate limits."
            )

        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers=headers,
        )

        # Verify token validity
        if self.github_token:
            try:
                resp = await self._client.get(f"{GITHUB_API_BASE}/rate_limit")
                if resp.status_code == 200:
                    data = resp.json()
                    search_remaining = data.get("resources", {}).get("search", {}).get("remaining", "?")
                    logger.info(f"GitHub search API: {search_remaining} requests remaining")
                elif resp.status_code == 401:
                    logger.warning("GitHub token is invalid, falling back to unauthenticated")
                    self.github_token = None
                    self._request_interval = 60.0 / 10
            except Exception as e:
                logger.warning(f"Could not check GitHub rate limit: {e}")

        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    # =========================================================================
    # Rate-limited GitHub API request
    # =========================================================================

    async def _rate_limited_request(
        self, url: str, params: dict | None = None
    ) -> dict | None:
        """Make a rate-limited GitHub API request with Retry-After handling."""
        if not self._client:
            raise RuntimeError("Client not initialized.")

        await asyncio.sleep(self._request_interval)

        try:
            response = await self._client.get(url, params=params)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 403:
                # Rate limited
                retry_after = int(response.headers.get("Retry-After", 60))
                reset_at = response.headers.get("X-RateLimit-Reset")
                if reset_at:
                    wait = max(0, int(reset_at) - int(datetime.now(timezone.utc).timestamp())) + 1
                    retry_after = min(retry_after, wait)
                logger.warning(f"GitHub rate limited, waiting {retry_after}s...")
                await asyncio.sleep(retry_after)
                return await self._rate_limited_request(url, params)

            if response.status_code == 422:
                # Unprocessable entity (query too long, etc.)
                logger.debug(f"GitHub search returned 422 for {params}")
                return None

            logger.warning(f"GitHub API returned {response.status_code}: {url}")
            return None

        except httpx.TimeoutException:
            logger.warning(f"GitHub API timeout: {url}")
            return None
        except Exception as e:
            logger.warning(f"GitHub API error: {e}")
            return None

    # =========================================================================
    # Tier A: arXiv ID in README (high precision)
    # =========================================================================

    async def _search_tier_a(self, arxiv_id: str) -> list[dict] | None:
        """Search for repos containing arXiv ID in their README.

        High precision: a repo that mentions the paper's arXiv ID in its
        README is very likely the paper's own implementation.
        """
        data = await self._rate_limited_request(
            f"{GITHUB_API_BASE}/search/code",
            params={
                "q": f"{arxiv_id} filename:README.md",
                "per_page": 5,
            },
        )

        if not data or data.get("total_count", 0) == 0:
            return None

        results = []
        blocklist_lower = {b.lower() for b in GITHUB_BLOCKLIST}

        for item in data.get("items", []):
            repo = item.get("repository", {})
            full_name = repo.get("full_name", "")

            if full_name.lower() in blocklist_lower:
                continue

            if repo.get("fork", False):
                continue

            results.append({
                "url": f"https://github.com/{full_name}",
                "is_official": True,
                "framework": None,
                "stars": repo.get("stargazers_count"),
                "source": "github_search_code",
            })

        return results if results else None

    # =========================================================================
    # Tier B: Title search with validation heuristics
    # =========================================================================

    async def _search_tier_b(
        self, title: str, year: int | None
    ) -> list[dict] | None:
        """Search GitHub repositories by paper title with validation.

        Validation heuristics:
        - Skip forks with < 10 stars
        - Temporal check: repo created within [year-1, year+2]
        - Title similarity: >= 40% of significant words in repo name+description
        """
        # Build search query from title (truncate to avoid 422)
        query_words = title.split()[:12]
        query = " ".join(query_words)

        data = await self._rate_limited_request(
            f"{GITHUB_API_BASE}/search/repositories",
            params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": 10,
            },
        )

        if not data or data.get("total_count", 0) == 0:
            return None

        # Extract significant title words for similarity check
        title_words = set()
        for w in title.lower().split():
            w = re.sub(r"[^a-z0-9]", "", w)
            if w and w not in _STOP_WORDS and len(w) > 2:
                title_words.add(w)

        if not title_words:
            return None

        results = []
        blocklist_lower = {b.lower() for b in GITHUB_BLOCKLIST}

        for repo in data.get("items", []):
            full_name = repo.get("full_name", "")

            # Blocklist check
            if full_name.lower() in blocklist_lower:
                continue

            # Skip forks with low stars
            stars = repo.get("stargazers_count", 0) or 0
            if repo.get("fork", False) and stars < 10:
                continue

            # Temporal check
            if year is not None:
                created_at = repo.get("created_at", "")
                if created_at:
                    try:
                        repo_year = int(created_at[:4])
                        if not (year - 1 <= repo_year <= year + 2):
                            continue
                    except (ValueError, IndexError):
                        pass

            # Title similarity check
            repo_text = (
                f"{repo.get('name', '')} {repo.get('description', '') or ''}"
            ).lower()
            repo_words = set()
            for w in repo_text.split():
                w = re.sub(r"[^a-z0-9]", "", w)
                if w and len(w) > 2:
                    repo_words.add(w)
            # Also check hyphenated name parts
            for w in repo.get("name", "").lower().replace("-", " ").replace("_", " ").split():
                w = re.sub(r"[^a-z0-9]", "", w)
                if w and len(w) > 2:
                    repo_words.add(w)

            overlap = title_words & repo_words
            similarity = len(overlap) / len(title_words) if title_words else 0

            if similarity < 0.4:
                continue

            results.append({
                "url": f"https://github.com/{full_name}",
                "is_official": False,  # Lower confidence for title-based matches
                "framework": None,
                "stars": stars,
                "source": "github_search_repo",
            })

        return results if results else None

    # =========================================================================
    # Combined lookup
    # =========================================================================

    async def _enrich_one(self, payload: dict) -> tuple[list[dict] | None, str]:
        """Combined lookup: Tier A first, then Tier B.

        Returns:
            (repos_or_none, tier_hit_string)
        """
        arxiv_id = self._extract_arxiv_id(payload)
        title = payload.get("title") or ""
        year = payload.get("year")

        # Tier A: arXiv ID in README
        if arxiv_id:
            repos = await self._search_tier_a(arxiv_id)
            if repos:
                return repos, "tier_a"

        # Tier B: Title search
        if title and len(title) > 10:
            repos = await self._search_tier_b(title, year)
            if repos:
                return repos, "tier_b"

        return None, "not_found"

    @staticmethod
    def _extract_arxiv_id(payload: dict) -> str | None:
        """Extract arXiv ID from paper payload."""
        source_id = payload.get("source_id", "") or ""
        if source_id.lower().startswith("arxiv:"):
            return source_id[6:]

        doi = payload.get("doi", "") or ""
        m = _ARXIV_DOI_RE.search(doi)
        if m:
            return m.group(1)

        return None

    # =========================================================================
    # Batch processing + main entry
    # =========================================================================

    async def _enrich_batch(
        self,
        papers: list[tuple[str, dict]],
        progress: GitHubSearchProgress,
    ) -> int:
        """Process a batch of papers sequentially (due to rate limits)."""
        to_process = [
            (pid, payload)
            for pid, payload in papers
            if pid not in progress.processed_point_ids
        ]

        if not to_process:
            return 0

        enriched = 0
        updates: list[tuple[str, list[dict], str | None]] = []

        for point_id, payload in to_process:
            progress.processed += 1
            progress.processed_point_ids.add(point_id)

            try:
                repos, tier = await self._enrich_one(payload)

                if repos:
                    best_url = CodeRepoEnricher._select_best_url(repos)
                    updates.append((point_id, repos, best_url))
                    progress.enriched += 1
                    enriched += 1
                    if tier == "tier_a":
                        progress.tier_a_hits += 1
                    elif tier == "tier_b":
                        progress.tier_b_hits += 1
                else:
                    progress.not_found += 1

            except Exception as e:
                logger.warning(f"Error processing {point_id}: {e}")
                progress.errors += 1

        # Write all updates to Qdrant
        if updates:
            self.storage.batch_update_code_repos(updates)

        return enriched

    async def enrich_code_repos_via_github(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> GitHubSearchProgress:
        """Enrich papers with code repos via GitHub API search.

        Args:
            dry_run: Only count eligible papers without searching.
            limit: Maximum papers to process.

        Returns:
            GitHubSearchProgress with statistics.
        """
        progress = self._load_checkpoint()
        offset = progress.last_offset

        logger.info("Starting GitHub search code repository enrichment...")

        while True:
            papers, next_offset = self.storage.get_papers_missing_code_repos_with_year(
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
                    f"(Tier-A: {progress.tier_a_hits}, Tier-B: {progress.tier_b_hits}), "
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
            f"GitHub search enrichment complete: {progress.enriched} enriched "
            f"(Tier-A: {progress.tier_a_hits}, Tier-B: {progress.tier_b_hits}), "
            f"{progress.not_found} not found, {progress.errors} errors"
        )
        return progress

    # =========================================================================
    # Checkpoint
    # =========================================================================

    def _load_checkpoint(self) -> GitHubSearchProgress:
        if self._checkpoint_file.exists():
            with open(self._checkpoint_file) as f:
                data = json.load(f)
            progress = GitHubSearchProgress(
                total_to_process=data.get("total_to_process", 0),
                processed=data.get("processed", 0),
                enriched=data.get("enriched", 0),
                tier_a_hits=data.get("tier_a_hits", 0),
                tier_b_hits=data.get("tier_b_hits", 0),
                not_found=data.get("not_found", 0),
                rate_limited=data.get("rate_limited", 0),
                errors=data.get("errors", 0),
                last_offset=data.get("last_offset"),
                started_at=data.get(
                    "started_at", datetime.now(timezone.utc).isoformat()
                ),
                last_updated=data.get("last_updated"),
            )
            progress.processed_point_ids = set(
                data.get("processed_point_ids", [])
            )
            return progress
        return GitHubSearchProgress()

    def _save_checkpoint(self, progress: GitHubSearchProgress) -> None:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "total_to_process": progress.total_to_process,
            "processed": progress.processed,
            "enriched": progress.enriched,
            "tier_a_hits": progress.tier_a_hits,
            "tier_b_hits": progress.tier_b_hits,
            "not_found": progress.not_found,
            "rate_limited": progress.rate_limited,
            "errors": progress.errors,
            "last_offset": progress.last_offset,
            "processed_point_ids": list(progress.processed_point_ids),
            "started_at": progress.started_at,
            "last_updated": progress.last_updated,
        }
        with open(self._checkpoint_file, "w") as f:
            json.dump(data, f, indent=2)

    def clear_checkpoint(self) -> None:
        if self._checkpoint_file.exists():
            self._checkpoint_file.unlink()
            logger.info("GitHub search enrichment checkpoint cleared")
