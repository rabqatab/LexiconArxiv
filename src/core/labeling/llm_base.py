"""Shared models, prompts, and base classes for LLM-based abstract labeling."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


# =============================================================================
# Pydantic Response Model
# =============================================================================


class AbstractStructure(BaseModel):
    """Structured output from LLM abstract sentence labeling.

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
    "Given a paper's title and abstract, split the abstract into individual sentences "
    "and classify each sentence into one or more rhetorical roles.\n\n"
    "The 7 roles are:\n"
    "- task: sentences that state the problem being addressed or the objective of the work\n"
    "- domain: sentences that describe the application area or research field\n"
    "- background: sentences about prior work, limitations of existing methods, or motivation\n"
    "- approach: sentences describing the key idea, novelty, or proposed solution at a high level\n"
    "- method: sentences about implementation details, architecture, or technical specifics\n"
    "- result: sentences reporting datasets used, experimental setup, scores, ablations, or findings\n"
    "- contribution: sentences that explicitly claim contributions or summarize impact\n\n"
    "Rules:\n"
    "1. Split the abstract at sentence boundaries. Keep each sentence verbatim (do not paraphrase).\n"
    "2. A sentence may appear in multiple roles if it serves more than one function.\n"
    "3. Use the paper title only as context to understand the topic — do not classify the title itself.\n"
    "4. Empty lists are valid — not every abstract contains all roles.\n"
    "5. Every sentence in the abstract must appear in at least one role."
)

LABELING_USER_PROMPT = (
    "Classify each sentence in this abstract into rhetorical roles:\n\n"
    "Title: {title}\n\n"
    "Abstract: {abstract}\n\n"
    "Return the result as structured JSON with fields: "
    "task, domain, background, approach, method, result, contribution."
)


# =============================================================================
# Abstract Base Class
# =============================================================================


class BaseAbstractLabeler(ABC):
    """Abstract base class for LLM-based abstract labelers."""

    @abstractmethod
    async def label_abstract(
        self, title: str, abstract: str
    ) -> AbstractStructure | None:
        """Label an abstract's sentences into rhetorical roles.

        Args:
            title: Paper title (used as context only).
            abstract: Paper abstract to classify.

        Returns:
            Structured abstract labeling, or None on failure.
        """

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources."""
