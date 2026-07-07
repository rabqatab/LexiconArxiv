"""Qdrant storage layer for Core Corpus papers.

Provides vector database storage with payload fields for filtering and retrieval.
"""

import logging
import os
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from src.core.storage.query import PaperQuery
from src.core.storage.reader import PaperReader
from src.core.storage.writer import BatchWriter
from src.core.storage.stubs import StubManager
from src.core.storage.statistics import StorageStatistics
from src.models.paper import RawPaper

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Default collection name for core corpus
DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "lexicon_arxiv")

# Vector dimensions (commented out - using payload-only storage)
# Vectors will be added later via named vectors feature
# VECTOR_DIM = 768


class QdrantStorage:
    """Qdrant storage for core corpus papers.

    Stores papers with vector embeddings (placeholder) and payload metadata
    for efficient filtering and retrieval.
    """

    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
        url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ):
        """Initialize Qdrant storage.

        Args:
            collection_name: Name of the Qdrant collection.
            url: Qdrant server URL. Defaults to QDRANT_URL env var.
            api_key: Qdrant API key. Defaults to QDRANT_API_KEY env var.
            timeout: HTTP client timeout in seconds. Defaults to
                ``QDRANT_TIMEOUT`` env var if set, else 300s. Bumped from
                the historical 60s after the 2026-07-04 label-abstracts
                500-paper bench: heavy filters (labeling-eligible count
                over 3.7M real papers) and payload set-writes both blew
                past 60s under P3-completion load. 300s is a safe headroom
                for the catchup-scale work; caller / env can drop it back
                down for latency-sensitive callsites (search, MCP handlers).
        """
        self.collection_name = collection_name
        self.url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self.api_key = api_key or os.getenv("QDRANT_API_KEY") or None
        if timeout is None:
            timeout = float(os.getenv("QDRANT_TIMEOUT", "300"))
        self.timeout = timeout

        # Initialize client
        client_kwargs = {"url": self.url, "timeout": timeout}
        if self.api_key:
            client_kwargs["api_key"] = self.api_key
        self.client = QdrantClient(**client_kwargs)

        # Compose helper objects
        self.queries = PaperQuery(self.client, self.collection_name)
        self.readers = PaperReader(self.client, self.collection_name)
        self.writers = BatchWriter(self.client, self.collection_name)
        self.stubs = StubManager(self.client, self.collection_name)
        self.statistics = StorageStatistics(self.client, self.collection_name)

    def ensure_collection(self) -> bool:
        """Ensure the collection exists, creating it if necessary.

        Returns:
            True if collection was created, False if it already existed.
        """
        try:
            self.client.get_collection(self.collection_name)
            logger.info(f"Collection '{self.collection_name}' already exists")
            return False
        except (UnexpectedResponse, Exception):
            # Collection doesn't exist, create it (payload-only, vectors added later)
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={},  # Empty config for payload-only storage
            )
            logger.info(f"Created collection '{self.collection_name}'")
            return True

    def ensure_collection_with_vectors(
        self,
        dense_vector_size: int = 1024,
    ) -> bool:
        """Create collection with all dense vectors + BM25 sparse vector config.

        Creates 9 dense vectors (abstract, structured-abstract, and 7 section vectors)
        plus 1 BM25 sparse vector.

        Returns:
            True if created, False if already exists.
        """
        from src.core.constants import ALL_DENSE_VECTORS

        try:
            self.client.get_collection(self.collection_name)
            logger.info(f"Collection '{self.collection_name}' already exists")
            return False
        except (UnexpectedResponse, Exception):
            vectors_config = {
                name: models.VectorParams(
                    size=dense_vector_size,
                    distance=models.Distance.COSINE,
                )
                for name in ALL_DENSE_VECTORS
            }
            # Cap background work so search queries can still make progress
            # under bulk write load. The 2026-07-04 labeling job (b2ab) at
            # scale saturated all CPU cores with HNSW background indexing +
            # segment-merge optimizer work; the SearchService's multi-vector
            # search hit Qdrant's 60s internal "fill query context" timeout.
            # Caps of 2 leave ~6-10 cores free on GB10 for hybrid queries.
            # PATCH-able at runtime; setting them here ensures fresh
            # collections inherit the tuned defaults.
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=vectors_config,
                sparse_vectors_config={
                    "bm25": models.SparseVectorParams(
                        modifier=models.Modifier.IDF,
                    ),
                },
                hnsw_config=models.HnswConfigDiff(max_indexing_threads=2),
                optimizers_config=models.OptimizersConfigDiff(max_optimization_threads=2),
            )
            logger.info(
                f"Created collection '{self.collection_name}' with "
                f"{len(ALL_DENSE_VECTORS)} dense vectors ({dense_vector_size}d), "
                f"BM25 sparse vector, and search-friendly background thread caps "
                f"(max_indexing_threads=2, max_optimization_threads=2)"
            )
            self.ensure_venue_text_index()
            self.ensure_stub_payload_index()
            self.ensure_identifier_indices()
            return True

    def ensure_venue_text_index(self) -> None:
        """Create a full-text index on the ``venue`` field if missing.

        The index uses a word tokenizer with lowercasing so that
        ``MatchText`` queries are case-insensitive (e.g. ``"iclr"``
        matches ``"ICLR 2025 Poster"``).
        """
        try:
            info = self.client.get_collection(self.collection_name)
            venue_schema = info.payload_schema.get("venue")
            if venue_schema and venue_schema.data_type == "text":
                return  # Index already exists
        except Exception:
            pass

        try:
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="venue",
                field_schema=models.TextIndexParams(
                    type="text",
                    tokenizer=models.TokenizerType.WORD,
                    lowercase=True,
                ),
            )
            logger.info("Created text index on 'venue' field")
        except Exception as e:
            logger.warning(f"Could not create venue text index (may already exist): {e}")

    def ensure_stub_payload_index(self) -> None:
        """Create a boolean index on is_stub for fast filtering."""
        try:
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="is_stub",
                field_schema=models.PayloadSchemaType.BOOL,
            )
            logger.info("Created is_stub payload index")
        except Exception:
            pass  # Already exists

    def ensure_identifier_indices(self) -> None:
        """Create keyword indices on doi/openalex_id/arxiv_id/source_id for fast lookups.

        Without these, every P2 promotion does ~3 filtered scrolls that
        full-scan the collection (~4 sec on 3.6M points = ~13 sec per
        promotion). With them, each scroll is <20ms — ~250x speedup. Required
        for P2 (resolve-stubs-from-snapshot) and used by find_real_by_identifier
        + the OpenAlex / DOI / arXiv enrichment paths.

        `source_id` was added 2026-07-03 to fix the get_paper_by_arxiv_id 60s
        timeout on legacy arXiv-crawler papers (they store the arxiv id in
        source_id, not arxiv_id — see incident 2026-07-03).

        Idempotent: Qdrant create_payload_index is a no-op if the index already
        exists. Safe to call repeatedly at every phase startup.
        """
        for field in ("doi", "openalex_id", "arxiv_id", "source_id"):
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                logger.info(f"Created keyword payload index on '{field}'")
            except Exception:
                pass  # Already exists

    def delete_collection(self) -> bool:
        """Delete the collection.

        Returns:
            True if deleted successfully.
        """
        try:
            self.client.delete_collection(self.collection_name)
            logger.info(f"Deleted collection '{self.collection_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to delete collection: {e}")
            return False

    def _paper_to_payload(self, paper: RawPaper) -> dict[str, Any]:
        """Convert RawPaper to Qdrant payload.

        Args:
            paper: The paper to convert.

        Returns:
            Payload dictionary for Qdrant.
        """
        return {
            "source_id": paper.source_id,
            "openalex_id": paper.openalex_id,
            "title": paper.title,
            "abstract": paper.abstract or "",
            "venue": paper.venue,
            "venue_type": paper.venue_type,
            "tier": paper.tier,
            "is_core": paper.is_core,
            "year": paper.year,
            "doi": paper.doi,
            "citation_count": paper.citation_count,
            "referenced_works": paper.referenced_works,
            "authors": [a.name for a in paper.authors],
            "categories": paper.categories,
            "pdf_url": paper.pdf_url,
            "fetched_at": paper.fetched_at.isoformat() if paper.fetched_at else None,
        }

    # NOTE: Placeholder vector removed - using payload-only storage
    # Vectors will be added later via named vectors feature
    # def _generate_placeholder_vector(self) -> list[float]:
    #     """Generate a placeholder zero vector."""
    #     return [0.0] * VECTOR_DIM

    def upsert_paper(self, paper: RawPaper) -> str:
        """Upsert a single paper into the collection.

        Args:
            paper: The paper to upsert.

        Returns:
            The point ID used for the paper.
        """
        point_id = str(uuid4())
        payload = self._paper_to_payload(paper)

        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector={},  # Empty for payload-only storage
                    payload=payload,
                )
            ],
        )
        return point_id

    def upsert_papers(self, papers: list[RawPaper], batch_size: int = 100) -> int:
        """Upsert multiple papers into the collection.

        Args:
            papers: List of papers to upsert.
            batch_size: Number of papers per batch.

        Returns:
            Number of papers upserted.
        """
        total_upserted = 0

        for i in range(0, len(papers), batch_size):
            batch = papers[i : i + batch_size]
            points = [
                models.PointStruct(
                    id=str(uuid4()),
                    vector={},  # Empty for payload-only storage
                    payload=self._paper_to_payload(paper),
                )
                for paper in batch
            ]

            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
            )
            total_upserted += len(batch)
            logger.debug(f"Upserted batch of {len(batch)} papers")

        return total_upserted

    # =========================================================================
    # Query Facade (delegated to PaperQuery)
    # =========================================================================

    def get_paper_by_doi(self, doi: str) -> dict[str, Any] | None:
        return self.queries.get_paper_by_doi(doi)

    def get_paper_by_openalex_id(self, openalex_id: str) -> dict[str, Any] | None:
        return self.queries.get_paper_by_openalex_id(openalex_id)

    def get_paper_by_arxiv_id(self, arxiv_id: str) -> tuple[str, dict] | None:
        return self.queries.get_paper_by_arxiv_id(arxiv_id)

    def get_paper_by_id(self, point_id: str) -> dict[str, Any] | None:
        return self.queries.get_paper_by_id(point_id)

    # ponytail: snapshot phase modules + mock_storage use get_payload as the
    # name for "fetch this point's payload dict". Real storage already had
    # get_paper_by_id with identical shape; this alias bridges the naming gap
    # so bootstrap unblocks. Drop during the polish wave by renaming mock + 2
    # phase callsites + 17 test callsites to get_paper_by_id (audit item).
    def get_payload(self, point_id: str) -> dict[str, Any] | None:
        return self.get_paper_by_id(point_id)

    def get_paper_by_normalized_title(
        self, normalized_title: str
    ) -> tuple[str, dict] | None:
        return self.queries.get_paper_by_normalized_title(normalized_title)

    def exists_by_doi(self, doi: str) -> bool:
        return self.queries.exists_by_doi(doi)

    def exists_by_openalex_id(self, openalex_id: str) -> bool:
        return self.queries.exists_by_openalex_id(openalex_id)

    # =========================================================================
    # Reader Facade (delegated to PaperReader)
    # =========================================================================

    def get_papers_missing_references(
        self,
        has_doi: bool = True,
        limit: int = 100,
        offset: str | None = None,
        fetched_since: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_missing_references(has_doi, limit, offset, fetched_since)

    def get_papers_missing_abstracts(
        self,
        has_doi: bool = True,
        limit: int = 100,
        offset: str | None = None,
        fetched_since: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_missing_abstracts(
            has_doi, limit, offset, fetched_since=fetched_since,
        )

    def iter_enrichment_candidates(self, batch_size: int = 1000):
        return self.readers.iter_enrichment_candidates(batch_size=batch_size)

    def iter_all_real_papers_minimal(self, batch_size: int = 1000):
        return self.readers.iter_all_real_papers_minimal(batch_size)

    def get_papers_without_doi_missing_references(
        self,
        limit: int = 100,
        offset: str | None = None,
        venues: list[str] | None = None,
        fetched_since: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_without_doi_missing_references(limit, offset, venues, fetched_since)

    def get_papers_with_references(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_with_references(limit, offset)

    def get_papers_with_title_refs(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_with_title_refs(limit, offset)

    def get_papers_needing_resolution(
        self,
        limit: int = 100,
        offset: str | None = None,
        fetched_since: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_needing_resolution(
            limit, offset, fetched_since=fetched_since,
        )

    def get_papers_for_keyword_extraction(
        self,
        limit: int = 100,
        offset: str | None = None,
        skip_existing: bool = True,
        fetched_since: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_for_keyword_extraction(
            limit, offset, skip_existing, fetched_since=fetched_since,
        )

    def get_papers_for_abstract_labeling(
        self,
        limit: int = 100,
        offset: str | None = None,
        skip_existing: bool = True,
        fetched_since: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_for_abstract_labeling(
            limit, offset, skip_existing, fetched_since=fetched_since,
        )

    def count_papers_for_keyword_extraction(
        self, skip_existing: bool = True, fetched_since: str | None = None,
    ) -> int:
        return self.readers.count_papers_for_keyword_extraction(
            skip_existing, fetched_since=fetched_since,
        )

    def count_papers_for_abstract_labeling(
        self, skip_existing: bool = True, fetched_since: str | None = None,
    ) -> int:
        return self.readers.count_papers_for_abstract_labeling(
            skip_existing, fetched_since=fetched_since,
        )

    def get_papers_missing_code_repos(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_missing_code_repos(limit, offset)

    def get_papers_missing_code_repos_with_pdf(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_missing_code_repos_with_pdf(limit, offset)

    def get_papers_missing_code_repos_with_year(
        self,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_missing_code_repos_with_year(limit, offset)

    def get_all_papers_for_index(
        self,
        fields: list[str],
        limit: int = 1000,
    ) -> dict[str, dict]:
        return self.readers.get_all_papers_for_index(fields, limit)

    def get_papers_for_embedding(
        self,
        limit: int = 100,
        offset: str | None = None,
        skip_embedded: bool = True,
        fetched_since: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get non-stub papers with abstracts for embedding."""
        return self.readers.get_papers_for_embedding(
            limit, offset, skip_embedded, fetched_since=fetched_since,
        )

    def build_referenced_openalex_id_set(self) -> dict[str, int]:
        return self.readers.build_referenced_openalex_id_set()

    def build_openalex_id_to_point_id_map(self) -> dict[str, str]:
        return self.readers.build_openalex_id_to_point_id_map()

    def build_identifier_index_for_dedup(self) -> dict[str, set[str]]:
        return self.readers.build_identifier_index_for_dedup()

    def count_papers_for_embedding(self) -> int:
        """Count non-stub papers with non-empty abstracts."""
        return self.client.count(
            self.collection_name,
            count_filter=models.Filter(
                must_not=[
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
                ],
            ),
        ).count

    # =========================================================================
    # Writer Facade (delegated to BatchWriter)
    # =========================================================================

    def update_referenced_works(
        self,
        point_id: str,
        referenced_works: list[str],
    ) -> bool:
        return self.writers.update_referenced_works(point_id, referenced_works)

    def batch_update_referenced_works(
        self,
        updates: list[tuple[str, list[str]]],
    ) -> int:
        return self.writers.batch_update_referenced_works(updates)

    def update_abstract(
        self,
        point_id: str,
        abstract: str,
    ) -> bool:
        return self.writers.update_abstract(point_id, abstract)

    def batch_update_abstracts(
        self,
        updates: list[tuple[str, str]],
    ) -> int:
        return self.writers.batch_update_abstracts(updates)

    def batch_apply_snapshot_enrichment(self, updates: list[tuple[str, dict]]) -> int:
        return self.writers.batch_apply_snapshot_enrichment(updates)

    def batch_apply_field_fill(self, updates: list[tuple[str, dict]], *, provenance_key: str = "snapshot_filled_at") -> int:
        return self.writers.batch_apply_field_fill(updates, provenance_key=provenance_key)

    def update_paper_with_doi_and_refs(
        self,
        point_id: str,
        doi: str,
        referenced_works: list[str],
    ) -> bool:
        return self.writers.update_paper_with_doi_and_refs(point_id, doi, referenced_works)

    def batch_update_papers_with_doi_and_refs(
        self,
        updates: list[tuple[str, str, list[str]]],
    ) -> int:
        return self.writers.batch_update_papers_with_doi_and_refs(updates)

    def batch_update_referenced_works_normalized(
        self,
        updates: list[tuple[str, list[str]]],
    ) -> int:
        return self.writers.batch_update_referenced_works_normalized(updates)

    def batch_update_resolved_references(
        self,
        updates: list[tuple[str, list[str]]],
    ) -> int:
        return self.writers.batch_update_resolved_references(updates)

    def batch_update_graph_metrics(
        self,
        updates: list[tuple[str, dict]],
    ) -> int:
        return self.writers.batch_update_graph_metrics(updates)

    def batch_update_keywords(
        self,
        updates: list[tuple[str, list[str]]],
    ) -> int:
        return self.writers.batch_update_keywords(updates)

    def batch_update_keywords_with_source(
        self,
        updates: list[tuple[str, list[str], str]],
    ) -> int:
        return self.writers.batch_update_keywords_with_source(updates)

    def batch_update_abstract_structure(
        self,
        updates: list[tuple[str, dict, str]],
    ) -> int:
        return self.writers.batch_update_abstract_structure(updates)

    def batch_update_code_repos(
        self,
        updates: list[tuple[str, list[dict], str | None]],
    ) -> int:
        return self.writers.batch_update_code_repos(updates)

    def clear_all_keywords(self) -> int:
        return self.writers.clear_all_keywords()

    def batch_promote_stubs(self, promotions: list[dict]) -> list[dict]:
        return self.writers.batch_promote_stubs(promotions)

    def batch_inject_papers(self, papers: list[dict]) -> list[dict]:
        return self.writers.batch_inject_papers(papers)

    def batch_extend_external_cited_by(self, updates: dict[str, list[dict]], *, cap: int = 300) -> int:
        return self.writers.batch_extend_external_cited_by(updates, cap=cap)

    # =========================================================================
    # Stub Facade (delegated to StubManager)
    # =========================================================================

    def _generate_stub_id(self, identifier: str) -> str:
        return self.stubs._generate_stub_id(identifier)

    def create_stub_paper(
        self,
        identifier: str,
        identifier_type: str,
        citing_paper_id: str,
    ) -> str | None:
        return self.stubs.create_stub_paper(identifier, identifier_type, citing_paper_id)

    def batch_create_stub_papers(
        self,
        stubs: list[tuple[str, str, str]],
    ) -> dict[str, str]:
        return self.stubs.batch_create_stub_papers(stubs)

    def get_stub_by_identifier(self, identifier: str) -> tuple[str, dict] | None:
        return self.stubs.get_stub_by_identifier(identifier)

    def get_most_cited_stubs(
        self,
        limit: int = 50,
        min_citations: int = 1,
    ) -> list[tuple[str, dict]]:
        return self.stubs.get_most_cited_stubs(limit, min_citations)

    def get_stubs_for_enrichment(
        self,
        identifier_type: str | None = None,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.stubs.get_stubs_for_enrichment(identifier_type, limit, offset)

    def update_stub_metadata(
        self,
        stub_id: str,
        title: str | None = None,
        year: int | None = None,
        authors: list[str] | None = None,
        venue: str | None = None,
        abstract: str | None = None,
        citation_count: int | None = None,
    ) -> bool:
        return self.stubs.update_stub_metadata(
            stub_id, title, year, authors, venue, abstract, citation_count
        )

    def batch_update_stub_metadata(
        self,
        updates: list[tuple[str, dict]],
    ) -> int:
        return self.stubs.batch_update_stub_metadata(updates)

    def count_stubs(self) -> int:
        return self.stubs.count_stubs()

    def count_real_papers(self) -> int:
        return self.stubs.count_real_papers()

    def build_stub_identifier_index(self) -> dict[str, str]:
        return self.stubs.build_stub_identifier_index()

    def find_stub_by_alternate_identifier(
        self,
        doi: str | None = None,
        arxiv_id: str | None = None,
        openalex_id: str | None = None,
    ) -> tuple[str, dict] | None:
        return self.stubs.find_stub_by_alternate_identifier(doi, arxiv_id, openalex_id)

    def add_stub_alternate_identifier(
        self,
        stub_id: str,
        identifier_type: str,
        identifier_value: str,
    ) -> bool:
        return self.stubs.add_stub_alternate_identifier(stub_id, identifier_type, identifier_value)

    def merge_stubs(
        self,
        keep_stub_id: str,
        merge_stub_id: str,
    ) -> bool:
        return self.stubs.merge_stubs(keep_stub_id, merge_stub_id)

    def get_stub_stats(self) -> dict[str, Any]:
        return self.stubs.get_stub_stats()

    def iter_stubs_for_resolution(self, batch_size: int = 500):
        return self.stubs.iter_stubs_for_resolution(batch_size)

    def find_real_by_identifier(self, fields: dict) -> str | None:
        return self.stubs.find_real_by_identifier(fields)

    def merge_stub_into_real(self, stub_point_id: str, real_point_id: str) -> None:
        return self.stubs.merge_stub_into_real(stub_point_id, real_point_id)

    # =========================================================================
    # Statistics Facade (delegated to StorageStatistics)
    # =========================================================================

    def count_papers(self, venue: str | None = None, tier: int | None = None) -> int:
        return self.statistics.count_papers(venue, tier)

    def get_venue_stats(self) -> dict[str, int]:
        return self.statistics.get_venue_stats()

    def get_data_quality_stats(self) -> dict[str, Any]:
        return self.statistics.get_data_quality_stats()

    def get_reference_stats(self) -> dict[str, Any]:
        return self.statistics.get_reference_stats()

    def get_citation_graph_stats(self) -> dict[str, Any]:
        return self.statistics.get_citation_graph_stats()

    def get_keyword_stats(self) -> dict[str, Any]:
        return self.statistics.get_keyword_stats()

    def build_cited_by_index(
        self,
        batch_size: int = 100,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        return self.statistics.build_cited_by_index(batch_size, progress_callback)

    def build_cited_by_incremental(
        self,
        batch_size: int = 100,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        return self.statistics.build_cited_by_incremental(batch_size, progress_callback)
