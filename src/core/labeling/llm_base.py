"""Shared models, prompts, and base classes for LLM-based abstract labeling."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


# =============================================================================
# Rhetorical Roles
# =============================================================================

ROLES = ("task", "domain", "background", "approach", "method", "result", "contribution")


# =============================================================================
# Pydantic Response Models
# =============================================================================


class SentenceLabel(BaseModel):
    """Label assignment for a single sentence."""

    index: int
    labels: list[str]


class SentenceLabels(BaseModel):
    """LLM response: label assignments for each sentence by index."""

    labels: list[SentenceLabel]


class AbstractStructure(BaseModel):
    """Structured output stored in Qdrant.

    Each field contains a list of verbatim sentences from the abstract
    classified into that rhetorical role. A sentence may appear in
    multiple roles (multi-label).
    """

    task: list[str]
    domain: list[str]
    background: list[str]
    approach: list[str]
    method: list[str]
    result: list[str]
    contribution: list[str]

    def to_dict(self) -> dict[str, list[str]]:
        return self.model_dump()


# =============================================================================
# Prompt Templates
# =============================================================================

LABELING_SYSTEM_PROMPT = (
    "You are an expert at analyzing the rhetorical structure of academic paper abstracts. "
    "Given a paper's title and a numbered list of sentences from the abstract, "
    "classify each sentence into one or more rhetorical roles by its index number.\n\n"
    "The 7 roles are:\n"
    "- task: sentences that state the problem being addressed or the objective of the work\n"
    "- domain: sentences that describe the application area or research field\n"
    "- background: sentences about prior work, limitations of existing methods, or motivation\n"
    "- approach: sentences describing the key idea, novelty, or proposed solution at a high level\n"
    "- method: sentences about implementation details, architecture, or technical specifics\n"
    "- result: sentences reporting datasets used, experimental setup, scores, ablations, or findings\n"
    "- contribution: sentences that explicitly claim contributions or summarize impact\n\n"
    "Rules:\n"
    "1. Refer to sentences ONLY by their index number. Do not reproduce the sentence text.\n"
    "2. A sentence may have multiple labels if it serves more than one function.\n"
    "3. Use the paper title only as context to understand the topic.\n"
    "4. Every sentence index must appear exactly once in the output.\n"
    "5. Labels must be from: task, domain, background, approach, method, result, contribution."
)

LABELING_USER_PROMPT = (
    "Classify each sentence by index into rhetorical roles.\n\n"
    "Title: {title}\n\n"
    "Full abstract (for context):\n{abstract}\n\n"
    "Sentences to classify:\n{sentences}\n\n"
    "Return JSON with a \"labels\" array where each item has "
    "\"index\" (int) and \"labels\" (list of role strings)."
)


def format_numbered_sentences(sentences: list[str]) -> str:
    """Format sentences as a numbered list for the prompt."""
    return "\n".join(f"[{i}] {s.strip()}" for i, s in enumerate(sentences))


def build_abstract_structure(
    sentences: list[str], labels: SentenceLabels
) -> AbstractStructure:
    """Map index-based labels back to verbatim sentences.

    Args:
        sentences: Original sentence list from pysbd.
        labels: LLM response with index → role mappings.

    Returns:
        AbstractStructure with verbatim sentences in each role.
    """
    result: dict[str, list[str]] = {role: [] for role in ROLES}

    for item in labels.labels:
        if 0 <= item.index < len(sentences):
            sentence = sentences[item.index].strip()
            for label in item.labels:
                if label in result:
                    result[label].append(sentence)

    return AbstractStructure(**result)


# =============================================================================
# Abstract Base Class
# =============================================================================


class BaseAbstractLabeler(ABC):
    """Abstract base class for LLM-based abstract labelers."""

    @abstractmethod
    async def label_sentences(
        self, title: str, abstract: str, numbered_sentences: str, num_sentences: int
    ) -> SentenceLabels | None:
        """Classify numbered sentences into rhetorical roles.

        Args:
            title: Paper title (used as context only).
            abstract: Full abstract text (for context).
            numbered_sentences: Formatted string of numbered sentences.
            num_sentences: Total number of sentences (for validation).

        Returns:
            Index-based label assignments, or None on failure.
        """

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
