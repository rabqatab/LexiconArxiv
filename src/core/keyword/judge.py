"""Keyword judge wrapper that delegates to a configurable LLM backend."""

import logging

from src.core.keyword.llm_base import BaseLLMJudge

logger = logging.getLogger(__name__)


class KeywordJudge:
    """Thin wrapper around an LLM judge backend for keyword validation."""

    def __init__(self, backend: BaseLLMJudge):
        self._backend = backend

    async def filter_keywords(
        self, title: str, abstract: str | None, keywords: list[str]
    ) -> list[str]:
        """Filter keywords by relevance using the LLM judge.

        Args:
            title: Paper title.
            abstract: Paper abstract (if None, returns all keywords).
            keywords: Candidate keywords to judge.

        Returns:
            List of relevant keywords.
        """
        if not keywords:
            return []

        if not abstract:
            logger.debug("No abstract available, skipping judge")
            return keywords

        try:
            return await self._backend.judge_keywords(title, abstract, keywords)
        except Exception as e:
            logger.warning(f"Judge failed, returning all keywords: {e}")
            return keywords

    async def close(self) -> None:
        await self._backend.close()
