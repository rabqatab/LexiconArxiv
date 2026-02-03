"""Deduplication logic for Core Corpus papers.

Provides DOI exact match and Title+Year fuzzy matching for deduplication.
Supports cross-source deduplication when merging papers from multiple sources.
"""

import logging
import re
from dataclasses import dataclass

from src.models.paper import RawPaper, SourceType

logger = logging.getLogger(__name__)

# Source priority for cross-source deduplication
# Higher priority sources are preferred when merging duplicates
# Lower number = higher priority
SOURCE_PRIORITY = {
    SourceType.OPENALEX: 1,  # Best metadata quality
    SourceType.OPENREVIEW: 2,  # Has reviews/decisions
    SourceType.ACL: 3,  # Good for NLP papers
    SourceType.ACM: 4,  # Good abstracts
    SourceType.DBLP: 5,  # Basic metadata
    SourceType.AAAI: 6,  # Basic metadata
    SourceType.ARXIV: 7,
    SourceType.SEMANTIC_SCHOLAR: 8,
}


@dataclass
class DuplicateResult:
    """Result of a duplicate check."""

    is_duplicate: bool
    match_type: str | None = None  # "doi", "openalex_id", "acl_id", "title_year"
    matched_id: str | None = None  # ID of the existing paper
    matched_source: SourceType | None = None  # Source of the matched paper
    confidence: float = 1.0  # 1.0 for exact match, lower for fuzzy


