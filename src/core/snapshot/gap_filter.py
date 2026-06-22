"""P3 hybrid relevance filter: ANCHOR_INJECT | CONCEPT_INJECT | REJECT.

Thresholds and taxonomy live as module constants. Override per-run via the CLI
options that wrap Thresholds.
"""
from dataclasses import dataclass
from enum import Enum


class Classification(str, Enum):
    ANCHOR_INJECT = "ANCHOR_INJECT"
    CONCEPT_INJECT = "CONCEPT_INJECT"
    REJECT = "REJECT"


@dataclass
class Thresholds:
    anchor_min_citers: int = 2
    concept_min_recent: int = 50
    concept_min_old: int = 200
    concept_min_year: int = 2018
    recent_age_years: int = 5


# OpenAlex concept IDs for AI/ML and adjacent. Update this set as the taxonomy
# evolves (the OpenAlex concepts API returns the canonical tree). These are
# the C-namespace IDs that appear in each work's `concepts[].id` (after the
# https://openalex.org/ prefix is stripped).
#
# Selected at implementation time (2026-06-21) from
# https://api.openalex.org/concepts?filter=level:1,ancestors.id:C154945302 .
AI_CONCEPT_IDS: set[str] = {
    "C154945302",  # Artificial intelligence
    "C119857082",  # Machine learning
    "C108583219",  # Deep learning
    "C204321447",  # Natural language processing
    "C31972630",   # Computer vision
    "C97541855",   # Reinforcement learning
    "C50644808",   # Artificial neural network
    "C2780451532", # Generative model
    "C2780641677", # Transformer (machine learning model)
    "C188441475",  # Knowledge graph
    "C23123220",   # Information retrieval
    "C2776760102", # Recommender system
    "C107457646",  # Robotics
    "C13280743",   # Speech recognition
    "C2776401178", # Federated learning
    "C2776194310", # Multi-agent system
    "C140779682",  # Foundation model
}


def _normalize_concept_id(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.rsplit("/", 1)[-1]


def _has_ai_concept(work: dict, taxonomy: set[str]) -> bool:
    for c in work.get("concepts") or []:
        cid = _normalize_concept_id(c.get("id"))
        if cid and cid in taxonomy:
            return True
    return False


def classify(
    work: dict,
    *,
    anchor_set: dict[str, int],
    taxonomy: set[str],
    thresholds: Thresholds,
    now_year: int,
) -> Classification:
    """Return ANCHOR_INJECT / CONCEPT_INJECT / REJECT for a single work."""
    wid = (work.get("id") or "").rsplit("/", 1)[-1]

    # Anchor path
    if wid and anchor_set.get(wid, 0) >= thresholds.anchor_min_citers:
        return Classification.ANCHOR_INJECT

    # Concept path
    if not _has_ai_concept(work, taxonomy):
        return Classification.REJECT
    year = work.get("publication_year") or 0
    if year < thresholds.concept_min_year:
        return Classification.REJECT
    citations = work.get("cited_by_count") or 0
    age = now_year - year
    if age <= thresholds.recent_age_years:
        return (
            Classification.CONCEPT_INJECT
            if citations >= thresholds.concept_min_recent
            else Classification.REJECT
        )
    return (
        Classification.CONCEPT_INJECT
        if citations >= thresholds.concept_min_old
        else Classification.REJECT
    )
