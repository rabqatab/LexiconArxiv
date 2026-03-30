"""ACL Anthology Crawler for NLP venue paper collection.

Collects papers from ACL Anthology XML files hosted on GitHub.
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any, AsyncIterator

from src.core.checkpoint import CheckpointManager
from src.core.crawler.base import BaseCrawler
from src.core.deduplication import Deduplicator
from src.models.paper import Author, PaperType, RawPaper, SourceType

if TYPE_CHECKING:
    from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)

# ACL Anthology GitHub repository raw file base URL
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/acl-org/acl-anthology/master/data/xml"
GITHUB_API_BASE = "https://api.github.com/repos/acl-org/acl-anthology/contents/data/xml"
# Use Git Trees API for full listing (Contents API is limited to 1000 files)
GITHUB_TREES_API = "https://api.github.com/repos/acl-org/acl-anthology/git/trees/master?recursive=1"

# Target NLP venues with their ACL Anthology prefixes
ACL_VENUES = {
    "acl": {
        "prefixes": ["acl"],
        "full_name": "Annual Meeting of the Association for Computational Linguistics",
        "tier": 0,
    },
    "emnlp": {
        "prefixes": ["emnlp"],
        "full_name": "Conference on Empirical Methods in Natural Language Processing",
        "tier": 0,
    },
    "naacl": {
        "prefixes": ["naacl"],
        "full_name": "North American Chapter of the ACL",
        "tier": 1,
    },
    "eacl": {
        "prefixes": ["eacl"],
        "full_name": "European Chapter of the ACL",
        "tier": 1,
    },
    "coling": {
        "prefixes": ["coling"],
        "full_name": "International Conference on Computational Linguistics",
        "tier": 1,
    },
    "findings": {
        "prefixes": ["findings"],
        "full_name": "Findings of the ACL",
        "tier": 1,
    },
    "tacl": {
        "prefixes": ["tacl"],
        "full_name": "Transactions of the ACL",
        "tier": 1,
    },
    "conll": {
        "prefixes": ["conll"],
        "full_name": "Conference on Computational Natural Language Learning",
        "tier": 1,
    },
    "lrec": {
        "prefixes": ["lrec"],
        "full_name": "Language Resources and Evaluation Conference",
        "tier": 1,
    },
    "aacl": {
        "prefixes": ["aacl", "ijcnlp"],
        "full_name": "Asia-Pacific Chapter of the ACL / IJCNLP",
        "tier": 1,
    },
}

# All main venue prefixes (used to identify workshop files)
MAIN_VENUE_PREFIXES = set()
for venue_info in ACL_VENUES.values():
    MAIN_VENUE_PREFIXES.update(venue_info["prefixes"])

# Known event locations for co-location detection
EVENT_LOCATIONS = {
    "acl-2023": ("Toronto, Canada", "July", "2023"),
    "emnlp-2023": ("Singapore", "December", "2023"),
    "acl-2022": ("Dublin, Ireland", "May", "2022"),
    "emnlp-2022": ("Abu Dhabi, UAE", "December", "2022"),
    "acl-2024": ("Bangkok, Thailand", "August", "2024"),
    "emnlp-2024": ("Miami, USA", "November", "2024"),
}


class ACLAnthologyCollector(BaseCrawler):
    """Collector for papers from ACL Anthology.

    Downloads XML files from the ACL Anthology GitHub repository
    and parses them into RawPaper objects.
    """

    DEFAULT_USER_AGENT = "LexiconArxiv/1.0 (ACL Anthology Collection)"

    def __init__(
        self,
        storage: "QdrantStorage | None" = None,
        checkpoint_manager: CheckpointManager | None = None,
        deduplicator: Deduplicator | None = None,
        timeout: float = 60.0,
    ):
        """Initialize the collector.

        Args:
            storage: Qdrant storage instance. Created if not provided.
            checkpoint_manager: Checkpoint manager. Created if not provided.
            deduplicator: Deduplicator instance. Created if not provided.
                Pass a shared instance for cross-source deduplication.
            timeout: HTTP request timeout in seconds.
        """
        super().__init__(
            storage=storage,
            checkpoint_manager=checkpoint_manager,
            deduplicator=deduplicator,
            timeout=timeout,
            checkpoint_name="acl_anthology",
        )

    def _get_default_headers(self) -> dict[str, str]:
        """Get default HTTP headers for GitHub API."""
        return {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "application/vnd.github.v3+json",
        }

    async def list_xml_files(self, venue_prefix: str | None = None) -> list[str]:
        """List available XML files from ACL Anthology GitHub.

        Uses Git Trees API to get complete listing (Contents API is limited to 1000 files).

        Args:
            venue_prefix: Optional prefix to filter files (e.g., "acl", "emnlp").

        Returns:
            List of XML filenames.
        """
        try:
            # Use Trees API to get full file listing (no pagination limit)
            response = await self.client.get(GITHUB_TREES_API)
            response.raise_for_status()
            data = response.json()

            xml_files = []
            for item in data.get("tree", []):
                path = item.get("path", "")
                # Filter to data/xml/*.xml files
                if not path.startswith("data/xml/") or not path.endswith(".xml"):
                    continue

                filename = path.split("/")[-1]
                if venue_prefix:
                    # Match pattern like "2023.acl.xml" or "acl.xml"
                    if venue_prefix in filename.lower():
                        xml_files.append(filename)
                else:
                    xml_files.append(filename)

            logger.info(f"Found {len(xml_files)} XML files in ACL Anthology")
            return sorted(xml_files)

        except Exception as e:
            logger.error(f"Failed to list XML files: {e}")
            return []

    async def download_xml(self, filename: str) -> str | None:
        """Download an XML file from ACL Anthology GitHub.

        Args:
            filename: Name of the XML file to download.

        Returns:
            XML content as string, or None if download fails.
        """
        url = f"{GITHUB_RAW_BASE}/{filename}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Failed to download {filename}: {e}")
            return None

    def _parse_author(self, author_elem: ET.Element) -> Author:
        """Parse an author element from XML.

        Args:
            author_elem: XML element containing author data.

        Returns:
            Author object.
        """
        first = author_elem.findtext("first", "")
        last = author_elem.findtext("last", "")
        name = f"{first} {last}".strip() or "Unknown"

        # Get affiliation if present
        affiliation = None
        affiliation_elem = author_elem.find("affiliation")
        if affiliation_elem is not None:
            affiliation = affiliation_elem.text

        return Author(
            name=name,
            affiliation=affiliation,
            orcid=author_elem.get("orcid"),
        )

    def _determine_paper_type(self, paper_elem: ET.Element, venue: str) -> PaperType:
        """Determine paper type from XML element and venue.

        Args:
            paper_elem: XML paper element.
            venue: Venue name.

        Returns:
            PaperType enum value.
        """
        title = (paper_elem.findtext("title") or "").lower()

        # Check title for type indicators
        if "survey" in title or "review" in title or "overview" in title:
            return PaperType.SURVEY
        if "dataset" in title or "corpus" in title or "benchmark" in title:
            return PaperType.DATASET
        if "demo" in title or "demonstration" in title or "system" in title:
            return PaperType.DEMO
        if "position" in title or "perspective" in title:
            return PaperType.POSITION
        if "analysis" in title or "study of" in title:
            return PaperType.ANALYSIS

        return PaperType.METHOD

    def parse_volume(
        self,
        xml_content: str,
        venue_name: str,
        venue_info: dict[str, Any],
    ) -> list[RawPaper]:
        """Parse an ACL Anthology XML file into RawPaper objects.

        Args:
            xml_content: XML content as string.
            venue_name: Short venue name (e.g., "acl").
            venue_info: Venue info dictionary from ACL_VENUES.

        Returns:
            List of parsed RawPaper objects.
        """
        papers = []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML: {e}")
            return papers

        # Get collection ID for the anthology ID prefix
        collection_id = root.get("id", "")

        for volume in root.findall(".//volume"):
            volume_id = volume.get("id", "")

            # Parse volume metadata
            meta = volume.find("meta")
            if meta is None:
                continue

            booktitle = meta.findtext("booktitle", "")
            address = meta.findtext("address")
            month_str = meta.findtext("month")
            year_str = meta.findtext("year")
            venue_tag = meta.findtext("venue", venue_name)

            try:
                year = int(year_str) if year_str else None
            except ValueError:
                year = None

            # Parse month
            month = None
            if month_str:
                month_mapping = {
                    "january": 1, "february": 2, "march": 3, "april": 4,
                    "may": 5, "june": 6, "july": 7, "august": 8,
                    "september": 9, "october": 10, "november": 11, "december": 12,
                }
                month_lower = month_str.lower().split("-")[0].split()[0]
                month = month_mapping.get(month_lower)

            # Determine venue type from booktitle
            venue_type = "conference"
            if "workshop" in booktitle.lower():
                venue_type = "workshop"
            elif "journal" in booktitle.lower() or "transactions" in booktitle.lower():
                venue_type = "journal"
            elif "proceedings" in booktitle.lower():
                venue_type = "conference"

            # Parse papers in this volume
            for paper_elem in volume.findall("paper"):
                paper_id = paper_elem.get("id", "")
                if not paper_id:
                    continue

                # Build ACL Anthology ID
                acl_id = f"{collection_id}-{volume_id}.{paper_id}"
                if not collection_id:
                    acl_id = f"{volume_id}.{paper_id}"

                # Get title - use itertext() to handle nested elements like <fixed-case>
                title_elem = paper_elem.find("title")
                if title_elem is None:
                    continue
                title = ''.join(title_elem.itertext()).strip()
                if not title:
                    continue

                # Get abstract - use itertext() to handle nested elements
                abstract_elem = paper_elem.find("abstract")
                abstract = None
                if abstract_elem is not None:
                    abstract = ''.join(abstract_elem.itertext()).strip()

                # Parse authors
                authors = []
                for author_elem in paper_elem.findall("author"):
                    authors.append(self._parse_author(author_elem))

                # Get DOI
                doi = paper_elem.findtext("doi")

                # Get PDF URL
                pdf_url = None
                url_elem = paper_elem.find("url")
                if url_elem is not None and url_elem.text:
                    # Convert ACL ID to PDF URL
                    pdf_url = f"https://aclanthology.org/{url_elem.text}.pdf"

                # Determine paper type
                paper_type = self._determine_paper_type(paper_elem, venue_name)

                paper = RawPaper(
                    source=SourceType.ACL,
                    source_id=acl_id,
                    title=title,
                    abstract=abstract,
                    authors=authors,
                    year=year,
                    month=month,
                    doi=doi,
                    acl_id=acl_id,
                    venue=booktitle or venue_info["full_name"],
                    venue_type=venue_type,
                    paper_type=paper_type,
                    pdf_url=pdf_url,
                    abstract_url=f"https://aclanthology.org/{acl_id}/" if acl_id else None,
                    tier=venue_info.get("tier", 1),
                    is_core=True,
                    raw_data={
                        "collection_id": collection_id,
                        "volume_id": volume_id,
                        "paper_id": paper_id,
                        "address": address,
                        "month": month_str,
                    },
                )
                papers.append(paper)

        return papers

    async def collect_venue(
        self,
        venue: str,
        since_year: int = 2020,
        to_year: int | None = None,
        save_to_storage: bool = True,
        since_date: str | None = None,
        to_date: str | None = None,
        force: bool = False,
    ) -> AsyncIterator[list[RawPaper]]:
        """Collect papers from a specific ACL venue.

        Args:
            venue: Venue name (e.g., "acl", "emnlp").
            since_year: Collect papers from this year onwards (ignored if since_date provided).
            to_year: Collect papers until this year (ignored if to_date provided).
            save_to_storage: Whether to save papers to Qdrant.
            since_date: Start date in YYYY-MM-DD or YYYY-MM format.
            to_date: End date in YYYY-MM-DD or YYYY-MM format.
            force: If True, skip the is_complete check (for incremental runs).

        Yields:
            Batches of collected papers.
        """
        # Parse date constraints
        if since_date:
            since_year = int(since_date[:4])
            since_month = int(since_date[5:7]) if len(since_date) >= 7 else 1
        else:
            since_month = 1

        if to_date:
            to_year = int(to_date[:4])
            to_month = int(to_date[5:7]) if len(to_date) >= 7 else 12
        else:
            to_month = 12
        venue_lower = venue.lower()
        if venue_lower not in ACL_VENUES:
            logger.error(f"Unknown ACL venue: {venue}")
            return

        venue_info = ACL_VENUES[venue_lower]
        prefixes = venue_info["prefixes"]

        # Load checkpoint
        checkpoint = self.checkpoint_manager.load()
        checkpoint_key = f"acl_{venue_lower}"

        # Check if already complete
        if not force and self.checkpoint_manager.is_venue_complete(checkpoint, checkpoint_key):
            logger.info(f"Venue {venue} already complete, skipping")
            return

        logger.info(f"Collecting ACL Anthology: {venue} from {since_year}")

        # List and filter XML files for this venue
        all_files = await self.list_xml_files()
        venue_files = []

        for filename in all_files:
            # Match patterns like "2023.acl.xml" or "acl.xml"
            for prefix in prefixes:
                if prefix in filename.lower():
                    # Extract year from filename if present
                    year_match = re.search(r"(\d{4})", filename)
                    if year_match:
                        file_year = int(year_match.group(1))
                        if file_year >= since_year:
                            if to_year is None or file_year <= to_year:
                                venue_files.append((filename, file_year))
                    else:
                        # Files without year in name (legacy format)
                        venue_files.append((filename, None))

        logger.info(f"Found {len(venue_files)} XML files for {venue}")

        papers_collected = 0
        progress = checkpoint.get_venue_progress(checkpoint_key)
        if progress:
            papers_collected = progress.papers_collected

        processed_files: set[str] = set()
        if progress and progress.cursor:
            # Resume from checkpoint - cursor contains processed files
            processed_files = set(progress.cursor.split(",")) if progress.cursor else set()

        try:
            for filename, file_year in venue_files:
                if filename in processed_files:
                    continue

                logger.info(f"Processing {filename}")

                xml_content = await self.download_xml(filename)
                if not xml_content:
                    continue

                papers = self.parse_volume(xml_content, venue_lower, venue_info)

                # Filter by year/month and deduplicate
                batch = []
                for paper in papers:
                    if not paper.year:
                        continue

                    # Get paper month from raw_data if available
                    paper_month = None
                    if paper.raw_data and paper.raw_data.get("month"):
                        month_str = paper.raw_data["month"]
                        # Convert month name to number
                        month_map = {
                            "january": 1, "february": 2, "march": 3, "april": 4,
                            "may": 5, "june": 6, "july": 7, "august": 8,
                            "september": 9, "october": 10, "november": 11, "december": 12
                        }
                        paper_month = month_map.get(month_str.lower().split("-")[0], None)

                    # Year filtering
                    if paper.year < since_year:
                        continue
                    if to_year and paper.year > to_year:
                        continue

                    # Month filtering (only if we have month info and date constraints)
                    if paper_month:
                        if paper.year == since_year and paper_month < since_month:
                            continue
                        if to_year and paper.year == to_year and paper_month > to_month:
                            continue

                    # Check for duplicates
                    dup_result = self.deduplicator.check_and_add(paper)
                    if not dup_result.is_duplicate:
                        batch.append(paper)

                if batch:
                    if save_to_storage:
                        self.storage.upsert_papers(batch)

                    papers_collected += len(batch)
                    checkpoint.total_papers += len(batch)

                    yield batch

                # Update checkpoint
                processed_files.add(filename)
                self.checkpoint_manager.update_venue(
                    checkpoint,
                    checkpoint_key,
                    cursor=",".join(sorted(processed_files)),
                    papers_collected=papers_collected,
                )

                # Small delay to be nice to GitHub
                await asyncio.sleep(0.5)

            # Mark venue as complete
            self.checkpoint_manager.update_venue(
                checkpoint,
                checkpoint_key,
                papers_collected=papers_collected,
                is_complete=True,
            )
            logger.info(f"Completed ACL {venue}: {papers_collected} papers")

        except Exception as e:
            logger.error(f"Error collecting ACL {venue}: {e}")
            self.checkpoint_manager.update_venue(
                checkpoint,
                checkpoint_key,
                papers_collected=papers_collected,
                error=str(e),
            )
            raise

    def _is_workshop_file(self, filename: str) -> bool:
        """Check if a file is a workshop file (not a main venue).

        Args:
            filename: XML filename to check.

        Returns:
            True if this is a workshop file.
        """
        filename_lower = filename.lower()

        # Skip non-year-prefixed files (legacy format)
        if not re.match(r"^\d{4}\.", filename_lower):
            return False

        # Check if it matches any main venue prefix
        for prefix in MAIN_VENUE_PREFIXES:
            if f".{prefix}." in filename_lower or filename_lower.endswith(f".{prefix}.xml"):
                return False

        # It's a workshop file if it has year prefix but doesn't match main venues
        return True

    async def collect_workshops(
        self,
        since_year: int = 2020,
        to_year: int | None = None,
        save_to_storage: bool = True,
        since_date: str | None = None,
        to_date: str | None = None,
        force: bool = False,
    ) -> AsyncIterator[list[RawPaper]]:
        """Collect papers from all ACL-affiliated workshops.

        Workshops are identified as XML files that don't match any main venue prefix.

        Args:
            since_year: Collect papers from this year onwards.
            to_year: Collect papers until this year (inclusive).
            save_to_storage: Whether to save papers to Qdrant.
            since_date: Start date in YYYY-MM-DD or YYYY-MM format.
            to_date: End date in YYYY-MM-DD or YYYY-MM format.
            force: If True, skip the is_complete check (for incremental runs).

        Yields:
            Batches of collected papers.
        """
        # Parse date constraints
        if since_date:
            since_year = int(since_date[:4])
            since_month = int(since_date[5:7]) if len(since_date) >= 7 else 1
        else:
            since_month = 1

        if to_date:
            to_year = int(to_date[:4])
            to_month = int(to_date[5:7]) if len(to_date) >= 7 else 12
        else:
            to_month = 12

        # Load checkpoint
        checkpoint = self.checkpoint_manager.load()
        checkpoint_key = "acl_workshops"

        # Check if already complete
        if not force and self.checkpoint_manager.is_venue_complete(checkpoint, checkpoint_key):
            logger.info("Workshops already complete, skipping")
            return

        logger.info(f"Collecting ACL workshops from {since_year}")

        # List all XML files
        all_files = await self.list_xml_files()

        # Filter to workshop files only
        workshop_files = []
        for filename in all_files:
            if not self._is_workshop_file(filename):
                continue

            # Extract year from filename
            year_match = re.search(r"^(\d{4})\.", filename)
            if year_match:
                file_year = int(year_match.group(1))
                if file_year >= since_year:
                    if to_year is None or file_year <= to_year:
                        workshop_files.append((filename, file_year))

        logger.info(f"Found {len(workshop_files)} workshop XML files")

        papers_collected = 0
        progress = checkpoint.get_venue_progress(checkpoint_key)
        if progress:
            papers_collected = progress.papers_collected

        processed_files: set[str] = set()
        if progress and progress.cursor:
            processed_files = set(progress.cursor.split(",")) if progress.cursor else set()

        # Workshop venue info (used for all workshops)
        workshop_info = {
            "full_name": "ACL Workshop",
            "tier": 2,  # Workshops are tier 2
        }

        try:
            for filename, file_year in workshop_files:
                if filename in processed_files:
                    continue

                logger.info(f"Processing workshop: {filename}")

                xml_content = await self.download_xml(filename)
                if not xml_content:
                    continue

                # Extract workshop name from filename (e.g., "2024.bionlp.xml" -> "bionlp")
                workshop_name = filename.replace(".xml", "").split(".", 1)[-1] if "." in filename else filename

                papers = self.parse_volume(xml_content, workshop_name, workshop_info)

                # Filter by year/month and deduplicate
                batch = []
                for paper in papers:
                    if not paper.year:
                        continue

                    # Get paper month from raw_data if available
                    paper_month = None
                    if paper.raw_data and paper.raw_data.get("month"):
                        month_str = paper.raw_data["month"]
                        month_map = {
                            "january": 1, "february": 2, "march": 3, "april": 4,
                            "may": 5, "june": 6, "july": 7, "august": 8,
                            "september": 9, "october": 10, "november": 11, "december": 12
                        }
                        paper_month = month_map.get(month_str.lower().split("-")[0], None)

                    # Year filtering
                    if paper.year < since_year:
                        continue
                    if to_year and paper.year > to_year:
                        continue

                    # Month filtering
                    if paper_month:
                        if paper.year == since_year and paper_month < since_month:
                            continue
                        if to_year and paper.year == to_year and paper_month > to_month:
                            continue

                    # Check for duplicates
                    dup_result = self.deduplicator.check_and_add(paper)
                    if not dup_result.is_duplicate:
                        batch.append(paper)

                if batch:
                    if save_to_storage:
                        self.storage.upsert_papers(batch)

                    papers_collected += len(batch)
                    checkpoint.total_papers += len(batch)

                    yield batch

                # Update checkpoint
                processed_files.add(filename)
                self.checkpoint_manager.update_venue(
                    checkpoint,
                    checkpoint_key,
                    cursor=",".join(sorted(processed_files)),
                    papers_collected=papers_collected,
                )

                # Small delay to be nice to GitHub
                await asyncio.sleep(0.5)

            # Mark workshops as complete
            self.checkpoint_manager.update_venue(
                checkpoint,
                checkpoint_key,
                papers_collected=papers_collected,
                is_complete=True,
            )
            logger.info(f"Completed ACL workshops: {papers_collected} papers")

        except Exception as e:
            logger.error(f"Error collecting ACL workshops: {e}")
            self.checkpoint_manager.update_venue(
                checkpoint,
                checkpoint_key,
                papers_collected=papers_collected,
                error=str(e),
            )
            raise

    async def collect_all(
        self,
        since_year: int = 2020,
        to_year: int | None = None,
        include_workshops: bool = True,
    ) -> int:
        """Collect papers from all ACL venues.

        Args:
            since_year: Collect papers from this year onwards.
            to_year: Collect papers until this year (inclusive).
            include_workshops: Whether to include workshop papers.

        Returns:
            Total number of papers collected.
        """
        # Ensure storage collection exists
        self.storage.ensure_collection()

        logger.info(f"Collecting from {len(ACL_VENUES)} ACL venues")

        total = 0
        for venue in ACL_VENUES:
            async for batch in self.collect_venue(venue, since_year, to_year):
                total += len(batch)

        # Collect workshops if enabled
        if include_workshops:
            logger.info("Collecting ACL workshops")
            async for batch in self.collect_workshops(since_year, to_year):
                total += len(batch)

        logger.info(f"ACL collection complete: {total} papers")
        return total


def get_acl_venues(include_workshops: bool = False) -> list[str]:
    """Get list of available ACL venues.

    Args:
        include_workshops: If True, includes "workshops" as a pseudo-venue.

    Returns:
        List of venue names.
    """
    venues = list(ACL_VENUES.keys())
    if include_workshops:
        venues.append("workshops")
    return venues


def get_acl_venue_info(venue: str) -> dict[str, Any] | None:
    """Get information about an ACL venue."""
    if venue.lower() == "workshops":
        return {
            "prefixes": [],
            "full_name": "ACL-Affiliated Workshops",
            "tier": 2,
        }
    return ACL_VENUES.get(venue.lower())
