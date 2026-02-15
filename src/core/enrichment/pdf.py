"""PDF reference extraction using GROBID.

GROBID (GeneRation Of BIbliographic Data) is a machine learning library
for extracting structured information from scholarly PDFs.

Setup:
1. Run GROBID server via Docker:
   docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0

2. Or install locally: https://grobid.readthedocs.io/en/latest/Install-Grobid/

API Documentation: https://grobid.readthedocs.io/en/latest/Grobid-service/
"""

import asyncio
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)

# GROBID server URL (default Docker port)
GROBID_URL = os.getenv("GROBID_URL", "http://localhost:8070")

# TEI XML namespace
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


@dataclass
class PDFExtractionProgress:
    """Track PDF extraction progress."""

    total_to_process: int = 0
    processed: int = 0
    extracted: int = 0
    download_failed: int = 0
    parse_failed: int = 0
    no_refs: int = 0
    errors: int = 0
    last_offset: str | None = None
    processed_point_ids: set[str] = field(default_factory=set)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_updated: str | None = None


class PDFReferenceExtractor:
    """Extract references from PDFs using GROBID."""

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        grobid_url: str | None = None,
        checkpoint_dir: Path | str | None = None,
        batch_size: int = 50,
        max_concurrent: int = 20,
        download_timeout: float = 60.0,
        grobid_timeout: float = 120.0,
    ):
        """Initialize PDFReferenceExtractor.

        Args:
            storage: QdrantStorage instance.
            grobid_url: GROBID server URL.
            checkpoint_dir: Directory for checkpoint files.
            batch_size: Papers per batch.
            max_concurrent: Max concurrent PDF download + GROBID extractions.
            download_timeout: Timeout for PDF download.
            grobid_timeout: Timeout for GROBID processing.
        """
        self.storage = storage or QdrantStorage()
        self.grobid_url = grobid_url or GROBID_URL
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.download_timeout = download_timeout
        self.grobid_timeout = grobid_timeout

        self.checkpoint_dir = Path(checkpoint_dir or "data/core/checkpoints")
        self.checkpoint_file = self.checkpoint_dir / "pdf_extraction.json"
        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None

    async def __aenter__(self) -> "PDFReferenceExtractor":
        """Enter async context."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=self.grobid_timeout,
                write=30.0,
                pool=10.0,
            ),
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        # Check GROBID is available
        try:
            response = await self._client.get(f"{self.grobid_url}/api/isalive")
            if response.status_code == 200:
                logger.info(f"GROBID server available at {self.grobid_url}")
            else:
                logger.warning(f"GROBID server returned {response.status_code}")
        except Exception as e:
            logger.error(f"Cannot connect to GROBID at {self.grobid_url}: {e}")
            logger.error("Start GROBID with: docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0")

        return self

    async def __aexit__(self, *args) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()

    async def download_pdf(self, url: str, max_retries: int = 3) -> bytes | None:
        """Download PDF from URL with retry logic.

        Args:
            url: PDF URL.
            max_retries: Maximum retry attempts for transient errors.

        Returns:
            PDF bytes or None if failed.
        """
        if not self._client:
            raise RuntimeError("Client not initialized.")

        for attempt in range(max_retries):
            try:
                response = await self._client.get(
                    url,
                    timeout=self.download_timeout,
                    headers={"User-Agent": "LexiconArxiv/1.0 (Citation enrichment)"},
                )
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if "pdf" not in content_type.lower() and not url.endswith(".pdf"):
                    logger.warning(f"Not a PDF: {url} (content-type: {content_type})")
                    return None

                return response.content

            except httpx.TimeoutException:
                logger.warning(f"Timeout downloading {url} (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                return None
            except (httpx.RemoteProtocolError, httpx.ConnectError) as e:
                # Transient network errors - retry
                logger.warning(f"Network error downloading {url} (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None
            except Exception as e:
                logger.warning(f"Error downloading {url}: {e}")
                return None

        return None

    async def extract_references_from_pdf(
        self, pdf_content: bytes
    ) -> list[dict[str, Any]] | None:
        """Extract references from PDF using GROBID.

        Args:
            pdf_content: PDF file content as bytes.

        Returns:
            List of reference dicts with title, authors, doi, etc.
        """
        if not self._client:
            raise RuntimeError("Client not initialized.")

        try:
            # Use GROBID's processReferences endpoint
            files = {"input": ("paper.pdf", pdf_content, "application/pdf")}
            response = await self._client.post(
                f"{self.grobid_url}/api/processReferences",
                files=files,
                timeout=self.grobid_timeout,
            )

            if response.status_code != 200:
                logger.warning(f"GROBID returned {response.status_code}")
                return None

            # Parse TEI XML response
            return self._parse_tei_references(response.text)

        except httpx.TimeoutException:
            logger.warning("GROBID processing timeout")
            return None
        except Exception as e:
            logger.warning(f"GROBID error: {e}")
            return None

    def _parse_tei_references(self, tei_xml: str) -> list[dict[str, Any]]:
        """Parse TEI XML to extract references.

        Args:
            tei_xml: TEI XML string from GROBID.

        Returns:
            List of reference dicts.
        """
        try:
            root = ET.fromstring(tei_xml)
        except ET.ParseError as e:
            logger.warning(f"XML parse error: {e}")
            return []

        references = []

        # Find all biblStruct elements (references)
        for bibl in root.findall(".//tei:biblStruct", TEI_NS):
            ref = self._parse_bibl_struct(bibl)
            if ref:
                references.append(ref)

        return references

    def _parse_bibl_struct(self, bibl: ET.Element) -> dict[str, Any] | None:
        """Parse a single biblStruct element.

        Args:
            bibl: biblStruct XML element.

        Returns:
            Reference dict or None.
        """
        ref: dict[str, Any] = {}

        # Extract title
        title_elem = bibl.find(".//tei:title[@level='a']", TEI_NS)
        if title_elem is None:
            title_elem = bibl.find(".//tei:title", TEI_NS)
        if title_elem is not None and title_elem.text:
            ref["title"] = title_elem.text.strip()

        # Extract authors
        authors = []
        for author in bibl.findall(".//tei:author/tei:persName", TEI_NS):
            name_parts = []
            forename = author.find("tei:forename", TEI_NS)
            surname = author.find("tei:surname", TEI_NS)
            if forename is not None and forename.text:
                name_parts.append(forename.text)
            if surname is not None and surname.text:
                name_parts.append(surname.text)
            if name_parts:
                authors.append(" ".join(name_parts))
        if authors:
            ref["authors"] = authors

        # Extract year
        date_elem = bibl.find(".//tei:date[@when]", TEI_NS)
        if date_elem is not None:
            when = date_elem.get("when", "")
            if when:
                ref["year"] = when[:4]

        # Extract DOI
        doi_elem = bibl.find(".//tei:idno[@type='DOI']", TEI_NS)
        if doi_elem is not None and doi_elem.text:
            ref["doi"] = doi_elem.text.strip()

        # Extract arXiv ID
        arxiv_elem = bibl.find(".//tei:idno[@type='arXiv']", TEI_NS)
        if arxiv_elem is not None and arxiv_elem.text:
            ref["arxiv_id"] = arxiv_elem.text.strip()

        # Only return if we have at least a title
        if "title" in ref:
            return ref

        return None

    def _refs_to_identifiers(self, refs: list[dict[str, Any]]) -> list[str]:
        """Convert extracted references to identifier strings.

        Args:
            refs: List of reference dicts from GROBID.

        Returns:
            List of identifier strings (DOI:xxx or TITLE:xxx).
        """
        identifiers = []
        for ref in refs:
            if ref.get("doi"):
                identifiers.append(f"DOI:{ref['doi']}")
            elif ref.get("arxiv_id"):
                arxiv_id = ref["arxiv_id"]
                # Strip "arXiv:" prefix if already present
                if arxiv_id.lower().startswith("arxiv:"):
                    arxiv_id = arxiv_id[6:]
                identifiers.append(f"arXiv:{arxiv_id}")
            elif ref.get("title"):
                # Use title hash as fallback identifier
                title_clean = re.sub(r"[^\w\s]", "", ref["title"].lower())
                title_hash = title_clean[:100]
                identifiers.append(f"TITLE:{title_hash}")

        return identifiers

    async def extract_and_enrich(
        self,
        point_id: str,
        pdf_url: str,
    ) -> tuple[bool, list[str]]:
        """Download PDF and extract references.

        Args:
            point_id: Qdrant point ID.
            pdf_url: URL to PDF.

        Returns:
            Tuple of (success, list of reference identifiers).
        """
        async with self._semaphore:
            # Download PDF
            pdf_content = await self.download_pdf(pdf_url)
            if not pdf_content:
                return False, []

            # Extract references
            refs = await self.extract_references_from_pdf(pdf_content)
            if not refs:
                return False, []

            # Convert to identifiers
            identifiers = self._refs_to_identifiers(refs)
            return True, identifiers

    async def enrich_from_pdfs(
        self,
        dry_run: bool = False,
        limit: int | None = None,
        venues: list[str] | None = None,
    ) -> PDFExtractionProgress:
        """Extract references from PDFs for papers missing citation data.

        Args:
            dry_run: Only count papers without processing.
            limit: Maximum papers to process.
            venues: Filter by venue names.

        Returns:
            PDFExtractionProgress with statistics.
        """
        progress = self._load_checkpoint()
        offset = progress.last_offset

        logger.info("Starting PDF reference extraction...")

        while True:
            # Get papers with PDF URL but no refs
            papers, next_offset = self._get_papers_with_pdf_urls(
                limit=self.batch_size,
                offset=offset,
                venues=venues,
            )

            if not papers:
                break

            if dry_run:
                progress.total_to_process += len(papers)
                logger.info(f"Found {len(papers)} papers with PDF URLs (dry run)")
            else:
                extracted = await self._process_batch(papers, progress)
                logger.info(
                    f"Batch: {extracted}/{len(papers)} extracted | "
                    f"Total: {progress.extracted} extracted, "
                    f"{progress.download_failed} download failed, "
                    f"{progress.no_refs} no refs"
                )

            progress.last_offset = next_offset
            progress.last_updated = datetime.now(timezone.utc).isoformat()
            self._save_checkpoint(progress)

            offset = next_offset
            if offset is None:
                break

            if limit and progress.processed >= limit:
                break

        logger.info(
            f"PDF extraction complete: {progress.extracted} extracted, "
            f"{progress.download_failed} download failed, "
            f"{progress.parse_failed} parse failed, "
            f"{progress.no_refs} no refs"
        )
        return progress

    def _get_papers_with_pdf_urls(
        self,
        limit: int,
        offset: str | None,
        venues: list[str] | None = None,
    ) -> tuple[list[tuple[str, dict]], str | None]:
        """Get papers with PDF URLs that are missing references.

        This queries papers that have pdf_url but empty referenced_works.
        """
        from qdrant_client.http import models

        filter_conditions = [
            models.IsEmptyCondition(
                is_empty=models.PayloadField(key="referenced_works"),
            ),
        ]

        # Exclude papers without pdf_url
        must_not_conditions = [
            models.IsNullCondition(
                is_null=models.PayloadField(key="pdf_url"),
            ),
        ]

        if venues:
            filter_conditions.append(
                models.FieldCondition(
                    key="venue",
                    match=models.MatchAny(any=venues),
                )
            )

        scroll_filter = models.Filter(
            must=filter_conditions,
            must_not=must_not_conditions,
        )

        results, next_offset = self.storage.client.scroll(
            collection_name=self.storage.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )

        return [(str(p.id), p.payload) for p in results], next_offset

    async def _process_batch(
        self,
        papers: list[tuple[str, dict]],
        progress: PDFExtractionProgress,
    ) -> int:
        """Process a batch of papers concurrently."""
        to_process = [
            (pid, payload)
            for pid, payload in papers
            if payload.get("pdf_url") and pid not in progress.processed_point_ids
        ]

        if not to_process:
            return 0

        async def _process_one(point_id: str, payload: dict) -> tuple[str, dict, bool, list[str]]:
            pdf_url = payload.get("pdf_url")
            success, refs = await self.extract_and_enrich(point_id, pdf_url)
            return point_id, payload, success, refs

        # Run all papers in batch concurrently (semaphore in extract_and_enrich limits actual concurrency)
        tasks = [_process_one(pid, payload) for pid, payload in to_process]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        extracted = 0
        updates = []

        for result in results:
            progress.processed += 1

            if isinstance(result, Exception):
                logger.warning(f"Unexpected error in PDF extraction: {result}")
                progress.download_failed += 1
                continue

            point_id, payload, success, refs = result
            progress.processed_point_ids.add(point_id)

            if not success:
                if refs == []:
                    progress.download_failed += 1
                else:
                    progress.parse_failed += 1
                continue

            if refs:
                updates.append((point_id, refs))
                progress.extracted += 1
                extracted += 1
                logger.debug(
                    f"Extracted {len(refs)} refs from {payload.get('title', '')[:40]}"
                )
            else:
                progress.no_refs += 1

        if updates:
            self.storage.batch_update_referenced_works(updates)

        return extracted

    def _load_checkpoint(self) -> PDFExtractionProgress:
        """Load checkpoint."""
        if self.checkpoint_file.exists():
            with open(self.checkpoint_file) as f:
                data = json.load(f)
            progress = PDFExtractionProgress(
                total_to_process=data.get("total_to_process", 0),
                processed=data.get("processed", 0),
                extracted=data.get("extracted", 0),
                download_failed=data.get("download_failed", 0),
                parse_failed=data.get("parse_failed", 0),
                no_refs=data.get("no_refs", 0),
                errors=data.get("errors", 0),
                last_offset=data.get("last_offset"),
                started_at=data.get("started_at", datetime.now(timezone.utc).isoformat()),
                last_updated=data.get("last_updated"),
            )
            progress.processed_point_ids = set(data.get("processed_point_ids", []))
            return progress
        return PDFExtractionProgress()

    def _save_checkpoint(self, progress: PDFExtractionProgress) -> None:
        """Save checkpoint."""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "total_to_process": progress.total_to_process,
            "processed": progress.processed,
            "extracted": progress.extracted,
            "download_failed": progress.download_failed,
            "parse_failed": progress.parse_failed,
            "no_refs": progress.no_refs,
            "errors": progress.errors,
            "last_offset": progress.last_offset,
            "processed_point_ids": list(progress.processed_point_ids),
            "started_at": progress.started_at,
            "last_updated": progress.last_updated,
        }
        with open(self.checkpoint_file, "w") as f:
            json.dump(data, f, indent=2)

    def clear_checkpoint(self) -> None:
        """Clear checkpoint."""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
            logger.info("PDF extraction checkpoint cleared")
