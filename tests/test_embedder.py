import pytest
import respx
from httpx import Response

from src.core.embedding.embedder import PaperEmbedder


class TestPaperEmbedder:
    """Test embedding generation via Ollama."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_embed_single_abstract(self):
        fake_embedding = list(range(4096))
        route = respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(200, json={"embeddings": [fake_embedding]}),
        )
        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            model="qwen3-embedding:8b",
            target_dim=1024,
        )
        async with embedder:
            vectors = await embedder.embed_texts(["Test abstract about ML"])
        assert len(vectors) == 1
        assert len(vectors[0]) == 1024
        assert vectors[0] == list(range(1024))
        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_embed_batch(self):
        fake_embeddings = [list(range(4096)) for _ in range(3)]
        respx.post("http://localhost:11434/api/embed").mock(
            return_value=Response(200, json={"embeddings": fake_embeddings}),
        )
        embedder = PaperEmbedder(
            ollama_base_url="http://localhost:11434",
            model="qwen3-embedding:8b",
            target_dim=1024,
        )
        async with embedder:
            vectors = await embedder.embed_texts(["Abstract one", "Abstract two", "Abstract three"])
        assert len(vectors) == 3
        assert all(len(v) == 1024 for v in vectors)

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_failure(self):
        fake_embedding = list(range(4096))
        route = respx.post("http://localhost:11434/api/embed")
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
