"""Shared models, prompts, and base classes for LLM-based keyword extraction."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


# =============================================================================
# Pydantic Response Models
# =============================================================================


class ExtractedKeywords(BaseModel):
    """Structured output from LLM keyword extraction.

    Used as Ollama format schema.
    Categories are research-oriented for academic papers.
    """

    task: list[str]
    method: list[str]
    model: list[str]
    domain: list[str]
    dataset: list[str]
    contribution_type: list[str]
    modality: list[str]

    def to_dict(self) -> dict[str, list[str]]:
        return self.model_dump()


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
    "technical keywords into 7 categories:\n\n"
    "- task: the specific problem or objective the paper addresses "
    "(e.g. 'text classification', 'machine translation', 'question answering')\n"
    "- method: techniques, algorithms, or approaches used "
    "(e.g. 'contrastive learning', 'attention mechanism', 'fine-tuning')\n"
    "- model: named models or systems — proper nouns "
    "(e.g. 'BERT', 'GPT-4', 'LLaMA', 'T5')\n"
    "- domain: application area or research field "
    "(e.g. 'NLP', 'computer vision', 'legal AI', 'biomedical')\n"
    "- dataset: benchmarks, datasets, or evaluation resources "
    "(e.g. 'GLUE', 'SQuAD', 'ImageNet', 'MS MARCO')\n"
    "- contribution_type: the kind of contribution this paper makes "
    "(e.g. 'model', 'survey', 'benchmark', 'dataset', 'system', 'method', "
    "'analysis', 'application', 'toolkit', 'position paper')\n"
    "- modality: data types or modalities the paper works with "
    "(e.g. 'text', 'image', 'audio', 'video', 'code', 'tabular', 'graph', "
    "'multimodal', 'time series', 'point cloud')\n\n"
    "Disambiguation examples:\n"
    "- 'transformer' -> model if referring to the original paper's model, "
    "method if referring to the architecture in general\n"
    "- 'BERT' -> always model (it's a named system)\n"
    "- 'self-attention' -> always method (it's a technique)\n\n"
    "Return only keywords that are specific and meaningful. "
    "Avoid generic terms like 'model', 'method', 'approach', 'paper', 'results'."
)

EXTRACTION_USER_PROMPT = (
    "Extract keywords from this research paper:\n\n"
    "Title: {title}\n\n"
    "Abstract: {abstract}\n\n"
    "Return the keywords as structured JSON with fields: "
    "task, method, model, domain, dataset, contribution_type, modality."
)

EXTRACTION_USER_PROMPT_TITLE_ONLY = (
    "Extract keywords from this research paper based on its title:\n\n"
    "Title: {title}\n\n"
    "Return the keywords as structured JSON with fields: "
    "task, method, model, domain, dataset, contribution_type, modality."
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
    async def extract_keywords(
        self, title: str, abstract: str | None = None
    ) -> ExtractedKeywords | None:
        """Extract keywords from a paper's title and optional abstract.

        Args:
            title: Paper title.
            abstract: Paper abstract (optional).

        Returns:
            Structured extracted keywords, or None on failure.
        """

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""

    @staticmethod
    def _flatten_extraction(result: ExtractedKeywords) -> list[str]:
        """Flatten an ExtractedKeywords model into a single keyword list."""
        keywords: list[str] = []
        for field in ("task", "method", "model", "domain", "dataset",
                      "contribution_type", "modality"):
            keywords.extend(getattr(result, field))
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
