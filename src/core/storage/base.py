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
    ):
        """Initialize Qdrant storage.

        Args:
            collection_name: Name of the Qdrant collection.
            url: Qdrant server URL. Defaults to QDRANT_URL env var.
            api_key: Qdrant API key. Defaults to QDRANT_API_KEY env var.
        """
        self.collection_name = collection_name
        self.url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self.api_key = api_key or os.getenv("QDRANT_API_KEY") or None

        # Initialize client
        if self.api_key:
            self.client = QdrantClient(url=self.url, api_key=self.api_key, timeout=60)
        else:
            self.client = QdrantClient(url=self.url, timeout=60)

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
        dense_vector_name: str = "abstract-qwen3-8b",
        dense_vector_size: int = 1024,
    ) -> bool:
        """Create collection with dense + BM25 sparse vector configs.

        Returns:
            True if created, False if already exists.
        """
        try:
            self.client.get_collection(self.collection_name)
            logger.info(f"Collection '{self.collection_name}' already exists")
            return False
        except (UnexpectedResponse, Exception):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    dense_vector_name: models.VectorParams(
                        size=dense_vector_size,
                        distance=models.Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    "bm25": models.SparseVectorParams(
                        modifier=models.Modifier.IDF,
                    ),
                },
            )
            logger.info(
                f"Created collection '{self.collection_name}' with dense "
                f"vector '{dense_vector_name}' ({dense_vector_size}d) and BM25 sparse vector"
            )
            return True

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
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_missing_references(has_doi, limit, offset)

    def get_papers_missing_abstracts(
        self,
        has_doi: bool = True,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_missing_abstracts(has_doi, limit, offset)

    def get_papers_without_doi_missing_references(
        self,
        limit: int = 100,
        offset: str | None = None,
        venues: list[str] | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_without_doi_missing_references(limit, offset, venues)

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
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_needing_resolution(limit, offset)

    def get_papers_for_keyword_extraction(
        self,
        limit: int = 100,
        offset: str | None = None,
        skip_existing: bool = True,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_for_keyword_extraction(limit, offset, skip_existing)

    def get_papers_for_abstract_labeling(
        self,
        limit: int = 100,
        offset: str | None = None,
        skip_existing: bool = True,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        return self.readers.get_papers_for_abstract_labeling(limit, offset, skip_existing)

    def count_papers_for_keyword_extraction(self, skip_existing: bool = True) -> int:
        return self.readers.count_papers_for_keyword_extraction(skip_existing)

    def count_papers_for_abstract_labeling(self, skip_existing: bool = True) -> int:
        return self.readers.count_papers_for_abstract_labeling(skip_existing)

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
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get non-stub papers with abstracts for embedding."""
        return self.readers.get_papers_for_embedding(limit, offset)

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
