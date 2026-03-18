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
