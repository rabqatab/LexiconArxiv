"""Reference resolution pipeline for building citation graphs.

Post-processes extracted `referenced_works` to build a citation graph by
resolving raw identifiers (DOI, arXiv, TITLE) to internal Qdrant paper IDs.

Pipeline Steps:
1. Normalize - Fix duplicate prefixes, case normalization
2. arXiv→DOI - Resolve arXiv IDs to DOIs via OpenAlex
3. Resolve to IDs - Map identifiers to internal Qdrant point IDs
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.core.constants import OPENALEX_BASE_URL
from src.core.deduplication import Deduplicator
from src.core.enrichment.base import OpenAlexMixin
from src.core.resolution.normalizer import IdentifierNormalizer, IdentifierType
from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


@dataclass
class ResolutionProgress:
    """Track reference resolution progress."""

    total_papers: int = 0
    processed: int = 0
    updated: int = 0
    skipped: int = 0  # Already processed
    errors: int = 0
    last_offset: str | None = None
    processed_point_ids: set[str] = field(default_factory=set)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_updated: str | None = None

    # Step-specific stats
    refs_normalized: int = 0
    arxiv_resolved: int = 0
    dois_resolved: int = 0
    openalex_resolved: int = 0  # OpenAlex Work IDs resolved
    titles_resolved: int = 0
    external_added: int = 0  # Papers added from external search
    stubs_created: int = 0  # Stub papers created for unresolved refs
    stubs_updated: int = 0  # Existing stubs updated with new citations


class ReferenceResolver(OpenAlexMixin):
    """Resolve raw reference identifiers to internal paper IDs.

    Three-step pipeline:
    1. normalize_references - Fix malformed identifiers
    2. resolve_arxiv_to_doi - Convert arXiv refs to DOIs via OpenAlex
    3. resolve_to_internal_ids - Map to Qdrant point IDs
    """

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        email: str | None = None,
        api_key: str | None = None,
        checkpoint_dir: Path | str | None = None,
        batch_size: int = 100,
        delay: float = 0.1,
        max_concurrent: int = 5,
    ):
        """Initialize ReferenceResolver.

        Args:
            storage: QdrantStorage instance.
            email: OpenAlex email for polite pool.
            api_key: OpenAlex API key for higher limits.
            checkpoint_dir: Directory for checkpoint files.
            batch_size: Papers per batch.
            delay: Delay between API calls.
            max_concurrent: Max concurrent API requests.
        """
        self.storage = storage or QdrantStorage()
        self._init_openalex(email, api_key)
        self.batch_size = batch_size
        self.delay = delay
        self.max_concurrent = max_concurrent

        self.checkpoint_dir = Path(checkpoint_dir or "data/core/checkpoints")
        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None

        # In-memory indexes (built on demand)
        self._doi_to_point_id: dict[str, str] | None = None
        self._arxiv_to_point_id: dict[str, str] | None = None
        self._openalex_to_point_id: dict[str, str] | None = None
        self._title_to_point_id: dict[str, str] | None = None

    async def __aenter__(self) -> "ReferenceResolver":
        """Enter async context."""
        self._client = httpx.AsyncClient(timeout=30.0)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self

    async def __aexit__(self, *args) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()

    # =========================================================================
    # Checkpoint Management
    # =========================================================================

    def _get_checkpoint_file(self, step: str) -> Path:
        """Get checkpoint file path for a resolution step."""
        return self.checkpoint_dir / f"ref_{step}.json"

    def _load_checkpoint(self, step: str) -> ResolutionProgress:
        """Load progress from checkpoint file."""
        checkpoint_file = self._get_checkpoint_file(step)
        if checkpoint_file.exists():
            with open(checkpoint_file) as f:
                data = json.load(f)
            progress = ResolutionProgress(
                total_papers=data.get("total_papers", 0),
                processed=data.get("processed", 0),
                updated=data.get("updated", 0),
                skipped=data.get("skipped", 0),
                errors=data.get("errors", 0),
                last_offset=data.get("last_offset"),
                started_at=data.get(
                    "started_at", datetime.now(timezone.utc).isoformat()
                ),
                last_updated=data.get("last_updated"),
                refs_normalized=data.get("refs_normalized", 0),
                arxiv_resolved=data.get("arxiv_resolved", 0),
                dois_resolved=data.get("dois_resolved", 0),
                openalex_resolved=data.get("openalex_resolved", 0),
                titles_resolved=data.get("titles_resolved", 0),
                external_added=data.get("external_added", 0),
                stubs_created=data.get("stubs_created", 0),
                stubs_updated=data.get("stubs_updated", 0),
            )
            progress.processed_point_ids = set(data.get("processed_point_ids", []))
            return progress
        return ResolutionProgress()

    def _save_checkpoint(self, progress: ResolutionProgress, step: str) -> None:
        """Save progress to checkpoint file."""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "total_papers": progress.total_papers,
            "processed": progress.processed,
            "updated": progress.updated,
            "skipped": progress.skipped,
            "errors": progress.errors,
            "last_offset": progress.last_offset,
            "processed_point_ids": list(progress.processed_point_ids),
            "started_at": progress.started_at,
            "last_updated": progress.last_updated,
            "refs_normalized": progress.refs_normalized,
            "arxiv_resolved": progress.arxiv_resolved,
            "dois_resolved": progress.dois_resolved,
            "openalex_resolved": progress.openalex_resolved,
            "titles_resolved": progress.titles_resolved,
            "external_added": progress.external_added,
            "stubs_created": progress.stubs_created,
            "stubs_updated": progress.stubs_updated,
        }
        checkpoint_file = self._get_checkpoint_file(step)
        with open(checkpoint_file, "w") as f:
            json.dump(data, f, indent=2)

    def clear_checkpoint(self, step: str) -> None:
        """Clear checkpoint for a step.

        Args:
            step: Step name ('normalize', 'arxiv', 'internal', or 'all').
        """
        if step == "all":
            for s in ["normalize", "arxiv", "internal"]:
                checkpoint_file = self._get_checkpoint_file(s)
                if checkpoint_file.exists():
                    checkpoint_file.unlink()
                    logger.info(f"Cleared checkpoint: {s}")
        else:
            checkpoint_file = self._get_checkpoint_file(step)
            if checkpoint_file.exists():
                checkpoint_file.unlink()
                logger.info(f"Cleared checkpoint: {step}")

    # =========================================================================
    # Index Building
    # =========================================================================

    def _build_indexes(self) -> None:
        """Build in-memory indexes for fast lookup."""
        logger.info("Building in-memory indexes...")

        self._doi_to_point_id = {}
        self._arxiv_to_point_id = {}
        self._openalex_to_point_id = {}
        self._title_to_point_id = {}

        offset = None
        count = 0

        while True:
            results, offset = self.storage.client.scroll(
                collection_name=self.storage.collection_name,
                limit=1000,
                offset=offset,
                with_payload=["doi", "source_id", "openalex_id", "title"],
            )

            for point in results:
                point_id = str(point.id)
                payload = point.payload

                # Index by DOI
                doi = payload.get("doi")
                if doi:
                    self._doi_to_point_id[doi.lower()] = point_id

                # Index by OpenAlex ID
                openalex_id = payload.get("openalex_id")
                if openalex_id:
                    # Store both with and without W prefix for flexibility
                    self._openalex_to_point_id[openalex_id.upper()] = point_id

                # Index by arXiv ID (from source_id)
                source_id = payload.get("source_id", "")
                if source_id.startswith("arXiv:"):
                    arxiv_id = source_id[6:].lower()
                    self._arxiv_to_point_id[arxiv_id] = point_id
                elif source_id.startswith("arxiv:"):
                    arxiv_id = source_id[6:].lower()
                    self._arxiv_to_point_id[arxiv_id] = point_id

                # Index by normalized title
                title = payload.get("title", "")
                if title:
                    normalized = Deduplicator.normalize_title(title)
                    if normalized and normalized not in self._title_to_point_id:
                        self._title_to_point_id[normalized] = point_id

                count += 1

            if offset is None:
                break

        logger.info(
            f"Indexes built: {len(self._doi_to_point_id)} DOIs, "
            f"{len(self._openalex_to_point_id)} OpenAlex IDs, "
            f"{len(self._arxiv_to_point_id)} arXiv IDs, "
            f"{len(self._title_to_point_id)} titles"
        )

    def _ensure_indexes(self) -> None:
        """Ensure indexes are built."""
        if self._doi_to_point_id is None:
            self._build_indexes()

    # =========================================================================
    # Step 1: Normalize References
    # =========================================================================

    async def normalize_references(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> ResolutionProgress:
        """Step 1: Normalize raw reference identifiers.

        Fixes issues like:
        - 'arXiv:arXiv:2303.08774' -> 'arXiv:2303.08774'
        - DOI case normalization
        - Prefix standardization

        Args:
            dry_run: If True, count without updating.
            limit: Maximum papers to process.

        Returns:
            ResolutionProgress with statistics.
        """
        progress = self._load_checkpoint("normalize")
        offset = progress.last_offset

        logger.info("Step 1: Normalizing reference identifiers...")

        while True:
            papers, next_offset = self.storage.get_papers_with_references(
                limit=self.batch_size,
                offset=offset,
            )

            if not papers:
                break

            updates = []
            for point_id, payload in papers:
                if point_id in progress.processed_point_ids:
                    progress.skipped += 1
                    continue

                progress.processed += 1
                progress.processed_point_ids.add(point_id)

                refs = payload.get("referenced_works", [])
                if not refs:
                    continue

                # Normalize each reference
                normalized_refs = []
                changed = False
                for ref in refs:
                    norm = IdentifierNormalizer.normalize(ref)
                    normalized_ref = norm.prefixed
                    if normalized_ref != ref:
                        changed = True
                        progress.refs_normalized += 1
                    normalized_refs.append(normalized_ref)

                if changed and not dry_run:
                    updates.append((point_id, normalized_refs))

                if changed:
                    progress.updated += 1

            # Batch update
            if updates:
                self.storage.batch_update_referenced_works_normalized(updates)
                logger.debug(f"Updated {len(updates)} papers with normalized refs")

            # Save checkpoint
            progress.last_offset = next_offset
            progress.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_checkpoint(progress, "normalize")

            offset = next_offset
            if offset is None:
                break

            if limit and progress.processed >= limit:
                break

            # Progress logging
            if progress.processed % 1000 == 0:
                logger.info(
                    f"Normalize progress: {progress.processed} papers, "
                    f"{progress.refs_normalized} refs normalized"
                )

        logger.info(
            f"Normalization complete: {progress.processed} papers, "
            f"{progress.refs_normalized} refs normalized, "
            f"{progress.updated} papers updated"
        )
        return progress

    # =========================================================================
    # Step 2: Resolve arXiv to DOI
    # =========================================================================

    async def resolve_arxiv_to_doi(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> ResolutionProgress:
        """Step 2: Resolve arXiv references to DOIs via OpenAlex.

        For each arXiv reference, looks up the paper in OpenAlex to find
        its DOI (if available).

        Args:
            dry_run: If True, count without updating.
            limit: Maximum papers to process.

        Returns:
            ResolutionProgress with statistics.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        progress = self._load_checkpoint("arxiv")
        offset = progress.last_offset

        logger.info("Step 2: Resolving arXiv references to DOIs...")

        # Cache of arXiv -> DOI mappings to avoid redundant API calls
        arxiv_to_doi_cache: dict[str, str | None] = {}

        while True:
            papers, next_offset = self.storage.get_papers_with_references(
                limit=self.batch_size,
                offset=offset,
            )

            if not papers:
                break

            updates = []
            for point_id, payload in papers:
                if point_id in progress.processed_point_ids:
                    progress.skipped += 1
                    continue

                progress.processed += 1
                progress.processed_point_ids.add(point_id)

                refs = payload.get("referenced_works", [])
                if not refs:
                    continue

                # Find arXiv references
                new_refs = []
                arxiv_refs_to_resolve = []
                for ref in refs:
                    norm = IdentifierNormalizer.normalize(ref)
                    if norm.type == IdentifierType.ARXIV:
                        arxiv_refs_to_resolve.append((ref, norm.value))
                        new_refs.append(None)  # Placeholder
                    else:
                        new_refs.append(ref)

                if not arxiv_refs_to_resolve:
                    continue

                # Resolve arXiv IDs to DOIs
                changed = False
                for i, (orig_ref, arxiv_id) in enumerate(arxiv_refs_to_resolve):
                    # Find placeholder index
                    placeholder_idx = new_refs.index(None)

                    if arxiv_id in arxiv_to_doi_cache:
                        doi = arxiv_to_doi_cache[arxiv_id]
                    else:
                        doi = await self._lookup_arxiv_doi(arxiv_id)
                        arxiv_to_doi_cache[arxiv_id] = doi

                    if doi:
                        new_refs[placeholder_idx] = f"DOI:{doi}"
                        changed = True
                        progress.arxiv_resolved += 1
                    else:
                        new_refs[placeholder_idx] = orig_ref

                if changed and not dry_run:
                    updates.append((point_id, new_refs))

                if changed:
                    progress.updated += 1

            # Batch update
            if updates:
                self.storage.batch_update_referenced_works_normalized(updates)
                logger.debug(f"Updated {len(updates)} papers with DOI refs")

            # Save checkpoint
            progress.last_offset = next_offset
            progress.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_checkpoint(progress, "arxiv")

            offset = next_offset
            if offset is None:
                break

            if limit and progress.processed >= limit:
                break

            # Progress logging
            if progress.processed % 500 == 0:
                logger.info(
                    f"arXiv->DOI progress: {progress.processed} papers, "
                    f"{progress.arxiv_resolved} arXiv refs resolved"
                )

        logger.info(
            f"arXiv->DOI resolution complete: {progress.processed} papers, "
            f"{progress.arxiv_resolved} arXiv refs resolved to DOIs"
        )
        return progress

    async def _lookup_arxiv_doi(self, arxiv_id: str) -> str | None:
        """Look up DOI for an arXiv ID via OpenAlex.

        Uses OpenAlexMixin.fetch_openalex_work for proper rate limit handling,
        API key exhaustion fallback to email pool, and max retry limits.

        Args:
            arxiv_id: arXiv ID (e.g., '2303.08774').

        Returns:
            DOI string or None if not found.
        """
        data = await self.fetch_openalex_work(arxiv_id, "arxiv")
        if data:
            doi = data.get("doi")
            if doi:
                # Clean DOI URL format
                if doi.startswith("https://doi.org/"):
                    doi = doi[16:]
                return doi.lower()
        return None

    # =========================================================================
    # Step 3: Resolve to Internal IDs
    # =========================================================================

    async def resolve_to_internal_ids(
        self,
        dry_run: bool = False,
        limit: int | None = None,
        fuzzy_matching: bool = False,
        external_search: bool = False,
        create_stubs: bool = False,
    ) -> ResolutionProgress:
        """Step 3: Resolve identifiers to internal Qdrant point IDs.

        Maps DOI, arXiv, and TITLE references to internal paper IDs
        using in-memory indexes for fast lookup.

        Args:
            dry_run: If True, count without updating.
            limit: Maximum papers to process.
            fuzzy_matching: Use fuzzy title matching (slower).
            external_search: Search S2/OpenAlex for unresolved titles.
            create_stubs: If True, create stub papers for unresolved refs.

        Returns:
            ResolutionProgress with statistics.
        """
        self._ensure_indexes()

        progress = self._load_checkpoint("internal")
        offset = progress.last_offset

        logger.info("Step 3: Resolving references to internal IDs...")

        while True:
            papers, next_offset = self.storage.get_papers_with_references(
                limit=self.batch_size,
                offset=offset,
            )

            if not papers:
                break

            updates = []
            stubs_to_create: list[tuple[str, str, str]] = []  # (identifier, type, citing_id)

            for point_id, payload in papers:
                if point_id in progress.processed_point_ids:
                    progress.skipped += 1
                    continue

                progress.processed += 1
                progress.processed_point_ids.add(point_id)

                refs = payload.get("referenced_works", [])
                if not refs:
                    continue

                # Resolve each reference
                resolved_ids = []
                for ref in refs:
                    norm = IdentifierNormalizer.normalize(ref)
                    resolved_id = None

                    if norm.type == IdentifierType.DOI:
                        resolved_id = self._doi_to_point_id.get(norm.value.lower())
                        if resolved_id:
                            progress.dois_resolved += 1

                    elif norm.type == IdentifierType.ARXIV:
                        resolved_id = self._arxiv_to_point_id.get(norm.value.lower())
                        if resolved_id:
                            progress.dois_resolved += 1  # Count as resolved

                    elif norm.type == IdentifierType.TITLE:
                        normalized_title = Deduplicator.normalize_title(norm.value)
                        resolved_id = self._title_to_point_id.get(normalized_title)

                        if not resolved_id and fuzzy_matching:
                            resolved_id = self._fuzzy_title_match(normalized_title)

                        if resolved_id:
                            progress.titles_resolved += 1
                        elif external_search and not dry_run:
                            # Try to find and add from external source
                            resolved_id = await self._search_and_add_paper(norm.value)
                            if resolved_id:
                                progress.external_added += 1
                                progress.titles_resolved += 1

                    elif norm.type == IdentifierType.OPENALEX:
                        # OpenAlex Work IDs (e.g., W2741809807)
                        resolved_id = self._openalex_to_point_id.get(norm.value.upper())
                        if resolved_id:
                            progress.openalex_resolved += 1

                    if resolved_id:
                        resolved_ids.append(resolved_id)
                    elif create_stubs and not dry_run:
                        # Create stub for unresolved reference
                        id_type = norm.type.name.lower()
                        stubs_to_create.append((norm.prefixed, id_type, point_id))

                if resolved_ids and not dry_run:
                    updates.append((point_id, resolved_ids))

                if resolved_ids:
                    progress.updated += 1

            # Batch update resolved_references
            if updates:
                self.storage.batch_update_resolved_references(updates)
                logger.debug(f"Updated {len(updates)} papers with resolved refs")

            # Batch create stub papers
            if stubs_to_create and create_stubs:
                created_stubs = self.storage.batch_create_stub_papers(stubs_to_create)
                # Count new vs updated stubs
                for identifier, stub_id in created_stubs.items():
                    # Check if this was a new stub or update
                    # For simplicity, count all as created (storage handles dedup)
                    progress.stubs_created += 1
                logger.debug(f"Created/updated {len(created_stubs)} stub papers")

            # Save checkpoint
            progress.last_offset = next_offset
            progress.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_checkpoint(progress, "internal")

            offset = next_offset
            if offset is None:
                break

            if limit and progress.processed >= limit:
                break

            # Progress logging
            if progress.processed % 500 == 0:
                logger.info(
                    f"Resolution progress: {progress.processed} papers, "
                    f"{progress.dois_resolved} DOIs, "
                    f"{progress.openalex_resolved} OpenAlex, "
                    f"{progress.titles_resolved} titles resolved"
                )

        stub_msg = ""
        if create_stubs:
            stub_msg = f", {progress.stubs_created} stubs created"
        logger.info(
            f"Resolution complete: {progress.processed} papers, "
            f"{progress.dois_resolved} DOIs, "
            f"{progress.openalex_resolved} OpenAlex IDs, "
            f"{progress.titles_resolved} titles resolved, "
            f"{progress.external_added} papers added from external search"
            f"{stub_msg}"
        )
        return progress

    def _fuzzy_title_match(
        self, normalized_title: str, threshold: float = 0.9
    ) -> str | None:
        """Find a paper by fuzzy title matching.

        Args:
            normalized_title: Normalized title to match.
            threshold: Minimum similarity threshold.

        Returns:
            Point ID if match found, None otherwise.
        """
        from src.core.deduplication import are_titles_similar

        for title, point_id in self._title_to_point_id.items():
            if are_titles_similar(normalized_title, title, threshold):
                return point_id
        return None

    async def _search_and_add_paper(self, title: str) -> str | None:
        """Search external APIs for a paper and add to corpus.

        Args:
            title: Paper title to search.

        Returns:
            New point ID if paper was added, None otherwise.
        """
        # Try OpenAlex first
        paper_data = await self._search_openalex_by_title(title)

        if not paper_data:
            # Could add Semantic Scholar fallback here
            return None

        # Add paper to corpus
        from src.models.paper import RawPaper, SourceType

        paper = RawPaper(
            source=SourceType.OPENALEX,
            source_id=paper_data.get("openalex_id", f"search:{title[:50]}"),
            title=paper_data.get("title", title),
            abstract=paper_data.get("abstract"),
            doi=paper_data.get("doi"),
            year=paper_data.get("year"),
            is_core=False,  # External paper
            tier=None,  # No tier for external papers
        )

        point_id = self.storage.upsert_paper(paper)

        # Update indexes
        if paper.doi:
            self._doi_to_point_id[paper.doi.lower()] = point_id
        normalized = Deduplicator.normalize_title(paper.title)
        if normalized:
            self._title_to_point_id[normalized] = point_id

        logger.debug(f"Added external paper: {paper.title[:50]}... -> {point_id}")
        return point_id

    async def _search_openalex_by_title(
        self, title: str, _retry_count: int = 0
    ) -> dict[str, Any] | None:
        """Search OpenAlex by title.

        Args:
            title: Paper title.
            _retry_count: Internal retry counter (do not set manually).

        Returns:
            Paper data dict or None.
        """
        max_retries = 3

        if not self._client:
            return None

        async with self._semaphore:
            await asyncio.sleep(self.delay)

            url = f"{OPENALEX_BASE_URL}/works"
            params = {"search": title, "per_page": 5}
            openalex_params = self._get_openalex_params()
            used_key = openalex_params.get("api_key")
            params.update(openalex_params)

            try:
                response = await self._client.get(url, params=params)

                if response.status_code == 429:
                    if self._handle_api_key_exhaustion(response, used_key):
                        if self._key_manager.has_available_keys:
                            if hasattr(self, "_semaphore") and self._semaphore is not None:
                                self._semaphore = asyncio.Semaphore(
                                    self._original_max_concurrent
                                )
                        return await self._search_openalex_by_title(title)
                    if _retry_count >= max_retries:
                        logger.warning(
                            f"OpenAlex rate limit: max retries ({max_retries}) "
                            f"reached for title search, skipping."
                        )
                        return None
                    logger.warning(
                        f"Rate limited, waiting 60s... "
                        f"(retry {_retry_count + 1}/{max_retries})"
                    )
                    await asyncio.sleep(60)
                    return await self._search_openalex_by_title(
                        title, _retry_count=_retry_count + 1
                    )

                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])
                if not results:
                    return None

                # Find best match
                title_lower = Deduplicator.normalize_title(title)
                for result in results:
                    result_title = result.get("title", "")
                    result_normalized = Deduplicator.normalize_title(result_title)

                    if result_normalized == title_lower or (
                        len(title_lower) > 20
                        and (
                            title_lower in result_normalized
                            or result_normalized in title_lower
                        )
                    ):
                        # Extract DOI
                        doi = result.get("doi")
                        if doi and doi.startswith("https://doi.org/"):
                            doi = doi[16:]

                        # Reconstruct abstract
                        abstract = None
                        inverted_index = result.get("abstract_inverted_index")
                        if inverted_index:
                            max_pos = 0
                            for positions in inverted_index.values():
                                if positions:
                                    max_pos = max(max_pos, max(positions))
                            words = [""] * (max_pos + 1)
                            for word, positions in inverted_index.items():
                                for pos in positions:
                                    words[pos] = word
                            abstract = " ".join(words)

                        return {
                            "title": result_title,
                            "doi": doi,
                            "abstract": abstract,
                            "year": result.get("publication_year"),
                            "openalex_id": result.get("id", "").replace(
                                "https://openalex.org/", ""
                            ),
                        }

            except Exception as e:
                logger.debug(f"Error searching OpenAlex for '{title[:30]}': {e}")

            return None

    # =========================================================================
    # Full Pipeline
    # =========================================================================

    async def run_full_pipeline(
        self,
        dry_run: bool = False,
        limit: int | None = None,
        fuzzy_matching: bool = False,
        external_search: bool = False,
        create_stubs: bool = False,
    ) -> dict[str, ResolutionProgress]:
        """Run the complete 3-step reference resolution pipeline.

        Args:
            dry_run: If True, count without updating.
            limit: Maximum papers to process per step.
            fuzzy_matching: Use fuzzy title matching in step 3.
            external_search: Search external APIs for unresolved titles.
            create_stubs: Create stub papers for unresolved references.

        Returns:
            Dictionary mapping step name to progress.
        """
        results = {}

        logger.info("=== Reference Resolution Pipeline ===")

        # Step 1: Normalize
        logger.info("\n--- Step 1: Normalize ---")
        results["normalize"] = await self.normalize_references(
            dry_run=dry_run, limit=limit
        )

        # Step 2: arXiv -> DOI
        logger.info("\n--- Step 2: arXiv -> DOI ---")
        results["arxiv"] = await self.resolve_arxiv_to_doi(dry_run=dry_run, limit=limit)

        # Step 3: Resolve to IDs
        logger.info("\n--- Step 3: Resolve to IDs ---")
        results["internal"] = await self.resolve_to_internal_ids(
            dry_run=dry_run,
            limit=limit,
            fuzzy_matching=fuzzy_matching,
            external_search=external_search,
            create_stubs=create_stubs,
        )

        return results
