"""Venue name normalization for search filters.

Maps short canonical venue names to search patterns so that a user
filtering by e.g. ``"ICLR"`` will match all Qdrant venue strings like
``"ICLR 2025 Poster"``, ``"ICLR 2024 poster"``, and
``"International Conference on Learning Representations"``.
"""

from __future__ import annotations

# Each key is a lowercased short name.  The values are substrings that
# should be fed to ``MatchText`` as alternatives (OR).  Keep patterns
# lowercase — the caller lowercases user input before lookup.
VENUE_ALIASES: dict[str, list[str]] = {
    "neurips": ["neurips", "neural information processing systems", "nips"],
    "icml": ["icml", "international conference on machine learning"],
    "iclr": ["iclr", "international conference on learning representations"],
    "aaai": ["aaai"],
    "ijcai": ["ijcai", "international joint conference on artificial intelligence"],
    "acl": ["acl", "association for computational linguistics"],
    "emnlp": ["emnlp", "empirical methods in natural language processing"],
    "naacl": ["naacl", "north american chapter"],
    "coling": ["coling", "computational linguistics"],
    "eacl": ["eacl", "european chapter"],
    "kdd": ["kdd", "knowledge discovery and data mining"],
    "www": ["www", "web conference"],
    "sigir": ["sigir"],
    "wsdm": ["wsdm"],
    "cikm": ["cikm"],
    "icdm": ["icdm"],
    "ecir": ["ecir"],
    "recsys": ["recsys", "recommender systems"],
    "jmlr": ["jmlr", "journal of machine learning research"],
    "tacl": ["tacl", "transactions of the association for computational linguistics"],
    "tois": ["tois", "acm transactions on information systems"],
    "findings": ["findings"],
    "conll": ["conll", "computational natural language learning"],
    "lrec": ["lrec", "language resources and evaluation"],
    "cvpr": ["cvpr", "computer vision and pattern recognition"],
    "iccv": ["iccv", "international conference on computer vision"],
    "eccv": ["eccv", "european conference on computer vision"],
}


def expand_venue_names(venues: list[str]) -> list[str]:
    """Expand a list of user-provided venue names into MatchText patterns.

    For each venue string the user provides:
    * If it matches a known alias key (case-insensitive), return all
      associated patterns so that ``MatchText`` will match every variant
      stored in Qdrant.
    * Otherwise, return the original string as-is (it will be used
      directly as a ``MatchText`` pattern for substring matching).

    Returns:
        De-duplicated list of patterns suitable for ``MatchText`` queries.
    """
    patterns: list[str] = []
    for v in venues:
        key = v.lower().strip()
        if key in VENUE_ALIASES:
            patterns.extend(VENUE_ALIASES[key])
        else:
            # Pass through as-is — MatchText will do substring matching
            patterns.append(v)
    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result
