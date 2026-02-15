"""Gemini-based keyword extraction and judging via google-genai SDK."""

import asyncio
import itertools
import logging

from google import genai
from google.genai import types

from src.core.constants import get_gemini_api_keys
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


def _make_gemini_clients(api_keys: list[str]) -> list[genai.Client]:
    """Create a genai.Client for each API key."""
    return [genai.Client(api_key=key) for key in api_keys]


class GeminiKeywordExtractor(BaseLLMExtractor):
    """Keyword extractor using Gemini API with structured output.

    Supports multiple API keys for round-robin rotation across rate limits.
    """

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        max_concurrent: int = 5,
        delay: float = 0.1,
        max_retries: int = 5,
    ):
        api_keys = get_gemini_api_keys()
        if not api_keys:
            raise ValueError(
                "Gemini API key not found. Set GEMINI_API_KEY or GOOGLE_API_KEY."
            )

        self._clients = _make_gemini_clients(api_keys)
        self._client_cycle = itertools.cycle(self._clients)
        self._model = model
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._delay = delay
        self._max_retries = max_retries

        if len(api_keys) > 1:
            logger.info(f"Gemini keyword extractor using {len(api_keys)} API keys (round-robin)")

    def _next_client(self) -> genai.Client:
        return next(self._client_cycle)

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
                    client = self._next_client()
                    response = await client.aio.models.generate_content(
                        model=self._model,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=EXTRACTION_SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            response_schema=ExtractedKeywords,
                            temperature=0.1,
                        ),
                    )

                    if self._delay > 0:
                        await asyncio.sleep(self._delay)

                    return ExtractedKeywords.model_validate_json(response.text)

                except Exception as e:
                    if attempt < self._max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(
                            f"Gemini extraction failed (attempt {attempt + 1}/{self._max_retries}), "
                            f"retrying in {wait_time}s: {e}"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(
                            f"Gemini extraction failed after {self._max_retries} attempts: {e}"
                        )
                        return None

    async def close(self) -> None:
        pass


class GeminiJudge(BaseLLMJudge):
    """Keyword judge using Gemini API with structured output.

    Supports multiple API keys for round-robin rotation across rate limits.
    """

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        max_concurrent: int = 5,
        delay: float = 0.1,
    ):
        api_keys = get_gemini_api_keys()
        if not api_keys:
            raise ValueError(
                "Gemini API key not found. Set GEMINI_API_KEY or GOOGLE_API_KEY."
            )

        self._clients = _make_gemini_clients(api_keys)
        self._client_cycle = itertools.cycle(self._clients)
        self._model = model
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._delay = delay

        if len(api_keys) > 1:
            logger.info(f"Gemini judge using {len(api_keys)} API keys (round-robin)")

    def _next_client(self) -> genai.Client:
        return next(self._client_cycle)

    async def judge_keywords(
        self, title: str, abstract: str, keywords: list[str]
    ) -> list[str]:
        async with self._semaphore:
            try:
                client = self._next_client()
                response = await client.aio.models.generate_content(
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
