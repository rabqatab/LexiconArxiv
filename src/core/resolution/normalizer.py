"""Identifier normalization for reference resolution.

Provides classification and normalization of various paper identifiers:
- DOI (Digital Object Identifier)
- arXiv IDs
- OpenAlex work IDs
- Title-based fallbacks
"""

import re
from dataclasses import dataclass
from enum import Enum


class IdentifierType(Enum):
    """Types of paper identifiers."""

    DOI = "DOI"
    ARXIV = "arXiv"
    OPENALEX = "W"  # OpenAlex work IDs start with W
    TITLE = "TITLE"
    UNKNOWN = "UNKNOWN"


@dataclass
class NormalizedIdentifier:
    """A normalized identifier with its type."""

    type: IdentifierType
    value: str
    original: str

    @property
    def prefixed(self) -> str:
        """Return identifier with type prefix (e.g., 'DOI:10.xxx').

        Note: OpenAlex IDs are returned as-is (e.g., 'W2741809807') since
        the 'W' prefix is already part of the identifier.
        """
        if self.type == IdentifierType.UNKNOWN:
            return self.original
        # OpenAlex IDs already have W prefix, don't double it
        if self.type == IdentifierType.OPENALEX:
            return self.value
        return f"{self.type.value}:{self.value}"


class IdentifierNormalizer:
    """Normalizes and classifies paper identifiers.

    Handles common issues:
    - 'arXiv:arXiv:2303.08774' -> 'arXiv:2303.08774'
    - DOI case normalization
    - OpenAlex URL stripping
    """

    # arXiv ID patterns
    # Old format: hep-th/9901001
    # New format: 2303.08774 or 2303.08774v1
    ARXIV_PATTERN = re.compile(
        r"^(?:arXiv:)*(?:arXiv:)*"  # Optional duplicate arXiv: prefixes
        r"("
        r"(?:[a-z-]+/\d{7})"  # Old format: hep-th/9901001
        r"|"
        r"(?:\d{4}\.\d{4,5}(?:v\d+)?)"  # New format: 2303.08774 or 2303.08774v1
        r")$",
        re.IGNORECASE,
    )

    # DOI pattern - more permissive
    DOI_PATTERN = re.compile(
        r"^(?:DOI:)?"  # Optional DOI: prefix
        r"(?:https?://(?:dx\.)?doi\.org/)?"  # Optional URL prefix
        r"(10\.\d{4,}/[^\s]+)$",  # DOI starting with 10.
        re.IGNORECASE,
    )

    # OpenAlex work ID pattern
    OPENALEX_PATTERN = re.compile(
        r"^(?:https?://openalex\.org/)?"  # Optional URL prefix
        r"(W\d+)$",  # OpenAlex work ID
        re.IGNORECASE,
    )

    # Title pattern (starts with TITLE:)
    TITLE_PATTERN = re.compile(r"^TITLE:(.+)$", re.IGNORECASE)

    @classmethod
    def normalize(cls, identifier: str) -> NormalizedIdentifier:
        """Normalize and classify an identifier.

        Args:
            identifier: Raw identifier string (e.g., 'arXiv:arXiv:2303.08774', 'DOI:10.xxx').

        Returns:
            NormalizedIdentifier with type and cleaned value.

        Examples:
            >>> IdentifierNormalizer.normalize('arXiv:arXiv:2303.08774')
            NormalizedIdentifier(type=ARXIV, value='2303.08774', original='arXiv:arXiv:2303.08774')

            >>> IdentifierNormalizer.normalize('DOI:10.18653/V1/2020.ACL-MAIN.1')
            NormalizedIdentifier(type=DOI, value='10.18653/v1/2020.acl-main.1', original='...')

            >>> IdentifierNormalizer.normalize('W2741809807')
            NormalizedIdentifier(type=OPENALEX, value='W2741809807', original='W2741809807')
        """
        if not identifier:
            return NormalizedIdentifier(
                type=IdentifierType.UNKNOWN, value="", original=""
            )

        original = identifier.strip()

        # Check for TITLE first (explicit prefix)
        title_match = cls.TITLE_PATTERN.match(original)
        if title_match:
            return NormalizedIdentifier(
                type=IdentifierType.TITLE,
                value=title_match.group(1).strip(),
                original=original,
            )

        # Check for DOI
        doi_match = cls.DOI_PATTERN.match(original)
        if doi_match:
            # Normalize DOI to lowercase
            doi_value = doi_match.group(1).lower()
            return NormalizedIdentifier(
                type=IdentifierType.DOI, value=doi_value, original=original
            )

        # Check for arXiv ID (handle duplicate prefix)
        arxiv_match = cls.ARXIV_PATTERN.match(original)
        if arxiv_match:
            arxiv_value = arxiv_match.group(1).lower()
            return NormalizedIdentifier(
                type=IdentifierType.ARXIV, value=arxiv_value, original=original
            )

        # Check for arXiv with prefix but not matching exact pattern
        if original.lower().startswith("arxiv:"):
            # Strip all arXiv: prefixes and try again
            cleaned = re.sub(r"^(?:arxiv:)+", "", original, flags=re.IGNORECASE)
            arxiv_match = cls.ARXIV_PATTERN.match(cleaned)
            if arxiv_match:
                arxiv_value = arxiv_match.group(1).lower()
                return NormalizedIdentifier(
                    type=IdentifierType.ARXIV, value=arxiv_value, original=original
                )
            # Even if pattern doesn't match, treat as arXiv if prefixed
            return NormalizedIdentifier(
                type=IdentifierType.ARXIV, value=cleaned.lower(), original=original
            )

        # Check for OpenAlex ID
        openalex_match = cls.OPENALEX_PATTERN.match(original)
        if openalex_match:
            return NormalizedIdentifier(
                type=IdentifierType.OPENALEX,
                value=openalex_match.group(1).upper(),  # Normalize to uppercase W
                original=original,
            )

        # Unknown identifier type
        return NormalizedIdentifier(
            type=IdentifierType.UNKNOWN, value=original, original=original
        )

    @classmethod
    def normalize_list(cls, identifiers: list[str]) -> list[NormalizedIdentifier]:
        """Normalize a list of identifiers.

        Args:
            identifiers: List of raw identifier strings.

        Returns:
            List of NormalizedIdentifier objects.
        """
        return [cls.normalize(id_str) for id_str in identifiers]

    @classmethod
    def classify(cls, identifier: str) -> IdentifierType:
        """Classify an identifier without full normalization.

        Args:
            identifier: Raw identifier string.

        Returns:
            IdentifierType enum value.
        """
        return cls.normalize(identifier).type

    @classmethod
    def extract_arxiv_id(cls, identifier: str) -> str | None:
        """Extract arXiv ID if present.

        Args:
            identifier: Raw identifier string.

        Returns:
            Normalized arXiv ID or None if not an arXiv identifier.
        """
        normalized = cls.normalize(identifier)
        if normalized.type == IdentifierType.ARXIV:
            return normalized.value
        return None

    @classmethod
    def extract_doi(cls, identifier: str) -> str | None:
        """Extract DOI if present.

        Args:
            identifier: Raw identifier string.

        Returns:
            Normalized DOI or None if not a DOI identifier.
        """
        normalized = cls.normalize(identifier)
        if normalized.type == IdentifierType.DOI:
            return normalized.value
        return None

    @classmethod
    def is_doi(cls, identifier: str) -> bool:
        """Check if identifier is a DOI."""
        return cls.classify(identifier) == IdentifierType.DOI

    @classmethod
    def is_arxiv(cls, identifier: str) -> bool:
        """Check if identifier is an arXiv ID."""
        return cls.classify(identifier) == IdentifierType.ARXIV

    @classmethod
    def is_title(cls, identifier: str) -> bool:
        """Check if identifier is a title-based reference."""
        return cls.classify(identifier) == IdentifierType.TITLE

    @classmethod
    def count_by_type(
        cls, identifiers: list[str]
    ) -> dict[IdentifierType, int]:
        """Count identifiers by type.

        Args:
            identifiers: List of raw identifier strings.

        Returns:
            Dictionary mapping IdentifierType to count.
        """
        counts: dict[IdentifierType, int] = {t: 0 for t in IdentifierType}
        for id_str in identifiers:
            id_type = cls.classify(id_str)
            counts[id_type] += 1
        return counts
