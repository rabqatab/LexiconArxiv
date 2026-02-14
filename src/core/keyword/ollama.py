"""Ollama-based keyword extraction and judging via REST API."""

import asyncio
import logging

import httpx

from src.core.constants import get_ollama_base_url
from src.core.keyword.llm_base import (
    BaseLLMExtractor,
    BaseLLMJudge,
    ExtractedKeywords,
    JudgeResult,
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT,
    JUDGE_SYSTEM_PROMPT,
    JUDGE_USER_PROMPT,
)

logger = logging.getLogger(__name__)


class OllamaKeywordExtractor(BaseLLMExtractor):
    """Keyword extractor using local Ollama LLM."""

    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: str | None = None,
        max_concurrent: int = 1,
        timeout: float = 60.0,
    ):
        self._model = model
        self._base_url = base_url or get_ollama_base_url()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client = httpx.AsyncClient(timeout=timeout)

    async def extract_keywords(self, title: str, abstract: str) -> list[str]:
        async with self._semaphore:
            try:
                response = await self._client.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": EXTRACTION_USER_PROMPT.format(
                                    title=title, abstract=abstract
                                ),
                            },
                        ],
                        "format": ExtractedKeywords.model_json_schema(),
                        "stream": False,
                    },
                )
                response.raise_for_status()

                content = response.json()["message"]["content"]
                parsed = ExtractedKeywords.model_validate_json(content)
                return self._flatten_extraction(parsed)

            except Exception as e:
                logger.warning(f"Ollama extraction failed: {e}")
                return []

    async def close(self) -> None:
        await self._client.aclose()


class OllamaJudge(BaseLLMJudge):
    """Keyword judge using local Ollama LLM."""

    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: str | None = None,
        max_concurrent: int = 1,
        timeout: float = 60.0,
    ):
        self._model = model
        self._base_url = base_url or get_ollama_base_url()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client = httpx.AsyncClient(timeout=timeout)

    async def judge_keywords(
        self, title: str, abstract: str, keywords: list[str]
    ) -> list[str]:
        async with self._semaphore:
            try:
                response = await self._client.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": JUDGE_USER_PROMPT.format(
                                    title=title,
                                    abstract=abstract,
                                    keywords=", ".join(keywords),
                                ),
                            },
                        ],
                        "format": JudgeResult.model_json_schema(),
                        "stream": False,
                    },
                )
                response.raise_for_status()

                content = response.json()["message"]["content"]
                parsed = JudgeResult.model_validate_json(content)
                return parsed.relevant

            except Exception as e:
                logger.warning(f"Ollama judge failed, returning all keywords: {e}")
                return keywords

    async def close(self) -> None:
        await self._client.aclose()
