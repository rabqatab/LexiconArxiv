"""Gemini-based abstract labeling via google-genai SDK."""

import asyncio
import itertools
import logging

from google import genai
from google.genai import types

from src.core.constants import get_gemini_api_keys
from src.core.labeling.llm_base import (
    BaseAbstractLabeler,
    SentenceLabels,
    LABELING_SYSTEM_PROMPT,
    LABELING_USER_PROMPT,
    format_numbered_sentences,
)

logger = logging.getLogger(__name__)


class GeminiAbstractLabeler(BaseAbstractLabeler):
    """Abstract labeler using Gemini API with structured output.

    Supports multiple API keys for round-robin rotation across rate limits.
    """

    def __init__(
        self,
        model: str = "gemini-3-flash-preview",
        max_concurrent: int = 5,
        delay: float = 0.1,
        max_retries: int = 5,
    ):
        api_keys = get_gemini_api_keys()
        if not api_keys:
            raise ValueError(
                "Gemini API key not found. Set GEMINI_API_KEYS or GEMINI_API_KEY."
            )

        self._clients = [genai.Client(api_key=key) for key in api_keys]
        self._client_cycle = itertools.cycle(self._clients)
        self._model = model
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._delay = delay
        self._max_retries = max_retries

        if len(api_keys) > 1:
            logger.info(f"Gemini abstract labeler using {len(api_keys)} API keys (round-robin)")

    def _next_client(self) -> genai.Client:
        return next(self._client_cycle)

    async def label_sentences(
        self, title: str, abstract: str, numbered_sentences: str, num_sentences: int
    ) -> SentenceLabels | None:
        user_prompt = LABELING_USER_PROMPT.format(
            title=title, abstract=abstract, sentences=numbered_sentences
        )

        for attempt in range(self._max_retries):
            async with self._semaphore:
                try:
                    client = self._next_client()
                    response = await client.aio.models.generate_content(
                        model=self._model,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=LABELING_SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            response_schema=SentenceLabels,
                            temperature=0.1,
                        ),
                    )

                    if self._delay > 0:
                        await asyncio.sleep(self._delay)

                    return SentenceLabels.model_validate_json(response.text)

                except Exception as e:
                    if attempt < self._max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(
                            f"Gemini labeling failed (attempt {attempt + 1}/{self._max_retries}), "
                            f"retrying in {wait_time}s: {e}"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(
                            f"Gemini labeling failed after {self._max_retries} attempts: {e}"
                        )
                        return None

    async def close(self) -> None:
        pass
