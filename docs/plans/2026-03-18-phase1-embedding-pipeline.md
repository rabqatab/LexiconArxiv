# Phase 1: Embedding Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed 145K core papers with Qwen3-Embedding-8B dense vectors (1024d) and server-side BM25 sparse vectors, enabling hybrid search in Qdrant.

**Architecture:** Collection migration (recreate with vector configs) → batch embedding via Ollama `/api/embed` → upsert dense + sparse vectors per point. Checkpoint/resume for crash recovery.

**Tech Stack:** Qdrant 1.16 (named vectors + sparse BM25), Ollama (Qwen3-Embedding-8B), httpx (async HTTP), Click (CLI), existing QdrantStorage facade.

**Spec:** `docs/specs/2026-03-18-search-engine-mvp-design.md` — Section 3

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/core/embedding/__init__.py` | Package init |
| Create | `src/core/embedding/embedder.py` | Async batch embedder (Ollama + Qdrant upsert) |
| Create | `src/core/embedding/migration.py` | Collection migration (backup → recreate → re-insert) |
| Modify | `src/core/storage/base.py` | Add `ensure_collection_with_vectors()` method |
| Modify | `src/core/storage/reader.py` | Add `get_papers_for_embedding()` method |
| Modify | `src/core/constants.py` | Add Ollama embedding model constant |
| Create | `src/cli/commands/embedding.py` | CLI commands: `embed-papers`, `migrate-collection` |
| Modify | `src/cli/core_collect.py` | Register embedding commands |
| Create | `scripts/embedding/run_embedding.sh` | Shell orchestrator |
| Create | `scripts/embedding/migrate_collection.sh` | Migration shell script |
| Create | `tests/test_embedder.py` | Unit tests for embedder |
| Create | `tests/test_migration.py` | Unit tests for migration |

---

## Chunk 1: Collection Migration

### Task 1: Add vector-aware collection creation to QdrantStorage

**Files:**
- Modify: `src/core/storage/base.py`
- Create: `tests/test_migration.py`

- [ ] **Step 1: Write failing test for `ensure_collection_with_vectors()`**

```python
# tests/test_migration.py
from qdrant_client import QdrantClient, models

from src.core.storage.base import QdrantStorage


