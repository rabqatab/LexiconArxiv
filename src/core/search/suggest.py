"""Keyword autocomplete using a prefix trie."""

import logging
from collections import defaultdict

from qdrant_client import models

from src.core.storage.base import QdrantStorage

logger = logging.getLogger(__name__)


class KeywordSuggestor:
    """In-memory prefix trie for keyword autocomplete."""

    def __init__(self):
        self._trie: dict = {}
        self._keywords: dict[str, int] = {}  # keyword -> count
        self._built = False

    @property
    def is_built(self) -> bool:
        return self._built

    def build(self, storage: QdrantStorage, batch_size: int = 1000) -> int:
        """Scan all papers and build prefix trie from keywords."""
        logger.info("Building keyword suggestion trie...")
        keyword_counts: dict[str, int] = defaultdict(int)
        offset = None

        while True:
            results, next_offset = storage.client.scroll(
                collection_name=storage.collection_name,
                scroll_filter=models.Filter(must_not=[
                    models.FieldCondition(key="is_stub", match=models.MatchValue(value=True)),
                    models.IsEmptyCondition(is_empty=models.PayloadField(key="keywords")),
                ]),
                limit=batch_size,
                offset=offset,
                with_payload=["keywords"],
            )
            if not results:
                break
            for point in results:
                for kw in (point.payload or {}).get("keywords", []):
                    if kw and isinstance(kw, str):
                        keyword_counts[kw.lower()] += 1
            if next_offset is None:
                break
            offset = next_offset

        # Build trie
        self._keywords = dict(keyword_counts)
        for keyword in keyword_counts:
            node = self._trie
            for char in keyword:
                node = node.setdefault(char, {})
            node["_end"] = True

        self._built = True
        logger.info(f"Keyword trie built: {len(self._keywords):,} unique keywords")
        return len(self._keywords)

    def suggest(self, prefix: str, limit: int = 10) -> list[str]:
        """Return keywords matching the prefix, sorted by frequency."""
        if not self._built:
            return []
        prefix = prefix.lower().strip()
        if not prefix:
            return []

        # Walk trie to prefix node
        node = self._trie
        for char in prefix:
            if char not in node:
                return []
            node = node[char]

        # Collect all keywords under this prefix
        matches: list[str] = []
        self._collect(node, prefix, matches)

        # Sort by count descending, return top N
        matches.sort(key=lambda kw: self._keywords.get(kw, 0), reverse=True)
        return matches[:limit]

    def _collect(self, node: dict, current: str, results: list):
        """DFS to collect all complete keywords under a trie node."""
        if "_end" in node:
            results.append(current)
        for char, child in node.items():
            if char != "_end":
                self._collect(child, current + char, results)