class Deduplicator:
    """Deduplication checker for papers.

    Uses a combination of exact matching (DOI, OpenAlex ID, ACL ID) and
    fuzzy matching (normalized title + year) to detect duplicates.
    Supports cross-source deduplication with source priority.
    """

    def __init__(self):
        """Initialize deduplicator with empty seen sets."""
        self._seen_dois: dict[str, tuple[str, SourceType]] = {}  # doi -> (id, source)
        self._seen_openalex_ids: set[str] = set()
        self._seen_acl_ids: set[str] = set()
        self._seen_title_years: dict[str, tuple[str, SourceType]] = {}  # key -> (id, source)

    @staticmethod
    def normalize_title(title: str) -> str:
        """Normalize a title for comparison.

        - Lowercase
        - Remove punctuation
        - Collapse whitespace
        - Remove common prefixes/suffixes

        Args:
            title: The title to normalize.

        Returns:
            Normalized title string.
        """
        if not title:
            return ""

        # Lowercase
        normalized = title.lower()

        # Remove punctuation
        normalized = re.sub(r"[^\w\s]", "", normalized)

        # Collapse whitespace
        normalized = " ".join(normalized.split())

        return normalized

    @staticmethod
    def make_title_year_key(title: str, year: int | None) -> str:
        """Create a key from normalized title and year.

        Args:
            title: Paper title.
            year: Publication year.

        Returns:
            Combined key for lookup.
        """
        normalized = Deduplicator.normalize_title(title)
        year_str = str(year) if year else "unknown"
        return f"{normalized}|{year_str}"

    def check_duplicate(self, paper: RawPaper) -> DuplicateResult:
        """Check if a paper is a duplicate.

        Checks in order:
        1. DOI exact match
        2. OpenAlex ID exact match
        3. ACL ID exact match
        4. Normalized title + year match

        Args:
            paper: The paper to check.

        Returns:
            DuplicateResult indicating if and how it's a duplicate.
        """
        # Check DOI first (most reliable)
        if paper.doi:
            doi_lower = paper.doi.lower()
            if doi_lower in self._seen_dois:
                matched_id, matched_source = self._seen_dois[doi_lower]
                return DuplicateResult(
                    is_duplicate=True,
                    match_type="doi",
                    matched_id=matched_id,
                    matched_source=matched_source,
                    confidence=1.0,
                )

        # Check OpenAlex ID
        if paper.openalex_id:
            if paper.openalex_id in self._seen_openalex_ids:
                return DuplicateResult(
                    is_duplicate=True,
                    match_type="openalex_id",
                    matched_id=paper.openalex_id,
                    matched_source=SourceType.OPENALEX,
                    confidence=1.0,
                )

        # Check ACL ID
        if paper.acl_id:
            if paper.acl_id in self._seen_acl_ids:
                return DuplicateResult(
                    is_duplicate=True,
                    match_type="acl_id",
                    matched_id=paper.acl_id,
                    matched_source=SourceType.ACL,
                    confidence=1.0,
                )

        # Check title + year
        if paper.title:
            title_year_key = self.make_title_year_key(paper.title, paper.year)
            if title_year_key in self._seen_title_years:
                matched_id, matched_source = self._seen_title_years[title_year_key]
                return DuplicateResult(
                    is_duplicate=True,
                    match_type="title_year",
                    matched_id=matched_id,
                    matched_source=matched_source,
                    confidence=0.95,  # Slightly lower confidence for title match
                )

        # Not a duplicate
        return DuplicateResult(is_duplicate=False)

    def add_paper(self, paper: RawPaper) -> None:
        """Add a paper to the seen sets.

        Args:
            paper: The paper to add.
        """
        source = SourceType(paper.source) if isinstance(paper.source, str) else paper.source
        primary_id = paper.doi or paper.openalex_id or paper.acl_id or paper.source_id

        if paper.doi:
            self._seen_dois[paper.doi.lower()] = (primary_id, source)

        if paper.openalex_id:
            self._seen_openalex_ids.add(paper.openalex_id)

        if paper.acl_id:
            self._seen_acl_ids.add(paper.acl_id)

        if paper.title:
            title_year_key = self.make_title_year_key(paper.title, paper.year)
            if title_year_key not in self._seen_title_years:
                self._seen_title_years[title_year_key] = (primary_id, source)

    def check_and_add(self, paper: RawPaper) -> DuplicateResult:
        """Check if paper is duplicate and add if not.

        Args:
            paper: The paper to check and potentially add.

        Returns:
            DuplicateResult indicating if it was a duplicate.
        """
        result = self.check_duplicate(paper)
        if not result.is_duplicate:
            self.add_paper(paper)
        return result

    def clear(self) -> None:
        """Clear all seen papers."""
        self._seen_dois.clear()
        self._seen_openalex_ids.clear()
        self._seen_acl_ids.clear()
        self._seen_title_years.clear()

    @property
    def stats(self) -> dict[str, int]:
        """Get statistics about seen papers.

        Returns:
            Dictionary with counts of seen identifiers.
        """
        return {
            "dois": len(self._seen_dois),
            "openalex_ids": len(self._seen_openalex_ids),
            "acl_ids": len(self._seen_acl_ids),
            "title_years": len(self._seen_title_years),
        }

    def should_prefer_new(self, existing_source: SourceType, new_source: SourceType) -> bool:
        """Check if new source should be preferred over existing.

        Uses SOURCE_PRIORITY to determine preference. Lower priority
        number means higher preference.

        Args:
            existing_source: Source type of existing paper.
            new_source: Source type of new paper.

        Returns:
            True if new source should replace existing.
        """
        existing_priority = SOURCE_PRIORITY.get(existing_source, 99)
        new_priority = SOURCE_PRIORITY.get(new_source, 99)
        return new_priority < existing_priority


def are_titles_similar(title1: str, title2: str, threshold: float = 0.9) -> bool:
    """Check if two titles are similar using simple ratio.

    Uses character-level Jaccard similarity as a simple metric.

    Args:
        title1: First title.
        title2: Second title.
        threshold: Minimum similarity ratio (0-1).

    Returns:
        True if titles are similar enough.
    """
    norm1 = Deduplicator.normalize_title(title1)
    norm2 = Deduplicator.normalize_title(title2)

    if not norm1 or not norm2:
        return False

    # Exact match after normalization
    if norm1 == norm2:
        return True

    # Character-level Jaccard similarity
    set1 = set(norm1.split())
    set2 = set(norm2.split())

    if not set1 or not set2:
        return False

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    similarity = intersection / union if union > 0 else 0

    return similarity >= threshold
