"""Enrichment commands for LexiconArxiv CLI."""

import asyncio
import logging
import sys

import click

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


def register_commands(cli: click.Group):

    @cli.command("enrich-citations")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--delay", type=float, default=0.1, help="Delay between API calls")
    @click.option("--parallel", "-p", type=int, default=1, help="Number of concurrent requests")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers still missing data (clears checkpoint)")
    def enrich_citations(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        delay: float,
        parallel: int,
        retry_incomplete: bool,
    ) -> None:
        """Enrich papers with citation data from OpenAlex.

        Fetches referenced_works for papers that have DOI but missing citations.
        Progress is checkpointed for resumable operation.

        Examples:

          # Count papers needing enrichment
          python -m src.cli.core_collect enrich-citations --dry-run

          # Enrich all papers
          python -m src.cli.core_collect enrich-citations

          # Enrich with parallel requests (faster)
          python -m src.cli.core_collect enrich-citations --parallel 10

          # Enrich first 1000 papers
          python -m src.cli.core_collect enrich-citations --limit 1000
        """
        from src.core.enrichment.openalex import EnrichmentType, PaperEnricher

        async def run_enrichment():
            storage = QdrantStorage()
            async with PaperEnricher(
                storage=storage,
                batch_size=batch_size,
                delay=delay,
                max_concurrent=parallel,
            ) as enricher:
                if retry_incomplete:
                    enricher.clear_checkpoint(EnrichmentType.CITATIONS)
                    click.echo("Checkpoint cleared — retrying papers still missing citations.")
                progress = await enricher.enrich_citations(dry_run=dry_run, limit=limit)

                click.echo(f"\nCitation Enrichment Results:")
                click.echo(f"  Processed: {progress.processed}")
                click.echo(f"  Enriched:  {progress.enriched}")
                click.echo(f"  Not found: {progress.not_found}")
                click.echo(f"  Errors:    {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total papers to enrich: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_enrichment())

    @cli.command("enrich-abstracts")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--delay", type=float, default=0.1, help="Delay between API calls")
    @click.option("--parallel", "-p", type=int, default=1, help="Number of concurrent requests")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers still missing data (clears checkpoint)")
    def enrich_abstracts(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        delay: float,
        parallel: int,
        retry_incomplete: bool,
    ) -> None:
        """Enrich papers with abstracts from OpenAlex.

        Fetches abstracts for papers that have DOI but missing abstracts.
        Progress is checkpointed for resumable operation.

        Examples:

          # Count papers needing abstract enrichment
          python -m src.cli.core_collect enrich-abstracts --dry-run

          # Enrich all papers
          python -m src.cli.core_collect enrich-abstracts

          # Enrich with parallel requests (faster)
          python -m src.cli.core_collect enrich-abstracts --parallel 10

          # Enrich first 100 papers
          python -m src.cli.core_collect enrich-abstracts --limit 100
        """
        from src.core.enrichment.openalex import EnrichmentType, PaperEnricher

        async def run_enrichment():
            storage = QdrantStorage()
            async with PaperEnricher(
                storage=storage,
                batch_size=batch_size,
                delay=delay,
                max_concurrent=parallel,
            ) as enricher:
                if retry_incomplete:
                    enricher.clear_checkpoint(EnrichmentType.ABSTRACTS)
                    click.echo("Checkpoint cleared — retrying papers still missing abstracts.")
                progress = await enricher.enrich_abstracts(dry_run=dry_run, limit=limit)

                click.echo(f"\nAbstract Enrichment Results:")
                click.echo(f"  Processed: {progress.processed}")
                click.echo(f"  Enriched:  {progress.enriched}")
                click.echo(f"  Not found: {progress.not_found}")
                click.echo(f"  Errors:    {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total papers to enrich: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_enrichment())

    @cli.command("enrich-citations-by-title")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--delay", type=float, default=0.1, help="Delay between API calls")
    @click.option("--parallel", "-p", type=int, default=None, help="Concurrent requests (auto: 3 for API key, 1 for email)")
    @click.option("--venue", "-v", multiple=True, help="Filter by venue (can repeat)")
    @click.option("--min-refs", type=int, default=1, help="Minimum refs required for match")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers still missing data (clears checkpoint)")
    def enrich_citations_by_title(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        delay: float,
        parallel: int | None,
        venue: tuple[str, ...],
        min_refs: int,
        retry_incomplete: bool,
    ) -> None:
        """Enrich papers WITHOUT DOIs by searching OpenAlex by title.

        This is useful for OpenReview papers (NeurIPS, ICML, ICLR) that
        don't have DOIs but may have arXiv versions indexed in OpenAlex.

        The search only returns matches that have at least --min-refs references.

        Examples:

          # Count papers needing title-based enrichment
          python -m src.cli.core_collect enrich-citations-by-title --dry-run

          # Enrich all papers without DOIs
          python -m src.cli.core_collect enrich-citations-by-title

          # Enrich only NeurIPS papers
          python -m src.cli.core_collect enrich-citations-by-title -v "NeurIPS 2024 poster"

          # Enrich with parallel requests
          python -m src.cli.core_collect enrich-citations-by-title --parallel 5

          # Only accept matches with 5+ references
          python -m src.cli.core_collect enrich-citations-by-title --min-refs 5
        """
        from src.core.enrichment.openalex import EnrichmentType, PaperEnricher

        venues_list = list(venue) if venue else None

        async def run_enrichment():
            storage = QdrantStorage()
            async with PaperEnricher(
                storage=storage,
                batch_size=batch_size,
                delay=delay,
                max_concurrent=parallel,
            ) as enricher:
                if retry_incomplete:
                    enricher.clear_checkpoint(EnrichmentType.TITLE_CITATIONS)
                    click.echo("Checkpoint cleared — retrying papers still missing citations.")
                progress = await enricher.enrich_citations_by_title(
                    dry_run=dry_run,
                    limit=limit,
                    venues=venues_list,
                    min_refs=min_refs,
                )

                click.echo(f"\nTitle-Based Citation Enrichment Results:")
                click.echo(f"  Processed: {progress.processed}")
                click.echo(f"  Enriched:  {progress.enriched}")
                click.echo(f"  Not found: {progress.not_found}")
                click.echo(f"  Errors:    {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total papers to enrich: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_enrichment())

    @cli.command("clear-enrichment-checkpoint")
    @click.option("--type", "enrichment_type", type=click.Choice(["citations", "abstracts", "title_citations", "all"]),
                  default="all", help="Type of checkpoint to clear")
    def clear_enrichment_checkpoint(enrichment_type: str) -> None:
        """Clear enrichment checkpoint for fresh start.

        Examples:

          # Clear all checkpoints
          python -m src.cli.core_collect clear-enrichment-checkpoint

          # Clear only citation checkpoint
          python -m src.cli.core_collect clear-enrichment-checkpoint --type citations

          # Clear only abstract checkpoint
          python -m src.cli.core_collect clear-enrichment-checkpoint --type abstracts

          # Clear only title-based citation checkpoint
          python -m src.cli.core_collect clear-enrichment-checkpoint --type title_citations
        """
        from src.core.enrichment.openalex import PaperEnricher, EnrichmentType

        enricher = PaperEnricher()

        if enrichment_type in ("citations", "all"):
            enricher.clear_checkpoint(EnrichmentType.CITATIONS)
            click.echo("Citation enrichment checkpoint cleared.")

        if enrichment_type in ("abstracts", "all"):
            enricher.clear_checkpoint(EnrichmentType.ABSTRACTS)
            click.echo("Abstract enrichment checkpoint cleared.")

        if enrichment_type in ("title_citations", "all"):
            enricher.clear_checkpoint(EnrichmentType.TITLE_CITATIONS)
            click.echo("Title-based citation enrichment checkpoint cleared.")

    @cli.command("enrich-s2")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=50, help="Batch size")
    @click.option("--delay", type=float, default=None, help="Delay between API calls (auto: 1.1s with key, 3s without)")
    @click.option("--parallel", "-p", type=int, default=None, help="Concurrent requests (auto: 1 with key, 1 without)")
    @click.option("--by-title", is_flag=True, help="Search by title instead of DOI")
    @click.option("--venue", "-v", multiple=True, help="Filter by venue (for title search)")
    @click.option("--min-refs", type=int, default=1, help="Min refs required (for title search)")
    def enrich_s2(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        delay: float | None,
        parallel: int | None,
        by_title: bool,
        venue: tuple[str, ...],
        min_refs: int,
    ) -> None:
        """Enrich citations using Semantic Scholar API.

        S2 often has better coverage for ML/AI papers than OpenAlex.
        Use this as a fallback when OpenAlex enrichment fails.

        API Key (optional but recommended):
          Set S2_API_KEY env var for ~3x faster processing.
          Get a free key at: https://www.semanticscholar.org/product/api#api-key

        Rate Limits (auto-adjusted based on API key):
          Without key: ~20 req/min (conservative)
          With key: ~55 req/min (1 req/sec cumulative limit)

        Examples:

          # Enrich papers with DOIs (fallback after OpenAlex)
          python -m src.cli.core_collect enrich-s2

          # With API key for faster processing
          S2_API_KEY=your_key python -m src.cli.core_collect enrich-s2

          # Enrich papers without DOIs by title search
          python -m src.cli.core_collect enrich-s2 --by-title

          # Target specific venues
          python -m src.cli.core_collect enrich-s2 --by-title -v "NeurIPS 2024 poster"
        """
        from src.core.enrichment.semantic_scholar import SemanticScholarEnricher

        venues_list = list(venue) if venue else None

        async def run_enrichment():
            storage = QdrantStorage()
            async with SemanticScholarEnricher(
                storage=storage,
                batch_size=batch_size,
                delay=delay,
                max_concurrent=parallel,
            ) as enricher:
                if by_title:
                    progress = await enricher.enrich_by_title(
                        dry_run=dry_run,
                        limit=limit,
                        venues=venues_list,
                        min_refs=min_refs,
                    )
                else:
                    progress = await enricher.enrich_by_doi(
                        dry_run=dry_run,
                        limit=limit,
                    )

                click.echo(f"\nSemantic Scholar Enrichment Results:")
                click.echo(f"  Processed: {progress.processed}")
                click.echo(f"  Enriched:  {progress.enriched}")
                click.echo(f"  Not found: {progress.not_found}")
                if hasattr(progress, 'no_refs'):
                    click.echo(f"  No refs:   {progress.no_refs}")
                click.echo(f"  Errors:    {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total papers to enrich: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_enrichment())

    @cli.command("clear-s2-checkpoint")
    @click.option("--type", "checkpoint_type", type=click.Choice(["doi", "title", "all"]),
                  default="all", help="Type of S2 checkpoint to clear")
    def clear_s2_checkpoint(checkpoint_type: str) -> None:
        """Clear Semantic Scholar enrichment checkpoint.

        Examples:

          # Clear all S2 checkpoints
          python -m src.cli.core_collect clear-s2-checkpoint

          # Clear only DOI-based checkpoint
          python -m src.cli.core_collect clear-s2-checkpoint --type doi

          # Clear only title-based checkpoint
          python -m src.cli.core_collect clear-s2-checkpoint --type title
        """
        from src.core.enrichment.semantic_scholar import SemanticScholarEnricher

        enricher = SemanticScholarEnricher()

        if checkpoint_type in ("doi", "all"):
            enricher.clear_checkpoint(by_title=False)
            click.echo("Semantic Scholar DOI checkpoint cleared.")

        if checkpoint_type in ("title", "all"):
            enricher.clear_checkpoint(by_title=True)
            click.echo("Semantic Scholar title checkpoint cleared.")

    @cli.command("enrich-crossref")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--delay", type=float, default=0.1, help="Delay between API calls (default: 0.1s = 10 req/sec)")
    @click.option("--parallel", "-p", type=int, default=5, help="Concurrent requests (default: 5)")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers still missing data (clears checkpoint)")
    def enrich_crossref(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        delay: float,
        parallel: int,
        retry_incomplete: bool,
    ) -> None:
        """Enrich papers with references from CrossRef.

        CrossRef has excellent coverage for ACM and Springer papers (97% success rate)
        where other APIs like Semantic Scholar fail.

        Rate limits are generous: 50 req/sec, no API key needed.

        For polite pool access (better reliability), set CROSSREF_EMAIL env var.

        Examples:

          # Count papers that can be enriched
          python -m src.cli.core_collect enrich-crossref --dry-run

          # Enrich all papers with DOIs
          python -m src.cli.core_collect enrich-crossref

          # Limit to 500 papers
          python -m src.cli.core_collect enrich-crossref --limit 500

          # Adjust concurrency
          python -m src.cli.core_collect enrich-crossref --parallel 20
        """
        import asyncio
        from src.core.enrichment.crossref import CrossRefEnricher

        async def run():
            async with CrossRefEnricher(
                batch_size=batch_size,
                delay=delay,
                max_concurrent=parallel,
            ) as enricher:
                if retry_incomplete:
                    enricher.clear_checkpoint()
                    click.echo("Checkpoint cleared — retrying papers still missing CrossRef data.")
                progress = await enricher.enrich_by_doi(
                    dry_run=dry_run,
                    limit=limit,
                )
                return progress

        progress = asyncio.run(run())

        click.echo()
        click.echo("CrossRef Enrichment Results:")
        if dry_run:
            click.echo(f"  Papers to process: {progress.total_to_process}")
        else:
            click.echo(f"  Processed:    {progress.processed}")
            click.echo(f"  Enriched:     {progress.enriched}")
            click.echo(f"  Not found:    {progress.not_found}")
            click.echo(f"  No refs:      {progress.no_refs}")
            click.echo(f"  Errors:       {progress.errors}")

    @cli.command("clear-crossref-checkpoint")
    def clear_crossref_checkpoint() -> None:
        """Clear CrossRef enrichment checkpoint.

        Use this to restart enrichment from the beginning.

        Examples:

          python -m src.cli.core_collect clear-crossref-checkpoint
        """
        from src.core.enrichment.crossref import CrossRefEnricher

        enricher = CrossRefEnricher()
        enricher.clear_checkpoint()
        click.echo("CrossRef enrichment checkpoint cleared.")

    @cli.command("extract-pdf-refs")
    @click.option("--dry-run", is_flag=True, help="Count papers without extracting")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=50, help="Papers per batch")
    @click.option("--parallel", "-p", type=int, default=20, help="Concurrent extractions")
    @click.option("--venue", "-v", multiple=True, help="Filter by venue")
    @click.option("--grobid-url", type=str, help="GROBID server URL (default: http://localhost:8070)")
    def extract_pdf_refs(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        parallel: int,
        venue: tuple[str, ...],
        grobid_url: str | None,
    ) -> None:
        """Extract references from PDFs using GROBID.

        This is a last-resort method when API-based enrichment fails.
        It downloads PDFs and extracts reference sections using GROBID.

        GROBID must be running:
          docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

        Examples:

          # Count papers with PDF URLs
          python -m src.cli.core_collect extract-pdf-refs --dry-run

          # Extract from all PDFs
          python -m src.cli.core_collect extract-pdf-refs

          # Target specific venues
          python -m src.cli.core_collect extract-pdf-refs -v "NeurIPS 2024 poster"
        """
        from src.core.enrichment.pdf import PDFReferenceExtractor

        venues_list = list(venue) if venue else None

        async def run_extraction():
            storage = QdrantStorage()
            async with PDFReferenceExtractor(
                storage=storage,
                grobid_url=grobid_url,
                batch_size=batch_size,
                max_concurrent=parallel,
            ) as extractor:
                progress = await extractor.enrich_from_pdfs(
                    dry_run=dry_run,
                    limit=limit,
                    venues=venues_list,
                )

                click.echo(f"\nPDF Reference Extraction Results:")
                click.echo(f"  Processed:       {progress.processed}")
                click.echo(f"  Extracted:       {progress.extracted}")
                click.echo(f"  Download failed: {progress.download_failed}")
                click.echo(f"  Parse failed:    {progress.parse_failed}")
                click.echo(f"  No refs found:   {progress.no_refs}")
                click.echo(f"  Errors:          {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total papers to process: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_extraction())

    @cli.command("clear-pdf-checkpoint")
    def clear_pdf_checkpoint() -> None:
        """Clear PDF extraction checkpoint."""
        from src.core.enrichment.pdf import PDFReferenceExtractor

        extractor = PDFReferenceExtractor()
        extractor.clear_checkpoint()
        click.echo("PDF extraction checkpoint cleared.")

    @cli.command("enrich-stubs")
    @click.option("--limit", "-n", type=int, default=100, help="Max stubs to enrich")
    @click.option("--type", "identifier_type", type=click.Choice(["doi", "arxiv", "openalex"]),
                  help="Only enrich stubs of this type")
    @click.option("--min-citations", type=int, default=1, help="Only enrich stubs with >= N citations")
    @click.option("--dry-run", is_flag=True, help="Count stubs without enriching")
    @click.option("--parallel", "-p", type=int, default=5, help="Concurrent API requests")
    def enrich_stubs(
        limit: int,
        identifier_type: str | None,
        min_citations: int,
        dry_run: bool,
        parallel: int,
    ) -> None:
        """Enrich stub papers with metadata from external APIs.

        Fetches title, authors, year, venue, abstract for stub papers using
        OpenAlex and CrossRef APIs. Prioritizes most-cited stubs.

        Examples:

          # Enrich top 100 most-cited stubs
          python -m src.cli.core_collect enrich-stubs

          # Enrich top 1000 DOI stubs
          python -m src.cli.core_collect enrich-stubs --limit 1000 --type doi

          # Only enrich stubs cited 5+ times
          python -m src.cli.core_collect enrich-stubs --min-citations 5

          # Dry run to see what would be enriched
          python -m src.cli.core_collect enrich-stubs --dry-run
        """
        from src.core.enrichment import StubEnricher

        async def run_enrichment():
            storage = QdrantStorage()
            async with StubEnricher(
                storage=storage,
                max_concurrent=parallel,
            ) as enricher:
                progress = await enricher.enrich_stubs(
                    limit=limit,
                    identifier_type=identifier_type,
                    min_citations=min_citations,
                    dry_run=dry_run,
                )

                click.echo(f"\nStub Enrichment Results:")
                click.echo(f"  Processed:    {progress.processed}")
                click.echo(f"  Enriched:     {progress.enriched}")
                click.echo(f"  Merged:       {progress.merged}")
                click.echo(f"  Not found:    {progress.not_found}")
                click.echo(f"  Errors:       {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total stubs to enrich: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_enrichment())
