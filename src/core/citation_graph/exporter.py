"""Graph export functionality for citation graphs.

Supports CSV, JSON, GraphML, and GEXF formats.
Includes streaming export for large graphs that don't fit in memory.
"""

import json
import logging
from pathlib import Path
from typing import Any, Iterator

import networkx as nx

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


class GraphExporter:
    """Export citation graphs to various formats.

    Supports:
    - CSV edge list and node list
    - JSON (node-link format)
    - GraphML (for Gephi, yEd)
    - GEXF (for Gephi)
    """

    def __init__(self, graph: nx.DiGraph):
        """Initialize the exporter.

        Args:
            graph: NetworkX DiGraph to export.
        """
        self.graph = graph

    def to_csv_edgelist(self, output_path: Path | str) -> int:
        """Export edges to a CSV file.

        Format: source,target
        Where source is the citing paper and target is the cited paper.

        Args:
            output_path: Path to output CSV file.

        Returns:
            Number of edges written.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            f.write("source,target\n")
            for source, target in self.graph.edges():
                f.write(f"{source},{target}\n")

        edge_count = self.graph.number_of_edges()
        logger.info(f"Exported {edge_count} edges to {output_path}")
        return edge_count

    def to_csv_nodes(self, output_path: Path | str) -> int:
        """Export nodes to a CSV file with attributes.

        Format: id,title,venue,year,citation_count,doi

        Args:
            output_path: Path to output CSV file.

        Returns:
            Number of nodes written.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine columns from first node with data
        columns = ["id"]
        sample_attrs = None
        for node in self.graph.nodes():
            sample_attrs = self.graph.nodes[node]
            if sample_attrs:
                columns.extend([k for k in sample_attrs.keys() if k != "id"])
                break

        with open(output_path, "w") as f:
            f.write(",".join(columns) + "\n")

            for node in self.graph.nodes():
                attrs = self.graph.nodes[node]
                row = [str(node)]

                for col in columns[1:]:
                    val = attrs.get(col, "")
                    # Handle lists (e.g., authors)
                    if isinstance(val, list):
                        val = "|".join(str(v) for v in val)
                    # Escape commas and quotes in strings
                    if isinstance(val, str) and ("," in val or '"' in val):
                        val = '"' + val.replace('"', '""') + '"'
                    row.append(str(val) if val is not None else "")

                f.write(",".join(row) + "\n")

        node_count = self.graph.number_of_nodes()
        logger.info(f"Exported {node_count} nodes to {output_path}")
        return node_count

    def to_json(self, output_path: Path | str) -> dict[str, Any]:
        """Export graph to JSON format (node-link).

        Uses NetworkX's node-link format which is suitable for D3.js visualization.

        Args:
            output_path: Path to output JSON file.

        Returns:
            The JSON data dictionary.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert graph to node-link format
        data = nx.node_link_data(self.graph)

        # Add summary statistics
        data["stats"] = {
            "num_nodes": self.graph.number_of_nodes(),
            "num_edges": self.graph.number_of_edges(),
            "density": nx.density(self.graph),
            "is_weakly_connected": nx.is_weakly_connected(self.graph) if self.graph.number_of_nodes() > 0 else False,
        }

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"Exported graph to JSON: {output_path}")
        return data

    def to_graphml(self, output_path: Path | str) -> None:
        """Export graph to GraphML format.

        GraphML is widely supported by graph visualization tools like Gephi and yEd.

        Args:
            output_path: Path to output GraphML file.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # GraphML doesn't handle list attributes well, so convert them
        G_copy = self.graph.copy()
        for node in G_copy.nodes():
            attrs = G_copy.nodes[node]
            for key, value in list(attrs.items()):
                if isinstance(value, list):
                    attrs[key] = "|".join(str(v) for v in value)
                elif value is None:
                    attrs[key] = ""

        nx.write_graphml(G_copy, str(output_path))
        logger.info(f"Exported graph to GraphML: {output_path}")

    def to_gexf(self, output_path: Path | str) -> None:
        """Export graph to GEXF format.

        GEXF is the native format for Gephi with rich attribute support.

        Args:
            output_path: Path to output GEXF file.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # GEXF doesn't handle list attributes well, so convert them
        G_copy = self.graph.copy()
        for node in G_copy.nodes():
            attrs = G_copy.nodes[node]
            for key, value in list(attrs.items()):
                if isinstance(value, list):
                    attrs[key] = "|".join(str(v) for v in value)
                elif value is None:
                    attrs[key] = ""

        nx.write_gexf(G_copy, str(output_path))
        logger.info(f"Exported graph to GEXF: {output_path}")

    def export(
        self,
        output_path: Path | str,
        format: str | None = None,
    ) -> None:
        """Export graph to the specified format.

        Format is inferred from file extension if not specified.

        Args:
            output_path: Path to output file.
            format: Export format (csv, json, graphml, gexf).
                   If None, inferred from file extension.
        """
        output_path = Path(output_path)

        # Infer format from extension if not specified
        if format is None:
            ext = output_path.suffix.lower()
            format_map = {
                ".csv": "csv",
                ".json": "json",
                ".graphml": "graphml",
                ".gexf": "gexf",
            }
            format = format_map.get(ext)
            if format is None:
                raise ValueError(f"Unknown file extension: {ext}. Specify format explicitly.")

        format = format.lower()

        if format == "csv":
            # Export both edges and nodes
            edges_path = output_path.with_stem(output_path.stem + "_edges")
            nodes_path = output_path.with_stem(output_path.stem + "_nodes")
            self.to_csv_edgelist(edges_path)
            self.to_csv_nodes(nodes_path)
        elif format == "json":
            self.to_json(output_path)
        elif format == "graphml":
            self.to_graphml(output_path)
        elif format == "gexf":
            self.to_gexf(output_path)
        else:
            raise ValueError(f"Unknown format: {format}. Use csv, json, graphml, or gexf.")


class StreamingGraphExporter:
    """Memory-efficient streaming graph exporter.

    Exports citation graph directly from Qdrant without loading the full
    graph into memory. Use this for large graphs (>1M edges).

    Only supports CSV format for streaming (edges and nodes exported separately).
    """

    def __init__(self, storage: QdrantStorage | None = None):
        """Initialize the streaming exporter.

        Args:
            storage: QdrantStorage instance. Creates one if not provided.
        """
        self.storage = storage or QdrantStorage()

    def stream_edges(self) -> Iterator[tuple[str, str]]:
        """Stream all citation edges from Qdrant.

        Yields:
            Tuples of (citing_paper_id, cited_paper_id).
        """
        offset = None
        total_edges = 0

        while True:
            results, offset = self.storage.client.scroll(
                collection_name=self.storage.collection_name,
                limit=1000,
                offset=offset,
                with_payload=["resolved_references"],
            )

            for point in results:
                paper_id = str(point.id)
                resolved_refs = point.payload.get("resolved_references", [])
                for cited_id in resolved_refs:
                    yield (paper_id, cited_id)
                    total_edges += 1

            if offset is None:
                break

        logger.info(f"Streamed {total_edges:,} edges")

    def stream_nodes(
        self,
        include_metadata: bool = True,
    ) -> Iterator[tuple[str, dict]]:
        """Stream all nodes (papers) from Qdrant.

        Args:
            include_metadata: Whether to include paper metadata.

        Yields:
            Tuples of (paper_id, metadata_dict).
        """
        fields = ["title", "venue", "year", "citation_count", "doi"] if include_metadata else []

        offset = None
        total_nodes = 0

        while True:
            results, offset = self.storage.client.scroll(
                collection_name=self.storage.collection_name,
                limit=1000,
                offset=offset,
                with_payload=fields if fields else False,
            )

            for point in results:
                paper_id = str(point.id)
                metadata = point.payload if include_metadata else {}
                yield (paper_id, metadata)
                total_nodes += 1

            if offset is None:
                break

        logger.info(f"Streamed {total_nodes:,} nodes")

    def export_edges_csv(self, output_path: Path | str) -> int:
        """Export edges to CSV using streaming (low memory).

        Args:
            output_path: Path to output CSV file.

        Returns:
            Number of edges written.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        edge_count = 0
        with open(output_path, "w") as f:
            f.write("source,target\n")
            for source, target in self.stream_edges():
                f.write(f"{source},{target}\n")
                edge_count += 1

                if edge_count % 100000 == 0:
                    logger.info(f"  Written {edge_count:,} edges...")

        logger.info(f"Exported {edge_count:,} edges to {output_path}")
        return edge_count

    def export_nodes_csv(
        self,
        output_path: Path | str,
        include_metadata: bool = True,
    ) -> int:
        """Export nodes to CSV using streaming (low memory).

        Args:
            output_path: Path to output CSV file.
            include_metadata: Whether to include paper metadata.

        Returns:
            Number of nodes written.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        columns = ["id"]
        if include_metadata:
            columns.extend(["title", "venue", "year", "citation_count", "doi"])

        node_count = 0
        with open(output_path, "w") as f:
            f.write(",".join(columns) + "\n")

            for paper_id, metadata in self.stream_nodes(include_metadata):
                row = [paper_id]
                if include_metadata:
                    for col in columns[1:]:
                        val = metadata.get(col, "")
                        if isinstance(val, str) and ("," in val or '"' in val):
                            val = '"' + val.replace('"', '""') + '"'
                        row.append(str(val) if val is not None else "")
                f.write(",".join(row) + "\n")
                node_count += 1

                if node_count % 50000 == 0:
                    logger.info(f"  Written {node_count:,} nodes...")

        logger.info(f"Exported {node_count:,} nodes to {output_path}")
        return node_count

    def export_csv(
        self,
        output_dir: Path | str,
        prefix: str = "citation_graph",
        include_metadata: bool = True,
    ) -> dict[str, int]:
        """Export both edges and nodes to CSV using streaming.

        Args:
            output_dir: Directory for output files.
            prefix: Filename prefix.
            include_metadata: Whether to include node metadata.

        Returns:
            Dict with edge_count and node_count.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        edges_path = output_dir / f"{prefix}_edges.csv"
        nodes_path = output_dir / f"{prefix}_nodes.csv"

        edge_count = self.export_edges_csv(edges_path)
        node_count = self.export_nodes_csv(nodes_path, include_metadata)

        return {
            "edge_count": edge_count,
            "node_count": node_count,
            "edges_file": str(edges_path),
            "nodes_file": str(nodes_path),
        }
