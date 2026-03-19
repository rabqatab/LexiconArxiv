"""CLI for Core Corpus collection.

Provides commands for collecting papers from Tier 0/1 venues,
checking status, and discovering Source IDs.

Supports multiple sources: OpenAlex, ACL Anthology, and DBLP.
"""

import click

from src.cli._logging import root_logger, console_handler, file_handler, logger
from src.cli.commands import analytics, collection, crawlers, embedding, enrichment, resolution, graph, quality, keywords, labeling


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """Core Corpus collection CLI for LexiconArxiv."""
    if verbose:
        import logging
        root_logger.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)
        file_handler.setLevel(logging.DEBUG)


# Register all command modules
analytics.register_commands(cli)
collection.register_commands(cli)
crawlers.register_commands(cli)
embedding.register_commands(cli)
enrichment.register_commands(cli)
resolution.register_commands(cli)
graph.register_commands(cli)
quality.register_commands(cli)
keywords.register_commands(cli)
labeling.register_commands(cli)


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
