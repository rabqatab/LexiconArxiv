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
    EXTRACTION_USER_PROMPT_TITLE_ONLY,
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
        timeout: float = 180.0,
        max_retries: int = 5,
    ):
        self._model = model
        self._base_url = base_url or get_ollama_base_url()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._client = httpx.AsyncClient(timeout=timeout)
        self._max_retries = max_retries

    async def extract_keywords(
        self, title: str, abstract: str | None = None
    ) -> ExtractedKeywords | None:
        if abstract:
            user_prompt = EXTRACTION_USER_PROMPT.format(title=title, abstract=abstract)
        else:
            user_prompt = EXTRACTION_USER_PROMPT_TITLE_ONLY.format(title=title)

        for attempt in range(self._max_retries):
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
                                    "content": user_prompt,
                                },
                            ],
                            "format": ExtractedKeywords.model_json_schema(),
                            "stream": False,
                            "options": {"temperature": 0.1},
                        },
                    )
                    response.raise_for_status()

                    content = response.json()["message"]["content"]
                    return ExtractedKeywords.model_validate_json(content)

                except Exception as e:
                    if attempt < self._max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(
                            f"Ollama extraction failed (attempt {attempt + 1}/{self._max_retries}), "
                            f"retrying in {wait_time}s: {e}"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(
                            f"Ollama extraction failed after {self._max_retries} attempts: {e}"
                        )
                        return None

    async def close(self) -> None:
        await self._client.aclose()


class OllamaJudge(BaseLLMJudge):
    """Keyword judge using local Ollama LLM."""

    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: str | None = None,
        max_concurrent: int = 1,
        timeout: float = 180.0,
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
                        "options": {"temperature": 0.0},
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
