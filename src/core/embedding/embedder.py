"""Async batch embedder using Ollama for dense vectors."""

import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from qdrant_client import models as qdrant_models

from src.core.constants import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_VECTOR_NAME,
    EMBEDDING_VECTOR_SIZE,
    SECTION_ROLES,
    SECTION_VECTOR_PREFIX,
    STRUCTURED_VECTOR_NAME,
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
    """Embed paper abstracts via Ollama and update vectors in Qdrant."""

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
                        wait_time = 2 ** attempt
                        logger.warning(
                            f"Embed failed (attempt {attempt + 1}/{self._max_retries}), "
                            f"retrying in {wait_time}s: {e}"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"Embed failed after {self._max_retries} attempts: {e}")
                        return None

    async def check_model_available(self) -> bool:
        """Check if the embedding model is loaded in Ollama."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")
        try:
            response = await self._client.get(f"{self._base_url}/api/tags")
            response.raise_for_status()
            model_list = response.json().get("models", [])
            model_names = [m.get("name", "") for m in model_list]
            available = any(self._model in name for name in model_names)
            if not available:
                logger.warning(
                    f"Model '{self._model}' not found in Ollama. Available: {model_names}"
                )
            return available
        except Exception as e:
            logger.error(f"Failed to check Ollama models: {e}")
            return False

    async def embed_and_upsert_batch(
        self,
        papers: list[tuple[str, dict]],
        storage: "QdrantStorage",
        embed_batch_size: int = 64,
    ) -> int:
        """Embed abstracts (full, structured, per-section) and update vectors in Qdrant.

        Uses client.update_vectors() -- NOT upsert -- to attach vectors
        to existing points without touching their payloads.

        For each paper, generates up to 9 dense vectors:
          1. abstract-qwen3-8b: full abstract embedding
          2. structured-abstract: section-prefixed concatenation
          3-9. section-{role}: per-section embeddings (only if abstract_structure exists)

        Plus 1 BM25 sparse vector per paper.

        Args:
            papers: List of (point_id, payload) tuples. payload must have "abstract",
                    optionally "abstract_structure".
            storage: QdrantStorage instance.
            embed_batch_size: Max texts per Ollama embed call.

        Returns:
            Number of points successfully embedded and updated.
        """
        # Collect ALL texts to embed in one big list
        all_texts: list[str] = []
        text_map: list[tuple[int, str]] = []  # (paper_index, vector_name)

        for i, (point_id, payload) in enumerate(papers):
            abstract = payload.get("abstract") or ""
            structure = payload.get("abstract_structure") or {}

            # 1. Full abstract vector
            all_texts.append(f"Retrieve academic papers: {abstract}")
            text_map.append((i, EMBEDDING_VECTOR_NAME))

            # 2. Structured abstract vector
            if structure:
                parts = []
                for role in SECTION_ROLES:
                    sents = structure.get(role, [])
                    if sents:
                        parts.append(f"[{role.upper()}] {' '.join(sents)}")
                structured = " ".join(parts) if parts else abstract
            else:
                structured = abstract
            all_texts.append(f"Retrieve academic papers: {structured}")
            text_map.append((i, STRUCTURED_VECTOR_NAME))

            # 3. Per-section vectors (only if abstract_structure exists)
            if structure:
                for role in SECTION_ROLES:
                    sents = structure.get(role, [])
                    if sents:
                        all_texts.append(
                            f"Retrieve academic papers {role}: {' '.join(sents)}"
                        )
                        text_map.append((i, f"{SECTION_VECTOR_PREFIX}{role}"))

        if not all_texts:
            return 0

        # Embed all texts in chunks of embed_batch_size
        all_vectors: list[list[float]] = []
        for chunk_start in range(0, len(all_texts), embed_batch_size):
            chunk = all_texts[chunk_start : chunk_start + embed_batch_size]
            vectors = await self.embed_texts(chunk)
            if vectors is None:
                logger.error(
                    f"Failed to get embeddings for chunk starting at index {chunk_start}"
                )
                return 0
            all_vectors.extend(vectors)

        # Distribute vectors back to per-paper dicts
        paper_vectors: list[dict] = [{} for _ in papers]
        for idx, (paper_idx, vector_name) in enumerate(text_map):
            paper_vectors[paper_idx][vector_name] = all_vectors[idx]

        # Build PointVectors for update_vectors (preserves existing payloads)
        point_vectors = []
        for (point_id, payload), vectors_dict in zip(papers, paper_vectors):
            combined = dict(vectors_dict)
            # Add BM25 sparse vector
            combined["bm25"] = qdrant_models.Document(
                text=payload.get("abstract") or "",
                model="qdrant/bm25",
            )
            point_vectors.append(
                qdrant_models.PointVectors(
                    id=point_id,
                    vector=combined,
                )
            )

        # Update vectors only -- payloads are untouched
        storage.client.update_vectors(
            collection_name=storage.collection_name,
            points=point_vectors,
        )

        return len(point_vectors)
