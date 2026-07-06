"""Paper reader operations for Qdrant storage.

Provides methods for bulk reading papers with various filters.
"""

import logging

from qdrant_client import QdrantClient
from qdrant_client.http import models

from src.core.storage.writer import _retry_qdrant_call

logger = logging.getLogger(__name__)


def _first_author_surname(payload: dict) -> str | None:
    """Extract first author's surname from a stored paper payload.

    Stored payloads use ``authors: list[str]`` (display names), e.g.
    ``["Jane Doe", "John Smith"]``.  Returns the last token of the first
    name, lower-cased, for loose corroboration matching.
    """
    authors = payload.get("authors") or []
    if not authors:
        return None
    name = authors[0] if isinstance(authors[0], str) else ""
    parts = name.strip().split()
    return parts[-1].lower() if parts else None


class PaperReader:
    """Handles bulk paper reading with filtering."""

    def __init__(self, client: QdrantClient, collection_name: str):
        self.client = client
        self.collection_name = collection_name

    def get_papers_missing_references(
        self,
        has_doi: bool = True,
        limit: int = 100,
        offset: str | None = None,
        fetched_since: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers with DOI but empty referenced_works.

        Args:
            has_doi: If True, only return papers that have a DOI.
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.
            fetched_since: ISO date string (e.g., "2026-03-01"). Only papers
                fetched after this date will be returned.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        filter_conditions = [
            models.IsEmptyCondition(
                is_empty=models.PayloadField(key="referenced_works"),
            )
        ]

        # Note: fetched_since is NOT applied server-side because qdrant-client 1.16
        # Range model doesn't accept ISO date strings. The caller (S2 enricher)
        # filters by fetched_at client-side instead.

        # Exclude stubs and optionally papers without DOI
        must_not_conditions = [
            models.FieldCondition(
                key="is_stub", match=models.MatchValue(value=True),
            ),
        ]
        if has_doi:
            must_not_conditions.append(
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="doi"),
                )
            )

        scroll_filter = models.Filter(
            must=filter_conditions,
            must_not=must_not_conditions if must_not_conditions else None,
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_missing_abstracts(
        self,
        has_doi: bool = True,
        limit: int = 100,
        offset: str | None = None,
        fetched_since: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers with DOI but empty/missing abstract.

        Args:
            has_doi: If True, only return papers that have a DOI.
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.
            fetched_since: ISO date string (e.g., "2026-07-06"). Only papers
                fetched after this date will be returned. When set, uses the
                indexed ``fetched_at`` field to bound the scroll — critical
                at corpus scale: without this filter Qdrant does a full
                scan on the unindexed ``abstract`` field and blows past its
                60s server-side scroll_by_id timeout (2026-07-06 incremental
                830c / d582 fatal).

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        # Papers with empty string abstract
        filter_conditions = [
            models.FieldCondition(
                key="abstract",
                match=models.MatchValue(value=""),
            )
        ]
        if fetched_since:
            # Narrow the scroll to recently-fetched papers using the indexed
            # ``fetched_at`` field. Incremental cycles enrich just today's
            # additions (~thousands of papers); prior corpus (~3.7M) is
            # already enriched and doesn't need re-scrolling.
            filter_conditions.append(
                models.FieldCondition(
                    key="fetched_at",
                    range=models.DatetimeRange(gte=fetched_since),
                )
            )
        # Exclude papers where DOI is null/missing (we need DOI for lookup)
        must_not_conditions = []
        if has_doi:
            must_not_conditions.append(
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="doi"),
                )
            )

        scroll_filter = models.Filter(
            must=filter_conditions,
            must_not=must_not_conditions if must_not_conditions else None,
        )

        # 2026-07-06 incremental 830c fatal: Qdrant server-side 60s
        # "scroll_by_id timed out" killed the enricher on a single
        # transient scroll page. Wrap in _retry_qdrant_call so bulk
        # reads survive the same class of contention that the writer
        # path already recovers from.
        results, next_offset = _retry_qdrant_call(
            lambda: self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=scroll_filter,
                limit=limit,
                offset=offset,
                with_payload=True,
            ),
            op_label=f"scroll(get_papers_missing_abstracts, offset={offset})",
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_without_doi_missing_references(
        self,
        limit: int = 100,
        offset: str | None = None,
        venues: list[str] | None = None,
        fetched_since: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers without DOI that are missing referenced_works.

        These papers need title-based lookup for enrichment.

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.
            venues: Optional list of venues to filter by.
            fetched_since: ISO date string (e.g., "2026-03-01"). Only papers
                fetched after this date will be returned.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        # Papers with empty referenced_works AND null/missing DOI
        filter_conditions = [
            models.IsEmptyCondition(
                is_empty=models.PayloadField(key="referenced_works"),
            ),
            models.IsEmptyCondition(
                is_empty=models.PayloadField(key="doi"),
            ),
        ]

        # Note: fetched_since is NOT applied server-side because qdrant-client 1.16
        # Range model doesn't accept ISO date strings. The caller (S2 enricher)
        # filters by fetched_at client-side instead.

        # Optionally filter by venue
        if venues:
            filter_conditions.append(
                models.FieldCondition(
                    key="venue",
                    match=models.MatchAny(any=venues),
                )
            )

        scroll_filter = models.Filter(
            must=filter_conditions,
            must_not=[
                models.FieldCondition(
                    key="is_stub", match=models.MatchValue(value=True),
                ),
            ],
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_with_references(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers that have referenced_works (non-empty).

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        scroll_filter = models.Filter(
            must_not=[
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="referenced_works"),
                )
            ]
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_with_title_refs(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers whose referenced_works contain TITLE:xxx entries.

        Only fetches the referenced_works field (not full payload) for efficiency.

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        # Get papers with non-empty referenced_works
        scroll_filter = models.Filter(
            must_not=[
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="referenced_works"),
                )
            ]
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=["referenced_works"],
        )

        # Filter to papers that have at least one TITLE: entry
        papers = []
        for p in results:
            refs = p.payload.get("referenced_works", [])
            if any(ref.startswith("TITLE:") for ref in refs):
                papers.append((str(p.id), p.payload))

        return papers, next_offset

    def get_papers_needing_resolution(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers with referenced_works but no resolved_references.

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        scroll_filter = models.Filter(
            must=[
                # Has referenced_works
                models.FieldCondition(
                    key="referenced_works",
                    match=models.MatchExcept(**{"except": []}),  # Not empty
                ),
            ],
            must_not=[
                # But no resolved_references yet (null or empty)
                models.FieldCondition(
                    key="resolved_references",
                    match=models.MatchExcept(**{"except": []}),  # Not empty
                ),
            ],
        )

        # Simpler approach: just get papers with refs and check in Python
        scroll_filter = models.Filter(
            must_not=[
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="referenced_works"),
                )
            ]
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=["title", "doi", "referenced_works", "resolved_references"],
        )

        # Filter to papers without resolved_references
        papers = []
        for p in results:
            resolved = p.payload.get("resolved_references", [])
            if not resolved:
                papers.append((str(p.id), p.payload))

        return papers, next_offset

    def get_papers_for_keyword_extraction(
        self,
        limit: int = 100,
        offset: str | None = None,
        skip_existing: bool = True,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers for keyword extraction.

        Only returns papers that have a non-null, non-empty abstract.
        Papers without abstracts (e.g. stubs) are skipped and will be
        picked up automatically once their abstracts are enriched.

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.
            skip_existing: If True, only return papers without keywords.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        must_conditions = []
        must_not_conditions = [
            # Skip papers with null abstract (e.g. stubs)
            models.IsNullCondition(
                is_null=models.PayloadField(key="abstract"),
            ),
            # Skip papers with empty string abstract
            models.FieldCondition(
                key="abstract",
                match=models.MatchValue(value=""),
            ),
        ]

        if skip_existing:
            # Papers without keywords (empty list or null)
            must_conditions.append(
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="keywords"),
                )
            )

        scroll_filter = models.Filter(
            must=must_conditions if must_conditions else None,
            must_not=must_not_conditions,
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=["title", "abstract", "keywords"],
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def count_papers_for_keyword_extraction(self, skip_existing: bool = True) -> int:
        """Count papers eligible for keyword extraction."""
        must_conditions = []
        must_not_conditions = [
            models.IsNullCondition(is_null=models.PayloadField(key="abstract")),
            models.FieldCondition(key="abstract", match=models.MatchValue(value="")),
        ]
        if skip_existing:
            must_conditions.append(
                models.IsEmptyCondition(is_empty=models.PayloadField(key="keywords"))
            )
        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=models.Filter(
                must=must_conditions if must_conditions else None,
                must_not=must_not_conditions,
            ),
        )
        return result.count

    def count_papers_for_abstract_labeling(self, skip_existing: bool = True) -> int:
        """Count papers eligible for abstract labeling.

        Same filter shape as ``get_papers_for_abstract_labeling`` — see
        that method's docstring for the 2026-07-05 IsEmpty/IsNull filter
        gotcha.
        """
        must_not_conditions = [
            models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract")),
            models.IsNullCondition(is_null=models.PayloadField(key="abstract")),
            models.FieldCondition(key="abstract", match=models.MatchValue(value="")),
        ]
        must_conditions = []
        if skip_existing:
            must_conditions.append(
                models.IsEmptyCondition(is_empty=models.PayloadField(key="abstract_structure"))
            )
        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=models.Filter(
                must=must_conditions if must_conditions else None,
                must_not=must_not_conditions,
            ),
        )
        return result.count

    def get_papers_for_abstract_labeling(
        self,
        limit: int = 100,
        offset: str | None = None,
        skip_existing: bool = True,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers for abstract sentence labeling.

        Only returns papers that have a non-null, non-empty abstract.

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.
            skip_existing: If True, only return papers without abstract_structure.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        # Qdrant filter gotcha (discovered 2026-07-05): `IsNullCondition`
        # matches only when the field EXISTS with null value; papers where
        # the field is entirely missing from the payload (many P3
        # snapshot injections) slip past. Use `IsEmptyCondition` — which
        # covers missing / null / empty-collection — plus the explicit
        # empty-string match to catch the "" case that IsEmpty does not.
        must_not_conditions = [
            models.IsEmptyCondition(
                is_empty=models.PayloadField(key="abstract"),
            ),
            models.IsNullCondition(
                is_null=models.PayloadField(key="abstract"),
            ),
            models.FieldCondition(
                key="abstract",
                match=models.MatchValue(value=""),
            ),
        ]

        must_conditions = []
        if skip_existing:
            # Only papers where abstract_structure is missing or empty (not yet labeled)
            must_conditions.append(
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="abstract_structure"),
                )
            )

        scroll_filter = models.Filter(
            must=must_conditions if must_conditions else None,
            must_not=must_not_conditions,
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=["title", "abstract", "abstract_structure"],
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_missing_code_repos(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get non-stub papers that don't have code_repositories yet.

        Returns papers with source_id, doi, and title for matching against
        PWC archive (by arXiv ID or title) and HuggingFace API.

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        scroll_filter = models.Filter(
            must=[
                # Only papers without code_repositories yet
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="code_repositories"),
                ),
            ],
            must_not=[
                # Exclude stub papers
                models.FieldCondition(
                    key="is_stub",
                    match=models.MatchValue(value=True),
                ),
            ],
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=["source_id", "doi", "title"],
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_missing_code_repos_with_pdf(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get non-stub papers without code_repositories that have a pdf_url.

        Used by enrich-11 (GROBID full-text GitHub URL extraction).

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        scroll_filter = models.Filter(
            must=[
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="code_repositories"),
                ),
            ],
            must_not=[
                models.FieldCondition(
                    key="is_stub",
                    match=models.MatchValue(value=True),
                ),
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="pdf_url"),
                ),
                models.IsNullCondition(
                    is_null=models.PayloadField(key="pdf_url"),
                ),
            ],
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=["source_id", "doi", "title", "pdf_url"],
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_missing_code_repos_with_year(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get non-stub papers without code_repositories (with year for validation).

        Used by enrich-12 (GitHub API search).

        Args:
            limit: Maximum number of papers to return.
            offset: Scroll offset for pagination.

        Returns:
            Tuple of (list of (point_id, payload), next_offset).
        """
        scroll_filter = models.Filter(
            must=[
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="code_repositories"),
                ),
            ],
            must_not=[
                models.FieldCondition(
                    key="is_stub",
                    match=models.MatchValue(value=True),
                ),
            ],
        )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=["source_id", "doi", "title", "year"],
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    def get_papers_for_embedding(
        self,
        limit: int = 100,
        offset: str | None = None,
        skip_embedded: bool = True,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get non-stub papers with abstracts for embedding.

        Args:
            skip_embedded: If True, exclude papers that already have dense vectors.

        Returns (list of (point_id, payload), next_offset).
        """
        must_not = [
            # Exclude stubs (is_stub is null on real papers, true on stubs)
            models.FieldCondition(
                key="is_stub",
                match=models.MatchValue(value=True),
            ),
            models.IsNullCondition(
                is_null=models.PayloadField(key="abstract"),
            ),
            models.FieldCondition(
                key="abstract",
                match=models.MatchValue(value=""),
            ),
        ]
        if skip_embedded:
            must_not.append(
                models.HasVectorCondition(has_vector="structured-abstract"),
            )

        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(must_not=must_not),
            limit=limit,
            offset=offset,
            with_payload=["title", "abstract", "abstract_structure"],
        )
        return [
            (str(point.id), point.payload)
            for point in results
        ], next_offset

    def get_all_papers_for_index(
        self,
        fields: list[str],
        limit: int = 1000,
    ) -> dict[str, dict]:
        """Get all papers with specified fields for building indexes.

        Args:
            fields: List of payload fields to retrieve.
            limit: Batch size for scrolling.

        Returns:
            Dictionary mapping point_id to payload dict.
        """
        papers: dict[str, dict] = {}
        offset = None

        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                offset=offset,
                with_payload=fields,
            )

            for point in results:
                papers[str(point.id)] = point.payload

            if offset is None:
                break

        return papers

    def iter_enrichment_candidates(self, batch_size: int = 1000):
        """Yield non-stub papers missing an abstract and/or referenced_works.

        Scrolls Qdrant for real (non-stub) papers where the abstract is empty
        OR referenced_works is empty, using ``should`` (OR) semantics.

        Yields dicts: {point_id, doi, title, year, first_author,
                       missing_abstract, missing_refs}.
        """
        flt = models.Filter(
            must_not=[
                models.FieldCondition(
                    key="is_stub", match=models.MatchValue(value=True)
                ),
            ],
            should=[
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="abstract")
                ),
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="referenced_works")
                ),
            ],
        )
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=flt,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break
            for pt in points:
                p = pt.payload or {}
                abstract = p.get("abstract") or ""
                refs = p.get("referenced_works") or []
                first_author = _first_author_surname(p)
                yield {
                    "point_id": str(pt.id),
                    "doi": p.get("doi") or None,
                    "title": p.get("title") or "",
                    "year": p.get("year") or p.get("publication_year"),
                    "first_author": first_author,
                    "missing_abstract": not abstract,
                    "missing_refs": not refs,
                }
            if offset is None:
                break

    def iter_all_real_papers_minimal(self, batch_size: int = 1000):
        """Yield {point_id, doi, openalex_id, title_norm, title} for every non-stub paper.

        Loads minimal payload (4 fields) — suitable for in-memory index building.
        """
        from src.core.deduplication import Deduplicator

        flt = models.Filter(
            must_not=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))]
        )
        offset = None
        while True:
            pts, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=flt,
                limit=batch_size,
                offset=offset,
                with_payload=["doi", "openalex_id", "title"],
                with_vectors=False,
            )
            for p in pts:
                pl = p.payload or {}
                title = pl.get("title")
                yield {
                    "point_id": str(p.id),
                    "doi": pl.get("doi"),
                    "openalex_id": pl.get("openalex_id"),
                    "title": title,
                    "title_norm": Deduplicator.normalize_title(title) if title else None,
                }
            if offset is None:
                return

    def build_referenced_openalex_id_set(self) -> dict[str, int]:
        """Return {OpenAlex Work ID -> in-corpus citer count} across all real papers."""
        counts: dict[str, int] = {}
        flt = models.Filter(
            must_not=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))]
        )
        offset = None
        while True:
            pts, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=flt,
                limit=500,
                offset=offset,
                with_payload=["referenced_works"],
                with_vectors=False,
            )
            for p in pts:
                for ref in (p.payload or {}).get("referenced_works") or []:
                    wid = ref.rsplit("/", 1)[-1] if isinstance(ref, str) else None
                    if wid and wid.startswith("W"):
                        counts[wid] = counts.get(wid, 0) + 1
            if offset is None:
                return counts

    def build_openalex_id_to_point_id_map(self) -> dict[str, str]:
        """Return {OpenAlex Work ID -> point_id} for every non-stub paper that has an openalex_id."""
        out: dict[str, str] = {}
        has_oa = models.Filter(
            must_not=[
                models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
                models.IsEmptyCondition(is_empty=models.PayloadField(key="openalex_id")),
            ]
        )
        offset = None
        while True:
            pts, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=has_oa,
                limit=500,
                offset=offset,
                with_payload=["openalex_id"],
                with_vectors=False,
            )
            for p in pts:
                oa = (p.payload or {}).get("openalex_id")
                if oa:
                    out[oa] = str(p.id)
            if offset is None:
                return out

    def build_identifier_index_for_dedup(self) -> dict[str, set[str]]:
        """Return all known identifiers in the corpus (real + stubs) for P3 dedup."""
        from src.core.deduplication import Deduplicator

        out: dict[str, set[str]] = {"doi": set(), "openalex_id": set(), "title_norm": set()}
        offset = None
        while True:
            pts, offset = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=None,
                limit=500,
                offset=offset,
                with_payload=["doi", "openalex_id", "title"],
                with_vectors=False,
            )
            for p in pts:
                pl = p.payload or {}
                if pl.get("doi"):
                    out["doi"].add(pl["doi"])
                if pl.get("openalex_id"):
                    out["openalex_id"].add(pl["openalex_id"])
                if pl.get("title"):
                    n = Deduplicator.normalize_title(pl["title"])
                    if n:
                        out["title_norm"].add(n)
            if offset is None:
                return out
