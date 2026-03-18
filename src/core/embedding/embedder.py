"""Async batch embedder using Ollama for dense vectors."""

import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from src.core.constants import (
    DEFAULT_EMBEDDING_MODEL,
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