class TestEnsureCollectionWithVectors:
    """Test creating a collection with dense + sparse vector configs."""

    def setup_method(self):
        self.client = QdrantClient(url="http://localhost:6333")
        self.collection = "_test_ensure_vectors"
        # Cleanup before test
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    def teardown_method(self):
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    def test_creates_collection_with_dense_and_sparse_vectors(self):
        storage = QdrantStorage(collection_name=self.collection)
        created = storage.ensure_collection_with_vectors(
            dense_vector_name="abstract-qwen3-8b",
            dense_vector_size=1024,
        )
        assert created is True

        # Verify collection exists with correct config
        info = self.client.get_collection(self.collection)
        assert "abstract-qwen3-8b" in info.config.params.vectors
        assert info.config.params.vectors["abstract-qwen3-8b"].size == 1024
        assert info.config.params.vectors["abstract-qwen3-8b"].distance == models.Distance.COSINE

    def test_returns_false_if_collection_already_exists(self):
        storage = QdrantStorage(collection_name=self.collection)
        storage.ensure_collection_with_vectors(
            dense_vector_name="abstract-qwen3-8b",
            dense_vector_size=1024,
        )
        created = storage.ensure_collection_with_vectors(
            dense_vector_name="abstract-qwen3-8b",
            dense_vector_size=1024,
        )
        assert created is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migration.py::TestEnsureCollectionWithVectors -v`
Expected: FAIL with `AttributeError: 'QdrantStorage' object has no attribute 'ensure_collection_with_vectors'`

- [ ] **Step 3: Implement `ensure_collection_with_vectors()` in QdrantStorage**

Add to `src/core/storage/base.py`:

```python
def ensure_collection_with_vectors(
    self,
    dense_vector_name: str = "abstract-qwen3-8b",
    dense_vector_size: int = 1024,
) -> bool:
    """Create collection with dense + BM25 sparse vector configs.

    Returns True if created, False if already exists.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migration.py::TestEnsureCollectionWithVectors -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/storage/base.py tests/test_migration.py
git commit -m "feat: add ensure_collection_with_vectors() for dense + BM25 sparse config"
```

---

### Task 2: Build collection migration script

**Files:**
- Create: `src/core/embedding/__init__.py`
- Create: `src/core/embedding/migration.py`
- Add tests to: `tests/test_migration.py`

- [ ] **Step 1: Write failing test for migration logic**

Append to `tests/test_migration.py`:

```python
import time

from src.core.embedding.migration import CollectionMigrator


class TestCollectionMigrator:
    """Test migrating payload-only collection to vector-enabled collection."""

    def setup_method(self):
        self.client = QdrantClient(url="http://localhost:6333")
        self.old_name = "_test_old_collection"
        self.new_name = "_test_new_collection"
        # Cleanup
        for name in [self.old_name, self.new_name]:
            try:
                self.client.delete_collection(name)
            except Exception:
                pass

    def teardown_method(self):
        for name in [self.old_name, self.new_name]:
            try:
                self.client.delete_collection(name)
            except Exception:
                pass

    def test_migrates_points_preserving_ids_and_payloads(self):
        # Create old payload-only collection with test data
        self.client.create_collection(
            collection_name=self.old_name,
            vectors_config={},
        )
        self.client.upsert(
            collection_name=self.old_name,
            points=[
                models.PointStruct(
                    id="aaaaaaaa-1111-2222-3333-444444444444",
                    vector={},
                    payload={"title": "Test Paper 1", "abstract": "About ML", "is_core": True},
                ),
                models.PointStruct(
                    id="bbbbbbbb-1111-2222-3333-444444444444",
                    vector={},
                    payload={"title": "Test Paper 2", "abstract": "About NLP", "is_stub": True},
                ),
            ],
        )

        migrator = CollectionMigrator(
            url="http://localhost:6333",
            old_collection=self.old_name,
            new_collection=self.new_name,
        )
        stats = migrator.migrate()

        assert stats["points_migrated"] == 2

        # Verify new collection has correct vector config
        info = self.client.get_collection(self.new_name)
        assert "abstract-qwen3-8b" in info.config.params.vectors

        # Verify points preserved
        result = self.client.scroll(self.new_name, limit=10, with_payload=True)
        points = result[0]
        assert len(points) == 2
        ids = {str(p.id) for p in points}
        assert "aaaaaaaa-1111-2222-3333-444444444444" in ids
        payloads = {p.payload["title"] for p in points}
        assert "Test Paper 1" in payloads
        assert "Test Paper 2" in payloads
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migration.py::TestCollectionMigrator -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.core.embedding'`

- [ ] **Step 3: Create package init and migration module**

Create `src/core/embedding/__init__.py`:
```python
"""Embedding pipeline for LexiconArxiv."""
```

Create `src/core/embedding/migration.py`:
```python
"""Collection migration: payload-only → vector-enabled collection."""

import logging
import time

from qdrant_client import QdrantClient, models

from src.core.constants import (
    EMBEDDING_VECTOR_NAME,
    EMBEDDING_VECTOR_SIZE,
    get_qdrant_url,
)

logger = logging.getLogger(__name__)

SCROLL_BATCH_SIZE = 100


class CollectionMigrator:
    """Migrate a payload-only Qdrant collection to one with vector configs."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        old_collection: str = "lexicon_arxiv",
        new_collection: str | None = None,
    ):
        self.client = QdrantClient(url=url or get_qdrant_url(), api_key=api_key or None)
        self.old_collection = old_collection
        self.new_collection = new_collection or f"{old_collection}_v2"

    def migrate(
        self,
        delete_old: bool = False,
        dense_vector_name: str = EMBEDDING_VECTOR_NAME,
        dense_vector_size: int = EMBEDDING_VECTOR_SIZE,
    ) -> dict:
        """Run the full migration.

        Returns dict with migration stats.
        """
        start = time.time()

        # 1. Snapshot backup
        logger.info(f"Creating snapshot of '{self.old_collection}'...")
        snapshot = self.client.create_snapshot(self.old_collection)
        logger.info(f"Snapshot created: {snapshot.name}")

        # 2. Create new collection with vector configs
        logger.info(f"Creating new collection '{self.new_collection}'...")
        self.client.create_collection(
            collection_name=self.new_collection,
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

        # 3. Scroll and re-insert all points
        points_migrated = 0
        offset = None

        while True:
            results, next_offset = self.client.scroll(
                collection_name=self.old_collection,
                limit=SCROLL_BATCH_SIZE,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )

            if not results:
                break

            # Batch upsert into new collection (payload only, no vectors yet)
            points = [
                models.PointStruct(
                    id=point.id,
                    vector={},
                    payload=point.payload,
                )
                for point in results
            ]

            self.client.upsert(
                collection_name=self.new_collection,
                points=points,
            )

            points_migrated += len(results)
            if points_migrated % 10000 == 0:
                logger.info(f"Migrated {points_migrated:,} points...")

            if next_offset is None:
                break
            offset = next_offset

        elapsed = time.time() - start
        logger.info(
            f"Migration complete: {points_migrated:,} points in {elapsed:.1f}s"
        )

        # 4. Optionally delete old collection
        if delete_old:
            logger.info(f"Deleting old collection '{self.old_collection}'...")
            self.client.delete_collection(self.old_collection)

        # 5. Verify counts match
        old_count = self.client.count(self.old_collection).count if not delete_old else points_migrated
        new_count = self.client.count(self.new_collection).count

        return {
            "points_migrated": points_migrated,
            "old_count": old_count,
            "new_count": new_count,
            "elapsed_seconds": round(elapsed, 1),
            "snapshot_name": snapshot.name,
            "new_collection": self.new_collection,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migration.py::TestCollectionMigrator -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/embedding/__init__.py src/core/embedding/migration.py tests/test_migration.py
git commit -m "feat: add collection migration from payload-only to vector-enabled"
```

---

### Task 3: Add `get_papers_for_embedding()` to PaperReader

**Files:**
- Modify: `src/core/storage/reader.py`
- Add tests to: `tests/test_migration.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_migration.py`:

```python
from src.core.storage.base import QdrantStorage


class TestGetPapersForEmbedding:
    """Test reading papers that need embedding."""

    def setup_method(self):
        self.collection = "_test_embed_reader"
        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass
        # Create collection with vector config
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                "abstract-qwen3-8b": models.VectorParams(size=4, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
        # Insert test papers
        self.client.upsert(
            collection_name=self.collection,
            points=[
                # Paper with abstract, no vector yet (should be returned)
                models.PointStruct(
                    id="aaaa0001-0000-0000-0000-000000000000",
                    vector={},
                    payload={"title": "Paper 1", "abstract": "Has abstract", "is_stub": False},
                ),
                # Stub paper (should be skipped)
                models.PointStruct(
                    id="aaaa0002-0000-0000-0000-000000000000",
                    vector={},
                    payload={"title": "Stub", "abstract": "Stub abstract", "is_stub": True},
                ),
                # Paper without abstract (should be skipped)
                models.PointStruct(
                    id="aaaa0003-0000-0000-0000-000000000000",
                    vector={},
                    payload={"title": "No abstract", "abstract": "", "is_stub": False},
                ),
            ],
        )

    def teardown_method(self):
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    def test_returns_non_stub_papers_with_abstracts(self):
        storage = QdrantStorage(collection_name=self.collection)
        papers, next_offset = storage.readers.get_papers_for_embedding(limit=10)
        assert len(papers) == 1
        point_id, payload = papers[0]
        assert payload["title"] == "Paper 1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migration.py::TestGetPapersForEmbedding -v`
Expected: FAIL with `AttributeError: 'PaperReader' object has no attribute 'get_papers_for_embedding'`

- [ ] **Step 3: Implement in `src/core/storage/reader.py`**

Add method to `PaperReader` class:

```python
def get_papers_for_embedding(
    self,
    limit: int = 100,
    offset: str | None = None,
) -> tuple[list[tuple[str, dict]], str | None]:
    """Get non-stub papers with abstracts for embedding.

    Returns (list of (point_id, payload), next_offset).
    """
    results, next_offset = self.client.scroll(
        collection_name=self.collection_name,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="is_stub",
                    match=models.MatchValue(value=False),
                ),
            ],
            must_not=[
                models.IsNullCondition(
                    is_null=models.PayloadField(key="abstract"),
                ),
                models.FieldCondition(
                    key="abstract",
                    match=models.MatchValue(value=""),
                ),
            ],
        ),
        limit=limit,
        offset=offset,
        with_payload=["title", "abstract"],
    )
    return [
        (str(point.id), point.payload)
        for point in results
    ], next_offset
```

- [ ] **Step 4: Add facade method to QdrantStorage**

Add to `src/core/storage/base.py` alongside other facade methods:

```python
def get_papers_for_embedding(
    self,
    limit: int = 100,
    offset: str | None = None,
) -> tuple[list[tuple[str, dict]], str | None]:
    """Get non-stub papers with abstracts for embedding."""
    return self.readers.get_papers_for_embedding(limit, offset)
```

Also add `count_papers_for_embedding()`:

```python
def count_papers_for_embedding(self) -> int:
    """Count non-stub papers with non-empty abstracts."""
    return self.client.count(
        self.collection_name,
        count_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="is_stub",
                    match=models.MatchValue(value=False),
                ),
            ],
            must_not=[
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_migration.py::TestGetPapersForEmbedding -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/storage/reader.py src/core/storage/base.py tests/test_migration.py
git commit -m "feat: add get_papers_for_embedding() and count to PaperReader + QdrantStorage"
```

---

## Chunk 2: Embedder Module

### Task 4: Add embedding model constant

**Files:**
- Modify: `src/core/constants.py`

- [ ] **Step 1: Add constant**

Add to `src/core/constants.py`:

```python
# Embedding model
DEFAULT_EMBEDDING_MODEL = "qwen3-embedding:8b"
EMBEDDING_VECTOR_NAME = "abstract-qwen3-8b"
EMBEDDING_VECTOR_SIZE = 1024
EMBEDDING_FULL_SIZE = 4096  # Ollama returns full dim, truncate client-side
```

- [ ] **Step 2: Commit**

```bash
git add src/core/constants.py
git commit -m "feat: add embedding model constants"
```

---

### Task 5: Build the async batch embedder

**Files:**
- Create: `src/core/embedding/embedder.py`
- Create: `tests/test_embedder.py`

- [ ] **Step 1: Write failing test for embedder**

```python
# tests/test_embedder.py
import asyncio

import pytest
import respx
from httpx import Response

from src.core.embedding.embedder import PaperEmbedder


class TestPaperEmbedder:
    """Test embedding generation via Ollama."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_embed_single_abstract(self):
        """Test embedding a single abstract via Ollama /api/embed."""
        # Mock Ollama response with 4096d vector (will be truncated to 1024)
        fake_embedding = list(range(4096))  # [0, 1, 2, ..., 4095]
        route = respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(
                200,
                json={"embeddings": [fake_embedding]},
            ),
        )

        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            model="qwen3-embedding:8b",
            target_dim=1024,
        )
        async with embedder:
            vectors = await embedder.embed_texts(["Test abstract about ML"])

        assert len(vectors) == 1
        assert len(vectors[0]) == 1024  # Truncated from 4096
        assert vectors[0] == list(range(1024))  # First 1024 dims
        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_embed_batch(self):
        """Test embedding multiple abstracts in one call."""
        fake_embeddings = [list(range(4096)) for _ in range(3)]
        respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(
                200,
                json={"embeddings": fake_embeddings},
            ),
        )

        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            model="qwen3-embedding:8b",
            target_dim=1024,
        )
        async with embedder:
            vectors = await embedder.embed_texts([
                "Abstract one",
                "Abstract two",
                "Abstract three",
            ])

        assert len(vectors) == 3
        assert all(len(v) == 1024 for v in vectors)

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_failure(self):
        """Test exponential backoff retry on Ollama errors."""
        fake_embedding = list(range(4096))
        route = respx.post("http://localhost:11434/api/embed")
        # First call fails, second succeeds
        route.side_effect = [
            Response(500, text="Server Error"),
            Response(200, json={"embeddings": [fake_embedding]}),
        ]

        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            model="qwen3-embedding:8b",
            target_dim=1024,
            max_retries=3,
        )
        async with embedder:
            vectors = await embedder.embed_texts(["Test abstract"])

        assert len(vectors) == 1
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_after_max_retries(self):
        """Test returns None when all retries exhausted."""
        respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(500, text="Server Error"),
        )

        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            model="qwen3-embedding:8b",
            target_dim=1024,
            max_retries=2,
        )
        async with embedder:
            vectors = await embedder.embed_texts(["Test abstract"])

        assert vectors is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_embedder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the embedder**

Create `src/core/embedding/embedder.py`:

```python
"""Async batch embedder using Ollama for dense vectors."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from src.core.constants import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_FULL_SIZE,
    EMBEDDING_VECTOR_SIZE,
    get_ollama_base_url,
)

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingProgress:
    """Track embedding pipeline progress."""

    total_to_process: int = 0
    processed: int = 0
    embedded: int = 0
    errors: int = 0
    processed_point_ids: set[str] = field(default_factory=set)
    last_updated: str | None = None


class PaperEmbedder:
    """Embed paper abstracts via Ollama and upsert to Qdrant."""

    def __init__(
        self,
        ollama_base_url: str | None = None,
        model: str = DEFAULT_EMBEDDING_MODEL,
        target_dim: int = EMBEDDING_VECTOR_SIZE,
        max_concurrent: int = 4,
        max_retries: int = 5,
        timeout: float = 300.0,
    ):
        self._base_url = ollama_base_url or get_ollama_base_url()
        self._model = model
        self._target_dim = target_dim
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_retries = max_retries
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "PaperEmbedder":
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        """Embed a batch of texts via Ollama /api/embed.

        Returns list of truncated vectors, or None if all retries fail.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        for attempt in range(self._max_retries):
            async with self._semaphore:
                try:
                    response = await self._client.post(
                        f"{self._base_url}/api/embed",
                        json={
                            "model": self._model,
                            "input": texts,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    embeddings = data["embeddings"]

                    # Truncate from full dim to target dim (MRL)
                    return [emb[: self._target_dim] for emb in embeddings]

                except Exception as e:
                    if attempt < self._max_retries - 1:
                        wait_time = 2**attempt
                        logger.warning(
                            f"Embed failed (attempt {attempt + 1}/{self._max_retries}), "
                            f"retrying in {wait_time}s: {e}"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(
                            f"Embed failed after {self._max_retries} attempts: {e}"
                        )
                        return None

    async def check_model_available(self) -> bool:
        """Check if the embedding model is loaded in Ollama."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")
        try:
            response = await self._client.get(f"{self._base_url}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            available = any(self._model in name for name in model_names)
            if not available:
                logger.warning(
                    f"Model '{self._model}' not found in Ollama. "
                    f"Available: {model_names}"
                )
            return available
        except Exception as e:
            logger.error(f"Failed to check Ollama models: {e}")
            return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_embedder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/embedding/embedder.py tests/test_embedder.py
git commit -m "feat: add async PaperEmbedder with Ollama /api/embed and MRL truncation"
```

---

### Task 6: Add batch embedding + Qdrant upsert pipeline

**Files:**
- Modify: `src/core/embedding/embedder.py`
- Add tests to: `tests/test_embedder.py`

- [ ] **Step 1: Write failing test for `embed_and_upsert_batch()`**

Append to `tests/test_embedder.py`:

```python
class TestEmbedAndUpsert:
    """Test the combined embed + upsert pipeline."""

    def setup_method(self):
        self.collection = "_test_embed_upsert"
        self.qdrant = QdrantClient(url="http://localhost:6333")
        try:
            self.qdrant.delete_collection(self.collection)
        except Exception:
            pass
        self.qdrant.create_collection(
            collection_name=self.collection,
            vectors_config={
                "abstract-qwen3-8b": models.VectorParams(size=4, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
        # Pre-insert payload-only points
        self.qdrant.upsert(
            collection_name=self.collection,
            points=[
                models.PointStruct(
                    id="aaaa0001-0000-0000-0000-000000000000",
                    vector={},
                    payload={"title": "Paper 1", "abstract": "Machine learning paper"},
                ),
                models.PointStruct(
                    id="aaaa0002-0000-0000-0000-000000000000",
                    vector={},
                    payload={"title": "Paper 2", "abstract": "Natural language processing"},
                ),
            ],
        )

    def teardown_method(self):
        try:
            self.qdrant.delete_collection(self.collection)
        except Exception:
            pass

    @pytest.mark.asyncio
    @respx.mock
    async def test_embeds_and_updates_vectors(self):
        from qdrant_client import QdrantClient, models
        from src.core.embedding.embedder import PaperEmbedder
        from src.core.storage.base import QdrantStorage

        # Mock Ollama returning 8d vectors (will be truncated to 4 by target_dim)
        fake_embeddings = [[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
                           [0.5, 0.6, 0.7, 0.8, 0.1, 0.2, 0.3, 0.4]]
        respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(200, json={"embeddings": fake_embeddings}),
        )

        storage = QdrantStorage(collection_name=self.collection)
        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            target_dim=4,  # Match test collection — truncated from 8d mock
        )

        papers = [
            ("aaaa0001-0000-0000-0000-000000000000", {"abstract": "Machine learning paper"}),
            ("aaaa0002-0000-0000-0000-000000000000", {"abstract": "Natural language processing"}),
        ]

        async with embedder:
            count = await embedder.embed_and_upsert_batch(
                papers=papers,
                storage=storage,
                dense_vector_name="abstract-qwen3-8b",
            )

        assert count == 2

        # Verify vectors were stored (via update_vectors, not upsert)
        point = self.qdrant.retrieve(
            collection_name=self.collection,
            ids=["aaaa0001-0000-0000-0000-000000000000"],
            with_vectors=True,
            with_payload=True,
        )[0]
        assert "abstract-qwen3-8b" in point.vector
        assert len(point.vector["abstract-qwen3-8b"]) == 4  # Truncated from 8d mock
        # Verify payloads were preserved (not wiped)
        assert point.payload["title"] == "Paper 1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_embedder.py::TestEmbedAndUpsert -v`
Expected: FAIL with `AttributeError: 'PaperEmbedder' object has no attribute 'embed_and_upsert_batch'`

- [ ] **Step 3: Add `embed_and_upsert_batch()` to PaperEmbedder**

Add to `src/core/embedding/embedder.py`:

```python
from qdrant_client import models as qdrant_models

from src.core.constants import EMBEDDING_VECTOR_NAME

# Add this method to PaperEmbedder class:

async def embed_and_upsert_batch(
    self,
    papers: list[tuple[str, dict]],
    storage: "QdrantStorage",
    dense_vector_name: str = EMBEDDING_VECTOR_NAME,
) -> int:
    """Embed abstracts and update vectors in Qdrant (preserves payloads).

    Uses client.update_vectors() — NOT upsert — to attach vectors
    to existing points without touching their payloads.

    Args:
        papers: List of (point_id, payload) tuples. payload must have "abstract".
        storage: QdrantStorage instance.
        dense_vector_name: Name of the dense vector in Qdrant.

    Returns:
        Number of points successfully embedded and updated.
    """
    # Prepend instruction prefix for Qwen3 retrieval quality
    instruction = "Retrieve academic papers: "
    abstracts = [instruction + p[1]["abstract"] for p in papers]

    # Get dense embeddings from Ollama
    vectors = await self.embed_texts(abstracts)
    if vectors is None:
        logger.error("Failed to get embeddings for batch")
        return 0

    # Build PointVectors for update_vectors (preserves existing payloads)
    point_vectors = [
        qdrant_models.PointVectors(
            id=point_id,
            vector={
                dense_vector_name: dense_vector,
                "bm25": qdrant_models.Document(
                    text=payload["abstract"],
                    model="qdrant/bm25",
                ),
            },
        )
        for (point_id, payload), dense_vector in zip(papers, vectors)
    ]

    # Update vectors only — payloads are untouched
    storage.client.update_vectors(
        collection_name=storage.collection_name,
        points=point_vectors,
    )

    return len(point_vectors)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_embedder.py::TestEmbedAndUpsert -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/embedding/embedder.py tests/test_embedder.py
git commit -m "feat: add embed_and_upsert_batch() for combined dense + BM25 upsert"
```

---

## Chunk 3: CLI + Shell Scripts

### Task 7: Add CLI commands for migration and embedding

**Files:**
- Create: `src/cli/commands/embedding.py`
- Modify: `src/cli/core_collect.py`

- [ ] **Step 1: Create the embedding CLI module**

Create `src/cli/commands/embedding.py`:

```python
"""CLI commands for embedding pipeline."""

import asyncio
import sys

import click

from src.cli._logging import logger


def register_commands(cli: click.Group):
    @cli.command()
    @click.option(
        "--new-collection",
        default=None,
        help="Name for the new collection (default: {old}_v2)",
    )
    @click.option("--delete-old", is_flag=True, help="Delete old collection after migration")
    @click.option("--dry-run", is_flag=True, help="Show what would be migrated without doing it")
    def migrate_collection(
        new_collection: str | None,
        delete_old: bool,
        dry_run: bool,
    ) -> None:
        """Migrate payload-only collection to vector-enabled collection.

        Creates a new collection with dense (Qwen3-8B, 1024d) and sparse
        (BM25) vector configs, then copies all points from the old collection.

        Examples:

          # Migrate with default names (lexicon_arxiv → lexicon_arxiv_v2)
          uv run python -m src.cli.core_collect migrate-collection

          # Migrate and delete old collection
          uv run python -m src.cli.core_collect migrate-collection --delete-old

          # Custom new collection name
          uv run python -m src.cli.core_collect migrate-collection --new-collection lexicon_arxiv_search
        """
        from src.core.embedding.migration import CollectionMigrator
        from src.core.constants import get_qdrant_url, get_qdrant_collection

        url = get_qdrant_url()
        old_name = get_qdrant_collection()

        if dry_run:
            from qdrant_client import QdrantClient
            client = QdrantClient(url=url)
            count = client.count(old_name).count
            click.echo(f"Would migrate {count:,} points from '{old_name}' to '{new_collection or old_name + '_v2'}'")
            return

        migrator = CollectionMigrator(
            url=url,
            old_collection=old_name,
            new_collection=new_collection,
        )

        click.echo(f"Migrating '{old_name}' → '{migrator.new_collection}'...")
        stats = migrator.migrate(delete_old=delete_old)

        click.echo(f"\nMigration complete:")
        click.echo(f"  Points migrated: {stats['points_migrated']:,}")
        click.echo(f"  New collection:  {stats['new_collection']}")
        click.echo(f"  Snapshot:        {stats['snapshot_name']}")
        click.echo(f"  Time:            {stats['elapsed_seconds']}s")

        if not delete_old:
            click.echo(f"\n  Old collection '{old_name}' preserved. Delete manually or re-run with --delete-old.")
            click.echo(f"  Update QDRANT_COLLECTION={stats['new_collection']} in .env to use new collection.")

    @cli.command()
    @click.option("--batch-size", type=int, default=32, help="Abstracts per Ollama request")
    @click.option("--concurrency", "-p", type=int, default=4, help="Parallel Ollama requests")
    @click.option("--limit", "-n", type=int, default=None, help="Max papers to embed")
    @click.option("--resume/--no-resume", default=True, help="Resume from checkpoint")
    @click.option("--dry-run", is_flag=True, help="Count papers to embed without doing it")
    def embed_papers(
        batch_size: int,
        concurrency: int,
        limit: int | None,
        resume: bool,
        dry_run: bool,
    ) -> None:
        """Embed paper abstracts with Qwen3-8B and BM25 sparse vectors.

        Reads non-stub papers with abstracts from Qdrant, generates dense
        embeddings via Ollama, and upserts both dense + BM25 vectors.

        Examples:

          # Embed all papers (resume from checkpoint)
          uv run python -m src.cli.core_collect embed-papers

          # Embed with higher concurrency
          uv run python -m src.cli.core_collect embed-papers -p 8

          # Embed first 100 papers (for testing)
          uv run python -m src.cli.core_collect embed-papers -n 100

          # Start fresh (ignore checkpoint)
          uv run python -m src.cli.core_collect embed-papers --no-resume
        """
        from datetime import datetime, timezone
        from pathlib import Path
        import json

        from src.core.embedding.embedder import PaperEmbedder
        from src.core.storage.base import QdrantStorage

        CHECKPOINT_DIR = Path("data/core/checkpoints")
        CHECKPOINT_FILE = CHECKPOINT_DIR / "embedding.json"

        storage = QdrantStorage()

        if dry_run:
            total = storage.count_papers_for_embedding()
            click.echo(f"Papers to embed: {total:,}")
            return

        # Load checkpoint (using same json pattern as CheckpointMixin)
        processed_ids: set[str] = set()
        if resume and CHECKPOINT_FILE.exists():
            try:
                with open(CHECKPOINT_FILE) as f:
                    data = json.load(f)
                processed_ids = set(data.get("processed_point_ids", []))
                click.echo(f"Resuming from checkpoint: {len(processed_ids):,} already embedded")
            except Exception as e:
                logger.warning(f"Failed to load checkpoint: {e}")

        # Pre-flight: verify collection has vector config
        try:
            info = storage.client.get_collection(storage.collection_name)
            vectors = info.config.params.vectors
            if not vectors or "abstract-qwen3-8b" not in vectors:
                click.echo(
                    "Error: Collection missing vector config. "
                    "Run: uv run python -m src.cli.core_collect migrate-collection",
                    err=True,
                )
                sys.exit(1)
        except Exception as e:
            click.echo(f"Error: Cannot connect to Qdrant: {e}", err=True)
            sys.exit(1)

        async def run():
            embedder = PaperEmbedder(max_concurrent=concurrency)
            async with embedder:
                # Check model availability
                if not await embedder.check_model_available():
                    click.echo(
                        "Error: Embedding model not found in Ollama. "
                        "Run: ollama pull qwen3-embedding:8b",
                        err=True,
                    )
                    sys.exit(1)

                total_embedded = 0
                offset = None

                while True:
                    papers, next_offset = storage.readers.get_papers_for_embedding(
                        limit=batch_size,
                        offset=offset,
                    )

                    if not papers:
                        break

                    # Filter out already-processed papers
                    papers = [(pid, p) for pid, p in papers if pid not in processed_ids]

                    if papers:
                        count = await embedder.embed_and_upsert_batch(
                            papers=papers,
                            storage=storage,
                        )
                        total_embedded += count

                        # Update checkpoint
                        for pid, _ in papers:
                            processed_ids.add(pid)
                        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
                        with open(CHECKPOINT_FILE, "w") as f:
                            json.dump({
                                "processed_point_ids": list(processed_ids),
                                "total_embedded": total_embedded,
                                "last_updated": datetime.now(timezone.utc).isoformat(),
                            }, f)

                        if total_embedded % 1000 == 0:
                            click.echo(f"  Embedded {total_embedded:,} papers...")

                    if limit and total_embedded >= limit:
                        break

                    if next_offset is None:
                        break
                    offset = next_offset

                click.echo(f"\nEmbedding complete: {total_embedded:,} papers embedded")

        asyncio.run(run())
```

- [ ] **Step 2: Register commands in `src/cli/core_collect.py`**

Add import and registration:

```python
from src.cli.commands import embedding

# In the section where commands are registered:
embedding.register_commands(cli)
```

- [ ] **Step 3: Test CLI commands exist**

Run: `uv run python -m src.cli.core_collect migrate-collection --help`
Expected: Shows help text for migrate-collection

Run: `uv run python -m src.cli.core_collect embed-papers --help`
Expected: Shows help text for embed-papers

- [ ] **Step 4: Commit**

```bash
git add src/cli/commands/embedding.py src/cli/core_collect.py
git commit -m "feat: add migrate-collection and embed-papers CLI commands"
```

---

### Task 8: Create shell scripts

**Files:**
- Create: `scripts/embedding/migrate_collection.sh`
- Create: `scripts/embedding/run_embedding.sh`

- [ ] **Step 1: Create migration script**

Create `scripts/embedding/migrate_collection.sh`:

```bash
#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

NEW_COLLECTION=${NEW_COLLECTION:-}

echo "=========================================="
echo "LexiconArxiv Collection Migration"
echo "=========================================="
echo "Migrating payload-only → vector-enabled"
echo "=========================================="

# Build command
CMD="uv run python -m src.cli.core_collect migrate-collection"
if [ -n "$NEW_COLLECTION" ]; then
    CMD="$CMD --new-collection $NEW_COLLECTION"
fi

$CMD

echo ""
echo "=========================================="
echo "Migration complete!"
echo "=========================================="
echo "Next: Update QDRANT_COLLECTION in .env, then run embedding."
```

- [ ] **Step 2: Create embedding script**

Create `scripts/embedding/run_embedding.sh`:

```bash
#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# Default values
BATCH_SIZE=${BATCH_SIZE:-32}
CONCURRENCY=${CONCURRENCY:-4}
LIMIT=${LIMIT:-}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --batch-size)
            BATCH_SIZE="$2"
            shift 2
            ;;
        --concurrency)
            CONCURRENCY="$2"
            shift 2
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --batch-size N     Abstracts per Ollama request (default: 32)"
            echo "  --concurrency N    Parallel Ollama requests (default: 4)"
            echo "  --limit N          Max papers to embed"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "LexiconArxiv Paper Embedding"
echo "=========================================="
echo "Model: qwen3-embedding:8b (1024d)"
echo "Batch Size: $BATCH_SIZE"
echo "Concurrency: $CONCURRENCY"
if [ -n "$LIMIT" ]; then
    echo "Limit: $LIMIT"
fi
echo "=========================================="

# Check Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Error: Ollama is not running. Start it with: ollama serve"
    exit 1
fi

# Check model is pulled
if ! curl -s http://localhost:11434/api/tags | grep -q "qwen3-embedding"; then
    echo "Pulling qwen3-embedding:8b model..."
    ollama pull qwen3-embedding:8b
fi

# Build command
CMD="uv run python -m src.cli.core_collect embed-papers"
CMD="$CMD --batch-size $BATCH_SIZE"
CMD="$CMD --concurrency $CONCURRENCY"
if [ -n "$LIMIT" ]; then
    CMD="$CMD --limit $LIMIT"
fi

$CMD

echo ""
echo "=========================================="
echo "Embedding complete!"
echo "=========================================="
```

- [ ] **Step 3: Make scripts executable**

```bash
chmod +x scripts/embedding/migrate_collection.sh scripts/embedding/run_embedding.sh
```

- [ ] **Step 4: Commit**

```bash
git add scripts/embedding/
git commit -m "feat: add migration and embedding shell scripts"
```

---

## Chunk 4: Integration Test

### Task 9: End-to-end integration test

**Files:**
- Add to: `tests/test_embedder.py`

- [ ] **Step 1: Write integration test (marked, skipped unless Ollama is running)**

Append to `tests/test_embedder.py`:

```python
@pytest.mark.integration
class TestEmbeddingIntegration:
    """End-to-end test: embed papers and verify hybrid search works.

    Requires: Ollama running with qwen3-embedding:8b pulled.
    Run with: uv run pytest tests/test_embedder.py -m integration -v
    """

    def setup_method(self):
        self.collection = "_test_e2e_embedding"
        self.client = QdrantClient(url="http://localhost:6333")
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

        # Create collection with vector configs
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                "abstract-qwen3-8b": models.VectorParams(
                    size=1024, distance=models.Distance.COSINE
                ),
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )

        # Insert test papers
        self.client.upsert(
            collection_name=self.collection,
            points=[
                models.PointStruct(
                    id="e2e00001-0000-0000-0000-000000000001",
                    vector={},
                    payload={
                        "title": "Attention Is All You Need",
                        "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.",
                        "is_stub": False,
                    },
                ),
                models.PointStruct(
                    id="e2e00001-0000-0000-0000-000000000002",
                    vector={},
                    payload={
                        "title": "BERT: Pre-training of Deep Bidirectional Transformers",
                        "abstract": "We introduce a new language representation model called BERT which stands for Bidirectional Encoder Representations from Transformers. BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context.",
                        "is_stub": False,
                    },
                ),
            ],
        )

    def teardown_method(self):
        try:
            self.client.delete_collection(self.collection)
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_embed_and_hybrid_search(self):
        from src.core.embedding.embedder import PaperEmbedder
        from src.core.storage.base import QdrantStorage

        storage = QdrantStorage(collection_name=self.collection)
        embedder = PaperEmbedder(target_dim=1024, max_concurrent=1)

        async with embedder:
            # Check model available
            if not await embedder.check_model_available():
                pytest.skip("Ollama qwen3-embedding:8b not available")

            # Embed papers
            papers = [
                ("e2e00001-0000-0000-0000-000000000001", {"abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms."}),
                ("e2e00001-0000-0000-0000-000000000002", {"abstract": "We introduce a new language representation model called BERT which stands for Bidirectional Encoder Representations from Transformers. BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context."}),
            ]
            count = await embedder.embed_and_upsert_batch(papers=papers, storage=storage)
            assert count == 2

            # Query: "transformer attention mechanism" should rank Attention paper first
            query_vectors = await embedder.embed_texts(["transformer attention mechanism"])
            assert query_vectors is not None

            results = self.client.query_points(
                collection_name=self.collection,
                prefetch=[
                    models.Prefetch(
                        query=query_vectors[0],
                        using="abstract-qwen3-8b",
                        limit=10,
                    ),
                    models.Prefetch(
                        query=models.Document(
                            text="transformer attention mechanism",
                            model="qdrant/bm25",
                        ),
                        using="bm25",
                        limit=10,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=2,
                with_payload=True,
            )

            assert len(results.points) == 2
            # Attention paper should rank first for "transformer attention mechanism"
            assert results.points[0].payload["title"] == "Attention Is All You Need"
```

- [ ] **Step 2: Run integration test (if Ollama available)**

Run: `uv run pytest tests/test_embedder.py::TestEmbeddingIntegration -m integration -v`
Expected: PASS (or SKIP if Ollama not available)

- [ ] **Step 3: Commit**

```bash
git add tests/test_embedder.py
git commit -m "test: add end-to-end embedding + hybrid search integration test"
```

---

## Execution Checklist

| Task | Description | Estimated Time |
|------|-------------|---------------|
| 1 | `ensure_collection_with_vectors()` | 5 min |
| 2 | Collection migration script | 10 min |
| 3 | `get_papers_for_embedding()` reader | 5 min |
| 4 | Embedding model constants | 2 min |
| 5 | Async batch embedder | 10 min |
| 6 | `embed_and_upsert_batch()` | 10 min |
| 7 | CLI commands | 10 min |
| 8 | Shell scripts | 5 min |
| 9 | Integration test | 10 min |

**After implementation:**
1. Pull the Ollama model: `ollama pull qwen3-embedding:8b`
2. Run migration: `scripts/embedding/migrate_collection.sh`
3. Update `.env`: `QDRANT_COLLECTION=lexicon_arxiv_v2`
4. Run embedding: `scripts/embedding/run_embedding.sh`
5. Verify: `uv run pytest tests/test_embedder.py -m integration -v`
