"""Abstract sentence labeling module for Core Corpus papers.

Classifies each sentence in paper abstracts into structured rhetorical roles
(task, domain, background, approach, method, result, contribution) using
LLM-based labeling via Ollama.
"""

from src.core.labeling.labeler import AbstractLabeler
from src.core.labeling.llm_base import AbstractStructure

__all__ = [
    "AbstractLabeler",
    "AbstractStructure",
]
