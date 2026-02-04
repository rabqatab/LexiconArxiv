"""Citation graph module for building and analyzing paper citation networks.

This module provides:
- ReverseCitationIndex: Build reverse citation lookup (who cites this paper?)
- CitationGraphBuilder: Build NetworkX graphs from Qdrant data
- GraphExporter: Export graphs to CSV, JSON, GraphML, GEXF formats
- StreamingGraphExporter: Memory-efficient streaming export for large graphs
- GraphAnalyzer: Compute PageRank, HITS, community detection

Memory considerations:
- Full graph with 150K nodes and 10M edges requires ~2-3 GB RAM
- Use StreamingGraphExporter for large graphs to avoid memory issues
- Set include_metadata=False to reduce memory by ~40%
"""

from src.core.citation_graph.reverse_index import (
    ReverseCitationIndex,
    estimate_memory_mb,
)
from src.core.citation_graph.builder import CitationGraphBuilder
from src.core.citation_graph.exporter import GraphExporter, StreamingGraphExporter
from src.core.citation_graph.analyzer import GraphAnalyzer, GraphMetrics

__all__ = [
    "ReverseCitationIndex",
    "CitationGraphBuilder",
    "GraphExporter",
    "StreamingGraphExporter",
    "GraphAnalyzer",
    "GraphMetrics",
    "estimate_memory_mb",
]
