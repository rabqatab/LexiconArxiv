"""Shared models, prompts, and base classes for LLM-based keyword extraction."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


# =============================================================================
# Pydantic Response Models
# =============================================================================


class ExtractedKeywords(BaseModel):
    """Structured output from LLM keyword extraction.

    Used as Gemini response_schema and Ollama format schema.
    """

    acronyms: list[str]
    methods: list[str]
    concepts: list[str]


class JudgeResult(BaseModel):
    """Structured output from LLM judge validation."""

    relevant: list[str]
    irrelevant: list[str]


# =============================================================================
# Prompt Templates
# =============================================================================

EXTRACTION_SYSTEM_PROMPT = (
    "You are an expert academic keyword extractor. "
    "Given a research paper's title and abstract, extract the most important "
    "technical keywords. Focus on:\n"
    "- Acronyms: model names, method abbreviations (e.g. BERT, RAG, LoRA)\n"
    "- Methods: specific techniques or algorithms mentioned\n"
    "- Concepts: key technical concepts central to the paper\n\n"
    "Return only keywords that are specific and meaningful. "
    "Avoid generic terms like 'model', 'method', 'approach', 'paper', 'results'."
)

EXTRACTION_USER_PROMPT = (
    "Extract keywords from this research paper:\n\n"
    "Title: {title}\n\n"
    "Abstract: {abstract}\n\n"
    "Return the keywords as structured JSON with fields: "
    "acronyms, methods, concepts."
)

JUDGE_SYSTEM_PROMPT = (
    "You are an expert academic keyword judge. "
    "Given a research paper's title, abstract, and a list of candidate keywords, "
    "determine which keywords are truly relevant to the paper's core contribution "
    "and which are not.\n\n"
    "A keyword is relevant if it:\n"
    "- Names a specific model, method, or technique discussed in the paper\n"
    "- Represents a core concept central to the paper's contribution\n"
    "- Is a well-known acronym used meaningfully in the paper\n\n"
    "A keyword is irrelevant if it:\n"
    "- Is too generic (e.g. 'deep learning' for any ML paper)\n"
    "- Is only mentioned in passing, not central to the paper\n"
    "- Is a common word mistakenly extracted as a keyword"
)

JUDGE_USER_PROMPT = (
    "Judge these candidate keywords for relevance:\n\n"
    "Title: {title}\n\n"
    "Abstract: {abstract}\n\n"
    "Candidate keywords: {keywords}\n\n"
    "Classify each keyword as relevant or irrelevant."
)


# =============================================================================
# Abstract Base Classes
# =============================================================================


class BaseLLMExtractor(ABC):
    """Abstract base class for LLM-based keyword extractors."""

    @abstractmethod
    async def extract_keywords(self, title: str, abstract: str) -> list[str]:
        """Extract keywords from a paper's title and abstract.

        Args:
            title: Paper title.
            abstract: Paper abstract.

        Returns:
            Flat list of extracted keywords.
        """

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""

    @staticmethod
    def _flatten_extraction(result: ExtractedKeywords) -> list[str]:
        """Flatten an ExtractedKeywords model into a single keyword list."""
        keywords: list[str] = []
        keywords.extend(result.acronyms)
        keywords.extend(result.methods)
        keywords.extend(result.concepts)
        return keywords


class BaseLLMJudge(ABC):
    """Abstract base class for LLM-based keyword judges."""

    @abstractmethod
    async def judge_keywords(
        self, title: str, abstract: str, keywords: list[str]
    ) -> list[str]:
        """Judge which keywords are relevant to the paper.

        Args:
            title: Paper title.
            abstract: Paper abstract.
            keywords: Candidate keywords to judge.

        Returns:
            List of relevant keywords (subset of input).
        """

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
