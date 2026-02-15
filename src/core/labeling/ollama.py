"""Ollama-based abstract labeling via REST API."""

import asyncio
import logging

import httpx

from src.core.constants import get_ollama_base_url
from src.core.labeling.llm_base import (
    AbstractStructure,
    BaseAbstractLabeler,
    LABELING_SYSTEM_PROMPT,
    LABELING_USER_PROMPT,
)

logger = logging.getLogger(__name__)


class OllamaAbstractLabeler(BaseAbstractLabeler):
    """Abstract labeler using local Ollama LLM."""

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

    async def label_abstract(
        self, title: str, abstract: str
    ) -> AbstractStructure | None:
        user_prompt = LABELING_USER_PROMPT.format(title=title, abstract=abstract)

        for attempt in range(self._max_retries):
            async with self._semaphore:
                try:
                    response = await self._client.post(
                        f"{self._base_url}/api/chat",
                        json={
                            "model": self._model,
                            "messages": [
                                {"role": "system", "content": LABELING_SYSTEM_PROMPT},
                                {"role": "user", "content": user_prompt},
                            ],
                            "format": AbstractStructure.model_json_schema(),
                            "stream": False,
                            "options": {"temperature": 0.1},
                        },
                    )
                    response.raise_for_status()

                    content = response.json()["message"]["content"]
                    return AbstractStructure.model_validate_json(content)

                except Exception as e:
                    if attempt < self._max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(
                            f"Ollama labeling failed (attempt {attempt + 1}/{self._max_retries}), "
                            f"retrying in {wait_time}s: {e}"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(
                            f"Ollama labeling failed after {self._max_retries} attempts: {e}"
                        )
                        return None

    async def close(self) -> None:
        await self._client.aclose()
