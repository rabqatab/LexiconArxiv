"""Unpaywall OA-PDF enrichment.

Fills ``pdf_url`` on papers that have a DOI but no PDF link, using Unpaywall's
free by-DOI endpoint (email required, no API key). The by-DOI endpoint is not
rate-throttled the way OpenAlex title-search is, so this is cheap to run.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.core.constants import UNPAYWALL_BASE_URL, get_unpaywall_email
from src.core.enrichment.base import BaseEnricher

if TYPE_CHECKING:
    from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)


def parse_oa_pdf(data: dict[str, Any]) -> tuple[str, str | None] | None:
    """Extract (pdf_url, oa_status) from an Unpaywall work response.

    Prefers best_oa_location.url_for_pdf; falls back to its landing url.
    Returns None when the work is not open access / has no usable location.
    """
    if not data or not data.get("is_oa"):
        return None
    loc = data.get("best_oa_location") or {}
    url = loc.get("url_for_pdf") or loc.get("url")
    if not url:
        return None
    return url, data.get("oa_status")


@dataclass
class UnpaywallProgress:
    total_to_process: int = 0
    processed: int = 0
    enriched: int = 0
    not_oa: int = 0
    not_found: int = 0
    errors: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class UnpaywallEnricher(BaseEnricher):
    """Fill pdf_url for DOI-bearing papers via Unpaywall."""

    def __init__(
        self,
        storage: "QdrantStorage | None" = None,
        email: str | None = None,
        delay: float = 0.1,
        max_concurrent: int = 5,
        batch_size: int = 100,
    ):
        super().__init__(storage=storage, delay=delay, max_concurrent=max_concurrent)
        self.email = email or get_unpaywall_email()
        self.batch_size = batch_size

    async def fetch_oa_pdf(self, doi: str) -> tuple[str, str | None] | None:
        """Look up a DOI on Unpaywall; return (pdf_url, oa_status) or None."""
        doi = doi.replace("https://doi.org/", "").replace("doi:", "").replace("DOI:", "")
        url = f"{UNPAYWALL_BASE_URL}/{doi}"
        try:
            resp = await self._rate_limited_request(
                "get", url, params={"email": self.email}
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return parse_oa_pdf(resp.json())
        except Exception as e:
            logger.debug(f"Unpaywall fetch error for {doi}: {e}")
            return None

    async def enrich_oa_pdfs(
        self,
        dry_run: bool = False,
        limit: int | None = None,
        fetched_since: str | None = None,
    ) -> UnpaywallProgress:
        """Fill pdf_url for papers with a DOI but no pdf_url."""
        progress = UnpaywallProgress()
        offset = None
        while True:
            papers, offset = self.storage.get_papers_with_doi_missing_pdf(
                limit=self.batch_size, offset=offset, fetched_since=fetched_since,
            )
            if not papers:
                break

            if dry_run:
                progress.total_to_process += len(papers)
            else:
                updates = []
                for point_id, payload in papers:
                    progress.processed += 1
                    doi = payload.get("doi")
                    if not doi:
                        continue
                    result = await self.fetch_oa_pdf(doi)
                    if result is None:
                        progress.not_oa += 1
                        continue
                    pdf_url, oa_status = result
                    updates.append((point_id, pdf_url, oa_status))
                if updates:
                    self.storage.batch_update_oa_pdf(updates)
                    progress.enriched += len(updates)
                logger.info(
                    f"Unpaywall batch: {len(updates)}/{len(papers)} OA PDFs found "
                    f"(total enriched {progress.enriched})"
                )

            if offset is None:
                break
            if limit and progress.processed >= limit:
                break

        logger.info(
            f"Unpaywall enrichment complete: {progress.enriched} enriched, "
            f"{progress.not_oa} not-OA, {progress.errors} errors"
        )
        return progress
