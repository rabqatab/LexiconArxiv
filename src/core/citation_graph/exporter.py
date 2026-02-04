"""Graph export functionality for citation graphs.

Supports CSV, JSON, GraphML, and GEXF formats.
"""

import json
import logging
from pathlib import Path
from typing import Any

import networkx as nx

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
