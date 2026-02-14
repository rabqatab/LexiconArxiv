"""Gemini-based keyword extraction and judging via google-genai SDK."""

import asyncio
import logging

from google import genai
from google.genai import types

from src.core.constants import get_gemini_api_key
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


class GeminiKeywordExtractor(BaseLLMExtractor):
    """Keyword extractor using Gemini API with structured output."""

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        max_concurrent: int = 5,
        delay: float = 0.1,
    ):
        api_key = get_gemini_api_key()
        if not api_key:
            raise ValueError(
                "Gemini API key not found. Set GEMINI_API_KEY or GOOGLE_API_KEY."
            )

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._delay = delay

    async def extract_keywords(self, title: str, abstract: str) -> list[str]:
        async with self._semaphore:
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=EXTRACTION_USER_PROMPT.format(
                        title=title, abstract=abstract
                    ),
                    config=types.GenerateContentConfig(
                        system_instruction=EXTRACTION_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=ExtractedKeywords,
                        temperature=0.1,
                    ),
                )

                if self._delay > 0:
                    await asyncio.sleep(self._delay)

                parsed = ExtractedKeywords.model_validate_json(response.text)
                return self._flatten_extraction(parsed)

            except Exception as e:
                logger.warning(f"Gemini extraction failed: {e}")
                return []

    async def close(self) -> None:
        pass


class GeminiJudge(BaseLLMJudge):
    """Keyword judge using Gemini API with structured output."""

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        max_concurrent: int = 5,
        delay: float = 0.1,
    ):
        api_key = get_gemini_api_key()
        if not api_key:
            raise ValueError(
                "Gemini API key not found. Set GEMINI_API_KEY or GOOGLE_API_KEY."
            )

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._delay = delay

    async def judge_keywords(
        self, title: str, abstract: str, keywords: list[str]
    ) -> list[str]:
        async with self._semaphore:
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=JUDGE_USER_PROMPT.format(
                        title=title,
                        abstract=abstract,
                        keywords=", ".join(keywords),
                    ),
                    config=types.GenerateContentConfig(
                        system_instruction=JUDGE_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=JudgeResult,
                        temperature=0.0,
                    ),
                )

                if self._delay > 0:
                    await asyncio.sleep(self._delay)

                parsed = JudgeResult.model_validate_json(response.text)
                return parsed.relevant

            except Exception as e:
                logger.warning(f"Gemini judge failed, returning all keywords: {e}")
                return keywords

    async def close(self) -> None:
        pass
