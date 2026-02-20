"""Enrichment commands for LexiconArxiv CLI."""

import asyncio
import logging
import sys

import click

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


def register_commands(cli: click.Group):

    @cli.command("enrich-1-refs-and-abstracts-by-doi-via-openalex")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--delay", type=float, default=0.1, help="Delay between API calls")
    @click.option("--parallel", "-p", type=int, default=1, help="Number of concurrent requests")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers still missing data (clears checkpoint)")
    def enrich_1_refs_and_abstracts_by_doi_via_openalex(
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
          python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --dry-run

          # Enrich all papers
          python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex

          # Enrich with parallel requests (faster)
          python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --parallel 10

          # Enrich first 1000 papers
          python -m src.cli.core_collect enrich-1-refs-and-abstracts-by-doi-via-openalex --limit 1000
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

    @cli.command("enrich-6-abstracts-by-doi-via-openalex")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--delay", type=float, default=0.1, help="Delay between API calls")
    @click.option("--parallel", "-p", type=int, default=1, help="Number of concurrent requests")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers still missing data (clears checkpoint)")
    def enrich_6_abstracts_by_doi_via_openalex(
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
          python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --dry-run

          # Enrich all papers
          python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex

          # Enrich with parallel requests (faster)
          python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --parallel 10

          # Enrich first 100 papers
          python -m src.cli.core_collect enrich-6-abstracts-by-doi-via-openalex --limit 100
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

    @cli.command("enrich-3-refs-and-abstracts-by-title-via-openalex")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--delay", type=float, default=0.1, help="Delay between API calls")
    @click.option("--parallel", "-p", type=int, default=None, help="Concurrent requests (auto: 3 for API key, 1 for email)")
    @click.option("--venue", "-v", multiple=True, help="Filter by venue (can repeat)")
    @click.option("--min-refs", type=int, default=1, help="Minimum refs required for match")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers still missing data (clears checkpoint)")
    def enrich_3_refs_and_abstracts_by_title_via_openalex(
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
          python -m src.cli.core_collect enrich-3-refs-and-abstracts-by-title-via-openalex --dry-run

          # Enrich all papers without DOIs
          python -m src.cli.core_collect enrich-3-refs-and-abstracts-by-title-via-openalex

          # Enrich only NeurIPS papers
          python -m src.cli.core_collect enrich-3-refs-and-abstracts-by-title-via-openalex -v "NeurIPS 2024 poster"

          # Enrich with parallel requests
          python -m src.cli.core_collect enrich-3-refs-and-abstracts-by-title-via-openalex --parallel 5

          # Only accept matches with 5+ references
          python -m src.cli.core_collect enrich-3-refs-and-abstracts-by-title-via-openalex --min-refs 5
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

    @cli.command("clear-enrich-1-checkpoint")
    def clear_enrich_1_checkpoint() -> None:
        """Clear checkpoint for enrich-1 (refs-and-abstracts-by-doi-via-openalex).

        Examples:

          python -m src.cli.core_collect clear-enrich-1-checkpoint
        """
        from src.core.enrichment.openalex import PaperEnricher, EnrichmentType

        enricher = PaperEnricher()
        enricher.clear_checkpoint(EnrichmentType.CITATIONS)
        click.echo("Enrich-1 (citation/DOI) checkpoint cleared.")

    @cli.command("clear-enrich-3-checkpoint")
    def clear_enrich_3_checkpoint() -> None:
        """Clear checkpoint for enrich-3 (refs-and-abstracts-by-title-via-openalex).

        Examples:

          python -m src.cli.core_collect clear-enrich-3-checkpoint
        """
        from src.core.enrichment.openalex import PaperEnricher, EnrichmentType

        enricher = PaperEnricher()
        enricher.clear_checkpoint(EnrichmentType.TITLE_CITATIONS)
        click.echo("Enrich-3 (citation/title) checkpoint cleared.")

    @cli.command("clear-enrich-6-checkpoint")
    def clear_enrich_6_checkpoint() -> None:
        """Clear checkpoint for enrich-6 (abstracts-by-doi-via-openalex).

        Examples:

          python -m src.cli.core_collect clear-enrich-6-checkpoint
        """
        from src.core.enrichment.openalex import PaperEnricher, EnrichmentType

        enricher = PaperEnricher()
        enricher.clear_checkpoint(EnrichmentType.ABSTRACTS)
        click.echo("Enrich-6 (abstract/DOI) checkpoint cleared.")

    @cli.command("enrich-4-refs-by-doi-via-s2")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=50, help="Batch size")
    @click.option("--delay", type=float, default=None, help="Delay between API calls (auto: 1.1s with key, 3s without)")
    @click.option("--parallel", "-p", type=int, default=None, help="Concurrent requests (auto: 1 with key, 1 without)")
    @click.option("--by-title", is_flag=True, help="Search by title instead of DOI")
    @click.option("--venue", "-v", multiple=True, help="Filter by venue (for title search)")
    @click.option("--min-refs", type=int, default=1, help="Min refs required (for title search)")
    def enrich_4_refs_by_doi_via_s2(
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
          python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2

          # With API key for faster processing
          S2_API_KEY=your_key python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2

          # Enrich papers without DOIs by title search
          python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --by-title

          # Target specific venues
          python -m src.cli.core_collect enrich-4-refs-by-doi-via-s2 --by-title -v "NeurIPS 2024 poster"
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

    @cli.command("clear-enrich-4-checkpoint")
    @click.option("--type", "checkpoint_type", type=click.Choice(["doi", "title", "all"]),
                  default="all", help="Type of S2 checkpoint to clear")
    def clear_enrich_4_checkpoint(checkpoint_type: str) -> None:
        """Clear Semantic Scholar enrichment checkpoint.

        Examples:

          # Clear all S2 checkpoints
          python -m src.cli.core_collect clear-enrich-4-checkpoint

          # Clear only DOI-based checkpoint
          python -m src.cli.core_collect clear-enrich-4-checkpoint --type doi

          # Clear only title-based checkpoint
          python -m src.cli.core_collect clear-enrich-4-checkpoint --type title
        """
        from src.core.enrichment.semantic_scholar import SemanticScholarEnricher

        enricher = SemanticScholarEnricher()

        if checkpoint_type in ("doi", "all"):
            enricher.clear_checkpoint(by_title=False)
            click.echo("Semantic Scholar DOI checkpoint cleared.")

        if checkpoint_type in ("title", "all"):
            enricher.clear_checkpoint(by_title=True)
            click.echo("Semantic Scholar title checkpoint cleared.")

    @cli.command("enrich-2-refs-by-doi-via-crossref")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--delay", type=float, default=0.1, help="Delay between API calls (default: 0.1s = 10 req/sec)")
    @click.option("--parallel", "-p", type=int, default=5, help="Concurrent requests (default: 5)")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers still missing data (clears checkpoint)")
    def enrich_2_refs_by_doi_via_crossref(
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
          python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --dry-run

          # Enrich all papers with DOIs
          python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref

          # Limit to 500 papers
          python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --limit 500

          # Adjust concurrency
          python -m src.cli.core_collect enrich-2-refs-by-doi-via-crossref --parallel 20
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

    @cli.command("clear-enrich-2-checkpoint")
    def clear_enrich_2_checkpoint() -> None:
        """Clear CrossRef enrichment checkpoint.

        Use this to restart enrichment from the beginning.

        Examples:

          python -m src.cli.core_collect clear-enrich-2-checkpoint
        """
        from src.core.enrichment.crossref import CrossRefEnricher

        enricher = CrossRefEnricher()
        enricher.clear_checkpoint()
        click.echo("CrossRef enrichment checkpoint cleared.")

    @cli.command("enrich-5-refs-by-pdf-via-grobid")
    @click.option("--dry-run", is_flag=True, help="Count papers without extracting")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=50, help="Papers per batch")
    @click.option("--parallel", "-p", type=int, default=20, help="Concurrent extractions")
    @click.option("--venue", "-v", multiple=True, help="Filter by venue")
    @click.option("--grobid-url", type=str, help="GROBID server URL (default: http://localhost:8070)")
    def enrich_5_refs_by_pdf_via_grobid(
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
          python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid --dry-run

          # Extract from all PDFs
          python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid

          # Target specific venues
          python -m src.cli.core_collect enrich-5-refs-by-pdf-via-grobid -v "NeurIPS 2024 poster"
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

    @cli.command("enrich-7-abstracts-by-pdf-via-grobid")
    @click.option("--dry-run", is_flag=True, help="Count papers without extracting")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=50, help="Papers per batch")
    @click.option("--parallel", "-p", type=int, default=20, help="Concurrent extractions")
    @click.option("--venue", "-v", multiple=True, help="Filter by venue")
    @click.option("--grobid-url", type=str, help="GROBID server URL (default: http://localhost:8070)")
    def enrich_7_abstracts_by_pdf_via_grobid(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        parallel: int,
        venue: tuple[str, ...],
        grobid_url: str | None,
    ) -> None:
        """Extract abstracts from PDFs using GROBID.

        Fallback for papers still missing abstracts after OpenAlex enrichment.
        Downloads PDFs and extracts abstracts via GROBID processHeaderDocument.
        Only processes papers with direct PDF URLs (ending in .pdf).

        GROBID must be running:
          docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

        Examples:

          # Count papers needing PDF abstract extraction
          python -m src.cli.core_collect enrich-7-abstracts-by-pdf-via-grobid --dry-run

          # Extract abstracts from PDFs
          python -m src.cli.core_collect enrich-7-abstracts-by-pdf-via-grobid

          # Target specific venues
          python -m src.cli.core_collect enrich-7-abstracts-by-pdf-via-grobid -v "PACLIC"
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
                progress = await extractor.enrich_abstracts_from_pdfs(
                    dry_run=dry_run,
                    limit=limit,
                    venues=venues_list,
                )

                click.echo(f"\nPDF Abstract Extraction Results:")
                click.echo(f"  Processed:       {progress.processed}")
                click.echo(f"  Extracted:       {progress.extracted}")
                click.echo(f"  Download failed: {progress.download_failed}")
                click.echo(f"  Parse failed:    {progress.parse_failed}")
                click.echo(f"  No abstract:     {progress.no_abstract}")
                click.echo(f"  Errors:          {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total papers to process: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_extraction())

    @cli.command("clear-enrich-5-checkpoint")
    def clear_enrich_5_checkpoint() -> None:
        """Clear checkpoint for enrich-5 (refs-by-pdf-via-grobid)."""
        from src.core.enrichment.pdf import PDFReferenceExtractor

        extractor = PDFReferenceExtractor()
        extractor.clear_checkpoint()
        click.echo("Enrich-5 (PDF refs) checkpoint cleared.")

    @cli.command("clear-enrich-7-checkpoint")
    def clear_enrich_7_checkpoint() -> None:
        """Clear checkpoint for enrich-7 (abstracts-by-pdf-via-grobid)."""
        from src.core.enrichment.pdf import PDFReferenceExtractor

        extractor = PDFReferenceExtractor()
        extractor.clear_abstract_checkpoint()
        click.echo("Enrich-7 (PDF abstracts) checkpoint cleared.")

    @cli.command("enrich-8-metadata-by-stub-via-openalex")
    @click.option("--limit", "-n", type=int, default=100, help="Max stubs to enrich")
    @click.option("--type", "identifier_type", type=click.Choice(["doi", "arxiv", "openalex"]),
                  help="Only enrich stubs of this type")
    @click.option("--min-citations", type=int, default=1, help="Only enrich stubs with >= N citations")
    @click.option("--dry-run", is_flag=True, help="Count stubs without enriching")
    @click.option("--parallel", "-p", type=int, default=5, help="Concurrent API requests")
    def enrich_8_metadata_by_stub_via_openalex(
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
          python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex

          # Enrich top 1000 DOI stubs
          python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --limit 1000 --type doi

          # Only enrich stubs cited 5+ times
          python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --min-citations 5

          # Dry run to see what would be enriched
          python -m src.cli.core_collect enrich-8-metadata-by-stub-via-openalex --dry-run
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

    @cli.command("enrich-9-resolve-title-refs-via-openalex")
    @click.option("--dry-run", is_flag=True, help="Count papers without resolving")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--delay", type=float, default=0.1, help="Delay between API calls")
    @click.option("--parallel", "-p", type=int, default=None, help="Concurrent requests (auto: 3 for API key, 1 for email)")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers still missing data (clears checkpoint)")
    def enrich_9_resolve_title_refs_via_openalex(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        delay: float,
        parallel: int | None,
        retry_incomplete: bool,
    ) -> None:
        """Resolve TITLE:xxx references to DOI/OpenAlex identifiers via OpenAlex title search.

        When GROBID extracts references from PDFs and only has a title (no DOI,
        no arXiv ID), it stores TITLE:<title> in referenced_works. This command
        resolves those to proper DOI:xxx or Wxxx identifiers by searching
        OpenAlex and fuzzy-matching titles.

        Examples:

          # Count papers with TITLE: refs
          python -m src.cli.core_collect enrich-9-resolve-title-refs-via-openalex --dry-run

          # Resolve all TITLE: refs
          python -m src.cli.core_collect enrich-9-resolve-title-refs-via-openalex

          # Resolve with parallel requests
          python -m src.cli.core_collect enrich-9-resolve-title-refs-via-openalex --parallel 5

          # Resolve first 100 papers
          python -m src.cli.core_collect enrich-9-resolve-title-refs-via-openalex --limit 100
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
                    enricher.clear_checkpoint(EnrichmentType.RESOLVE_TITLE_REFS)
                    click.echo("Checkpoint cleared — retrying title reference resolution.")
                progress = await enricher.resolve_title_references(
                    dry_run=dry_run,
                    limit=limit,
                )

                click.echo(f"\nTitle Reference Resolution Results:")
                click.echo(f"  Processed: {progress.processed}")
                click.echo(f"  Resolved:  {progress.enriched}")
                click.echo(f"  Not found: {progress.not_found}")
                click.echo(f"  Errors:    {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total papers to resolve: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_enrichment())

    @cli.command("clear-enrich-9-checkpoint")
    def clear_enrich_9_checkpoint() -> None:
        """Clear checkpoint for enrich-9 (resolve-title-refs-via-openalex).

        Examples:

          python -m src.cli.core_collect clear-enrich-9-checkpoint
        """
        from src.core.enrichment.openalex import PaperEnricher, EnrichmentType

        enricher = PaperEnricher()
        enricher.clear_checkpoint(EnrichmentType.RESOLVE_TITLE_REFS)
        click.echo("Enrich-9 (title ref resolution) checkpoint cleared.")

    @cli.command("enrich-10-code-repos")
    @click.option("--dry-run", is_flag=True, help="Count papers without enriching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=100, help="Batch size")
    @click.option("--delay", type=float, default=0.05, help="Delay between HF API calls (seconds)")
    @click.option("--parallel", "-p", type=int, default=10, help="Concurrent HF API requests")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers (clears checkpoint)")
    def enrich_10_code_repos(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        delay: float,
        parallel: int,
        retry_incomplete: bool,
    ) -> None:
        """Enrich papers with GitHub code repository URLs.

        Two-phase lookup:
        1. PWC Archive (bulk offline, ~300K paper->repo mappings)
        2. HuggingFace Papers API (live, for papers not in PWC)

        Only processes papers with arXiv source_id.

        Examples:

          # Count papers needing code repo enrichment
          python -m src.cli.core_collect enrich-10-code-repos --dry-run

          # Enrich all papers
          python -m src.cli.core_collect enrich-10-code-repos

          # Enrich first 50 papers
          python -m src.cli.core_collect enrich-10-code-repos --limit 50

          # Adjust HF API concurrency
          python -m src.cli.core_collect enrich-10-code-repos --parallel 20
        """
        from src.core.enrichment.code_repos import CodeRepoEnricher

        async def run_enrichment():
            storage = QdrantStorage()
            async with CodeRepoEnricher(
                storage=storage,
                batch_size=batch_size,
                delay=delay,
                max_concurrent=parallel,
            ) as enricher:
                if retry_incomplete:
                    enricher.clear_checkpoint()
                    click.echo("Checkpoint cleared — retrying code repo enrichment.")
                progress = await enricher.enrich_code_repos(
                    dry_run=dry_run,
                    limit=limit,
                )

                click.echo(f"\nCode Repository Enrichment Results:")
                click.echo(f"  Processed:      {progress.processed}")
                click.echo(f"  Enriched:       {progress.enriched}")
                click.echo(f"    PWC (arXiv):     {progress.pwc_hits}")
                click.echo(f"    PWC (title):     {progress.pwc_title_hits}")
                click.echo(f"    HuggingFace:     {progress.hf_hits}")
                click.echo(f"  Not found:      {progress.not_found}")
                click.echo(f"  Errors:         {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total papers to enrich: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_enrichment())

    @cli.command("clear-enrich-10-checkpoint")
    def clear_enrich_10_checkpoint() -> None:
        """Clear checkpoint for enrich-10 (code-repos).

        Examples:

          python -m src.cli.core_collect clear-enrich-10-checkpoint
        """
        from src.core.enrichment.code_repos import CodeRepoEnricher

        enricher = CodeRepoEnricher()
        enricher.clear_checkpoint()
        click.echo("Enrich-10 (code repos) checkpoint cleared.")

    @cli.command("enrich-11-code-repos-via-grobid")
    @click.option("--dry-run", is_flag=True, help="Count papers without extracting")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=20, help="Batch size")
    @click.option("--parallel", "-p", type=int, default=20, help="Concurrent PDF downloads + GROBID extractions")
    @click.option("--grobid-url", type=str, help="GROBID server URL (default: http://localhost:8070)")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers (clears checkpoint)")
    def enrich_11_code_repos_via_grobid(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        parallel: int,
        grobid_url: str | None,
        retry_incomplete: bool,
    ) -> None:
        """Extract GitHub code repo URLs from paper PDFs via GROBID full-text.

        Downloads PDFs, extracts full-text TEI-XML via GROBID, then finds
        and classifies GitHub URLs based on section and context heuristics.

        Requires GROBID server running:
          docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

        Examples:

          # Count papers with PDF URLs needing code repos
          python -m src.cli.core_collect enrich-11-code-repos-via-grobid --dry-run

          # Extract from first 10 papers
          python -m src.cli.core_collect enrich-11-code-repos-via-grobid --limit 10

          # Use custom GROBID URL
          python -m src.cli.core_collect enrich-11-code-repos-via-grobid --grobid-url http://grobid:8070
        """
        from src.core.enrichment.grobid_code_repos import GrobidCodeRepoExtractor

        async def run_enrichment():
            storage = QdrantStorage()
            async with GrobidCodeRepoExtractor(
                storage=storage,
                grobid_url=grobid_url,
                batch_size=batch_size,
                max_concurrent=parallel,
            ) as extractor:
                if retry_incomplete:
                    extractor.clear_checkpoint()
                    click.echo("Checkpoint cleared — retrying GROBID code repo extraction.")
                progress = await extractor.enrich_code_repos_via_grobid(
                    dry_run=dry_run,
                    limit=limit,
                )

                click.echo(f"\nGROBID Code Repo Extraction Results:")
                click.echo(f"  Processed:        {progress.processed}")
                click.echo(f"  Enriched:         {progress.enriched}")
                click.echo(f"  Download failed:  {progress.download_failed}")
                click.echo(f"  GROBID failed:    {progress.grobid_failed}")
                click.echo(f"  No URLs found:    {progress.no_urls_found}")
                click.echo(f"  Errors:           {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total papers with PDF: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_enrichment())

    @cli.command("enrich-12-code-repos-via-github")
    @click.option("--dry-run", is_flag=True, help="Count papers without searching")
    @click.option("--limit", "-n", type=int, help="Max papers to process")
    @click.option("--batch-size", type=int, default=50, help="Batch size")
    @click.option("--github-token", type=str, help="GitHub API token (or set GITHUB_TOKEN env)")
    @click.option("--retry-incomplete", is_flag=True, help="Re-process papers (clears checkpoint)")
    def enrich_12_code_repos_via_github(
        dry_run: bool,
        limit: int | None,
        batch_size: int,
        github_token: str | None,
        retry_incomplete: bool,
    ) -> None:
        """Search GitHub API for code repositories matching papers.

        Two-tier strategy:
          Tier A: arXiv ID in README.md (high precision)
          Tier B: Title search with validation heuristics

        Rate limits: 30 req/min with GITHUB_TOKEN, 10/min without.

        Examples:

          # Count papers needing GitHub search
          python -m src.cli.core_collect enrich-12-code-repos-via-github --dry-run

          # Search first 10 papers
          python -m src.cli.core_collect enrich-12-code-repos-via-github --limit 10

          # Provide token directly
          python -m src.cli.core_collect enrich-12-code-repos-via-github --github-token ghp_xxx
        """
        from src.core.enrichment.github_search import GitHubSearchEnricher

        async def run_enrichment():
            storage = QdrantStorage()
            async with GitHubSearchEnricher(
                storage=storage,
                github_token=github_token,
                batch_size=batch_size,
            ) as enricher:
                if retry_incomplete:
                    enricher.clear_checkpoint()
                    click.echo("Checkpoint cleared — retrying GitHub search enrichment.")
                progress = await enricher.enrich_code_repos_via_github(
                    dry_run=dry_run,
                    limit=limit,
                )

                click.echo(f"\nGitHub Search Enrichment Results:")
                click.echo(f"  Processed:      {progress.processed}")
                click.echo(f"  Enriched:       {progress.enriched}")
                click.echo(f"    Tier A (arXiv):  {progress.tier_a_hits}")
                click.echo(f"    Tier B (title):  {progress.tier_b_hits}")
                click.echo(f"  Not found:      {progress.not_found}")
                click.echo(f"  Errors:         {progress.errors}")

                if dry_run:
                    click.echo(f"\n  Total papers to search: {progress.total_to_process}")
                    click.echo("  (Dry run - no changes made)")

        asyncio.run(run_enrichment())

    @cli.command("clear-enrich-11-checkpoint")
    def clear_enrich_11_checkpoint() -> None:
        """Clear checkpoint for enrich-11 (GROBID code repos).

        Examples:

          python -m src.cli.core_collect clear-enrich-11-checkpoint
        """
        from src.core.enrichment.grobid_code_repos import GrobidCodeRepoExtractor

        extractor = GrobidCodeRepoExtractor()
        extractor.clear_checkpoint()
        click.echo("Enrich-11 (GROBID code repos) checkpoint cleared.")

    @cli.command("clear-enrich-12-checkpoint")
    def clear_enrich_12_checkpoint() -> None:
        """Clear checkpoint for enrich-12 (GitHub search).

        Examples:

          python -m src.cli.core_collect clear-enrich-12-checkpoint
        """
        from src.core.enrichment.github_search import GitHubSearchEnricher

        enricher = GitHubSearchEnricher()
        enricher.clear_checkpoint()
        click.echo("Enrich-12 (GitHub search) checkpoint cleared.")
