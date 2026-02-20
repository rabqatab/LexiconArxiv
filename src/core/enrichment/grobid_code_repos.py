"""Code repository extraction from paper PDFs via GROBID full-text.

Uses GROBID's processFulltextDocument endpoint to extract TEI-XML,
then finds and classifies GitHub URLs in the paper text.

Classification heuristics:
- Blocklist filters out well-known library repos (pytorch, tensorflow, etc.)
- Section-based scoring: abstract/conclusion boost, related-work/bibliography penalty
- Context-based scoring: phrases like "our code" boost, "based on" penalize
- URLs with score >= 2 are marked is_official=True
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from src.core.enrichment.code_repos import CodeRepoEnricher, _normalize_title
from src.core.storage import QdrantStorage

logger = logging.getLogger(__name__)

# GROBID server URL (default Docker port)
GROBID_DEFAULT_URL = "http://localhost:8070"

# TEI XML namespace
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

# =============================================================================
# GitHub URL regex and blocklist
# =============================================================================

GITHUB_URL_RE = re.compile(
    r"https?://github\.com/([a-zA-Z0-9\-_.]+)/([a-zA-Z0-9\-_.]+)",
)

GITHUB_BLOCKLIST = frozenset({
    # Deep learning frameworks
    "pytorch/pytorch",
    "tensorflow/tensorflow",
    "keras-team/keras",
    "google/jax",
    "apache/mxnet",
    "microsoft/cntk",
    "PaddlePaddle/Paddle",
    "Theano/Theano",
    # NLP libraries
    "huggingface/transformers",
    "huggingface/datasets",
    "huggingface/tokenizers",
    "huggingface/accelerate",
    "facebookresearch/fairseq",
    "google-research/bert",
    "allenai/allennlp",
    "explosion/spaCy",
    "nltk/nltk",
    "stanfordnlp/stanza",
    "flairNLP/flair",
    "RasaHQ/rasa",
    # ML libraries
    "scikit-learn/scikit-learn",
    "dmlc/xgboost",
    "microsoft/LightGBM",
    "catboost/catboost",
    # Computer vision
    "facebookresearch/detectron2",
    "open-mmlab/mmdetection",
    "open-mmlab/mmcv",
    "ultralytics/yolov5",
    "ultralytics/ultralytics",
    # Training / infrastructure
    "microsoft/DeepSpeed",
    "NVIDIA/apex",
    "Lightning-AI/lightning",
    "wandb/wandb",
    "ray-project/ray",
    "horovod/horovod",
    # Utilities
    "numpy/numpy",
    "pandas-dev/pandas",
    "scipy/scipy",
    "matplotlib/matplotlib",
    # Benchmarks / datasets
    "google-research/google-research",
    "facebookresearch/ParlAI",
})

# Phrases indicating the paper's own code
OWN_CODE_PHRASES = [
    "our code",
    "our implementation",
    "our source code",
    "source code is available",
    "source code available",
    "code is available",
    "code available at",
    "code can be found",
    "code is released",
    "we release",
    "we open-source",
    "we open source",
    "publicly available at",
    "released at",
    "implementation is available",
    "implementation available",
    "available at github",
]

# Phrases indicating third-party code references
NEGATIVE_PHRASES = [
    "based on",
    "built on",
    "we use",
    "we utilize",
    "we adopt",
    "we follow",
    "provided by",
    "implemented in",
    "available in",
    "originally from",
    "proposed by",
    "introduced by",
    "from the",
    "codebase of",
]


@dataclass
class GrobidCodeRepoProgress:
    """Track GROBID code repo extraction progress."""

    total_to_process: int = 0
    processed: int = 0
    enriched: int = 0
    download_failed: int = 0
    grobid_failed: int = 0
    no_urls_found: int = 0
    all_blocklisted: int = 0
    errors: int = 0
    last_offset: str | None = None
    processed_point_ids: set[str] = field(default_factory=set)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_updated: str | None = None


class GrobidCodeRepoExtractor:
    """Extract GitHub code repo URLs from paper PDFs via GROBID full-text."""

    def __init__(
        self,
        storage: QdrantStorage | None = None,
        grobid_url: str | None = None,
        checkpoint_dir: Path | str | None = None,
        batch_size: int = 20,
        max_concurrent: int = 20,
        download_timeout: float = 60.0,
        grobid_timeout: float = 180.0,
    ):
        self.storage = storage or QdrantStorage()
        self.grobid_url = grobid_url or GROBID_DEFAULT_URL
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.download_timeout = download_timeout
        self.grobid_timeout = grobid_timeout

        self.checkpoint_dir = Path(checkpoint_dir or "data/core/checkpoints")
        self._checkpoint_file = self.checkpoint_dir / "grobid_code_repo_extraction.json"
        self._client: httpx.AsyncClient | None = None
        self._semaphore: asyncio.Semaphore | None = None

    async def __aenter__(self) -> "GrobidCodeRepoExtractor":
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

        # Check GROBID availability
        try:
            response = await self._client.get(f"{self.grobid_url}/api/isalive")
            if response.status_code == 200:
                logger.info(f"GROBID server available at {self.grobid_url}")
            else:
                logger.warning(f"GROBID server returned {response.status_code}")
        except Exception as e:
            logger.error(f"Cannot connect to GROBID at {self.grobid_url}: {e}")
            logger.error(
                "Start GROBID with: docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0"
            )

        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    # =========================================================================
    # PDF download (same pattern as PDFReferenceExtractor)
    # =========================================================================

    async def download_pdf(self, url: str, max_retries: int = 3) -> bytes | None:
        """Download PDF from URL with retry logic."""
        if not self._client:
            raise RuntimeError("Client not initialized.")

        for attempt in range(max_retries):
            try:
                response = await self._client.get(
                    url,
                    timeout=self.download_timeout,
                    headers={"User-Agent": "LexiconArxiv/1.0 (Code repo enrichment)"},
                )
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if "pdf" not in content_type.lower() and not url.endswith(".pdf"):
                    logger.warning(f"Not a PDF: {url} (content-type: {content_type})")
                    return None

                return response.content

            except httpx.TimeoutException:
                logger.warning(
                    f"Timeout downloading {url} (attempt {attempt + 1}/{max_retries})"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                return None
            except (httpx.RemoteProtocolError, httpx.ConnectError) as e:
                logger.warning(
                    f"Network error downloading {url} "
                    f"(attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                return None
            except Exception as e:
                logger.warning(f"Error downloading {url}: {e}")
                return None

        return None

    # =========================================================================
    # GROBID full-text extraction
    # =========================================================================

    async def extract_fulltext_from_pdf(self, pdf_content: bytes) -> str | None:
        """Extract full-text TEI-XML from PDF via GROBID processFulltextDocument.

        Returns:
            TEI-XML string or None on failure.
        """
        if not self._client:
            raise RuntimeError("Client not initialized.")

        try:
            files = {"input": ("paper.pdf", pdf_content, "application/pdf")}
            response = await self._client.post(
                f"{self.grobid_url}/api/processFulltextDocument",
                files=files,
                timeout=self.grobid_timeout,
            )

            if response.status_code != 200:
                logger.warning(f"GROBID returned {response.status_code}")
                return None

            return response.text

        except httpx.TimeoutException:
            logger.warning("GROBID full-text processing timeout")
            return None
        except Exception as e:
            logger.warning(f"GROBID error: {e}")
            return None

    # =========================================================================
    # GitHub URL extraction + classification from TEI-XML
    # =========================================================================

    @staticmethod
    def _normalize_github_url(url: str) -> tuple[str, str] | None:
        """Normalize a GitHub URL to github.com/owner/repo.

        Returns:
            (clean_url, owner_repo) or None if not a valid GitHub repo URL.
        """
        m = GITHUB_URL_RE.search(url)
        if not m:
            return None

        owner = m.group(1)
        repo = m.group(2)
        # Strip common extensions
        repo = re.sub(r"\.(git|zip|tar\.gz)$", "", repo)
        owner_repo = f"{owner}/{repo}"
        clean_url = f"https://github.com/{owner_repo}"
        return clean_url, owner_repo

    @staticmethod
    def _classify_section(head_text: str) -> str:
        """Classify a section heading into a category.

        Returns one of: abstract, introduction, method, results,
                        conclusion, related_work, references, other
        """
        head_lower = head_text.lower().strip()

        if not head_lower:
            return "other"
        if "abstract" in head_lower:
            return "abstract"
        if "introduction" in head_lower:
            return "introduction"
        if any(
            w in head_lower
            for w in [
                "method",
                "approach",
                "model",
                "framework",
                "architecture",
                "system",
                "proposed",
            ]
        ):
            return "method"
        if any(
            w in head_lower
            for w in ["experiment", "result", "evaluation", "analysis"]
        ):
            return "results"
        if any(
            w in head_lower for w in ["conclusion", "summary", "future work"]
        ):
            return "conclusion"
        if any(
            w in head_lower
            for w in ["related work", "related research", "prior work", "background"]
        ):
            return "related_work"
        if any(
            w in head_lower for w in ["reference", "bibliography", "citation"]
        ):
            return "references"
        return "other"

    def extract_github_urls_from_tei(self, tei_xml: str) -> list[dict]:
        """Extract and classify GitHub URLs from TEI-XML full-text.

        Steps:
        1. Parse XML, find URLs in <ref type="url"> and via regex on body text
        2. Normalize to github.com/owner/repo
        3. Deduplicate by owner/repo
        4. Filter against blocklist
        5. Score each URL based on section and context
        6. Classify: is_official = True if score >= 2

        Returns:
            List of repo dicts sorted by score descending.
        """
        try:
            root = ET.fromstring(tei_xml)
        except ET.ParseError as e:
            logger.warning(f"XML parse error: {e}")
            return []

        # Collect (url, section, surrounding_text) tuples
        url_contexts: list[tuple[str, str, str]] = []

        # Strategy 1: Find <ref type="url"> elements in the body
        body = root.find(".//tei:body", TEI_NS)
        if body is not None:
            for div in body.findall(".//tei:div", TEI_NS):
                head_el = div.find("tei:head", TEI_NS)
                head_text = (
                    head_el.text if head_el is not None and head_el.text else ""
                )
                section = self._classify_section(head_text)

                # Get full div text for context matching
                div_text = ET.tostring(div, encoding="unicode", method="text")

                # Find <ref> elements with GitHub URLs
                for ref in div.findall(".//tei:ref", TEI_NS):
                    target = ref.get("target", "")
                    if "github.com" in target:
                        # Get surrounding context (text of the parent paragraph)
                        parent_p = ref.find("..")
                        context = ""
                        if parent_p is not None:
                            context = ET.tostring(
                                parent_p, encoding="unicode", method="text"
                            )
                        url_contexts.append((target, section, context))

                # Strategy 2: Regex scan for GitHub URLs in the div text
                for m in GITHUB_URL_RE.finditer(div_text):
                    url = m.group(0)
                    # Get surrounding ±200 chars for context
                    start = max(0, m.start() - 200)
                    end = min(len(div_text), m.end() + 200)
                    context = div_text[start:end]
                    url_contexts.append((url, section, context))

        # Also check the abstract
        abstract = root.find(".//tei:profileDesc/tei:abstract", TEI_NS)
        if abstract is not None:
            abs_text = ET.tostring(abstract, encoding="unicode", method="text")
            for m in GITHUB_URL_RE.finditer(abs_text):
                url = m.group(0)
                start = max(0, m.start() - 200)
                end = min(len(abs_text), m.end() + 200)
                context = abs_text[start:end]
                url_contexts.append((url, "abstract", context))

        if not url_contexts:
            return []

        # Normalize, deduplicate, and aggregate contexts per repo
        repo_data: dict[str, dict] = {}  # owner_repo -> {url, sections, contexts}
        for raw_url, section, context in url_contexts:
            normalized = self._normalize_github_url(raw_url)
            if not normalized:
                continue
            clean_url, owner_repo = normalized

            if owner_repo not in repo_data:
                repo_data[owner_repo] = {
                    "url": clean_url,
                    "sections": [],
                    "contexts": [],
                }
            repo_data[owner_repo]["sections"].append(section)
            repo_data[owner_repo]["contexts"].append(context)

        # Filter blocklist
        for blocked in list(repo_data.keys()):
            if blocked.lower() in {b.lower() for b in GITHUB_BLOCKLIST}:
                del repo_data[blocked]

        if not repo_data:
            return []

        # Score each URL
        results = []
        for owner_repo, data in repo_data.items():
            score = 0

            # Section scoring
            for section in data["sections"]:
                if section in ("abstract", "conclusion"):
                    score += 2
                elif section in ("introduction", "method"):
                    score += 1
                elif section == "related_work":
                    score -= 1
                elif section == "references":
                    score -= 2

            # Context scoring
            all_context = " ".join(data["contexts"]).lower()
            for phrase in OWN_CODE_PHRASES:
                if phrase in all_context:
                    score += 3
                    break  # Only count once

            for phrase in NEGATIVE_PHRASES:
                if phrase in all_context:
                    score -= 1
                    break  # Only count once

            is_official = score >= 2

            results.append({
                "url": data["url"],
                "is_official": is_official,
                "framework": None,
                "stars": None,
                "source": "grobid_fulltext",
                "_score": score,  # Internal, stripped before storage
            })

        # Sort by score descending
        results.sort(key=lambda r: r["_score"], reverse=True)

        # Strip internal score field
        for r in results:
            del r["_score"]

        return results

    # =========================================================================
    # Processing pipeline
    # =========================================================================

    async def _process_one(
        self, point_id: str, payload: dict
    ) -> tuple[str, list[dict] | None, str]:
        """Process a single paper: download PDF, extract full-text, find GitHub URLs.

        Returns:
            (point_id, repos_or_none, status_string)
        """
        pdf_url = payload.get("pdf_url")
        if not pdf_url:
            return point_id, None, "no_pdf_url"

        async with self._semaphore:
            # Download PDF
            pdf_content = await self.download_pdf(pdf_url)
            if not pdf_content:
                return point_id, None, "download_failed"

            # Extract full-text via GROBID
            tei_xml = await self.extract_fulltext_from_pdf(pdf_content)
            if not tei_xml:
                return point_id, None, "grobid_failed"

            # Extract and classify GitHub URLs
            repos = self.extract_github_urls_from_tei(tei_xml)
            if not repos:
                return point_id, None, "no_urls_found"

            return point_id, repos, "ok"

    async def _process_batch(
        self,
        papers: list[tuple[str, dict]],
        progress: GrobidCodeRepoProgress,
    ) -> int:
        """Process a batch of papers."""
        to_process = [
            (pid, payload)
            for pid, payload in papers
            if pid not in progress.processed_point_ids
        ]

        if not to_process:
            return 0

        # Launch concurrent processing
        tasks = [
            self._process_one(pid, payload) for pid, payload in to_process
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched = 0
        updates: list[tuple[str, list[dict], str | None]] = []

        for i, result in enumerate(results):
            point_id = to_process[i][0]
            progress.processed += 1
            progress.processed_point_ids.add(point_id)

            if isinstance(result, Exception):
                logger.warning(f"Error processing {point_id}: {result}")
                progress.errors += 1
                continue

            pid, repos, status = result

            if status == "download_failed":
                progress.download_failed += 1
            elif status == "grobid_failed":
                progress.grobid_failed += 1
            elif status == "no_urls_found":
                progress.no_urls_found += 1
            elif status == "ok" and repos:
                best_url = CodeRepoEnricher._select_best_url(repos)
                updates.append((pid, repos, best_url))
                progress.enriched += 1
                enriched += 1

        # Write all updates to Qdrant
        if updates:
            self.storage.batch_update_code_repos(updates)

        return enriched

    async def enrich_code_repos_via_grobid(
        self,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> GrobidCodeRepoProgress:
        """Enrich papers with code repository URLs from GROBID full-text extraction.

        Args:
            dry_run: Only count eligible papers without processing.
            limit: Maximum papers to process.

        Returns:
            GrobidCodeRepoProgress with statistics.
        """
        progress = self._load_checkpoint()
        offset = progress.last_offset

        logger.info("Starting GROBID code repository extraction...")

        while True:
            papers, next_offset = self.storage.get_papers_missing_code_repos_with_pdf(
                limit=self.batch_size,
                offset=offset,
            )

            if not papers:
                break

            if dry_run:
                progress.total_to_process += len(papers)
                logger.info(f"Found {len(papers)} papers with PDF URLs (dry run)")
            else:
                enriched = await self._process_batch(papers, progress)
                logger.info(
                    f"Batch: {enriched}/{len(papers)} enriched | "
                    f"Total: {progress.enriched} enriched, "
                    f"{progress.download_failed} download failed, "
                    f"{progress.grobid_failed} GROBID failed, "
                    f"{progress.no_urls_found} no URLs"
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
            f"GROBID code repo extraction complete: {progress.enriched} enriched, "
            f"{progress.download_failed} download failed, "
            f"{progress.grobid_failed} GROBID failed, "
            f"{progress.no_urls_found} no URLs, "
            f"{progress.errors} errors"
        )
        return progress

    # =========================================================================
    # Checkpoint
    # =========================================================================

    def _load_checkpoint(self) -> GrobidCodeRepoProgress:
        if self._checkpoint_file.exists():
            with open(self._checkpoint_file) as f:
                data = json.load(f)
            progress = GrobidCodeRepoProgress(
                total_to_process=data.get("total_to_process", 0),
                processed=data.get("processed", 0),
                enriched=data.get("enriched", 0),
                download_failed=data.get("download_failed", 0),
                grobid_failed=data.get("grobid_failed", 0),
                no_urls_found=data.get("no_urls_found", 0),
                all_blocklisted=data.get("all_blocklisted", 0),
                errors=data.get("errors", 0),
                last_offset=data.get("last_offset"),
                started_at=data.get(
                    "started_at", datetime.now(timezone.utc).isoformat()
                ),
                last_updated=data.get("last_updated"),
            )
            progress.processed_point_ids = set(
                data.get("processed_point_ids", [])
            )
            return progress
        return GrobidCodeRepoProgress()

    def _save_checkpoint(self, progress: GrobidCodeRepoProgress) -> None:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "total_to_process": progress.total_to_process,
            "processed": progress.processed,
            "enriched": progress.enriched,
            "download_failed": progress.download_failed,
            "grobid_failed": progress.grobid_failed,
            "no_urls_found": progress.no_urls_found,
            "all_blocklisted": progress.all_blocklisted,
            "errors": progress.errors,
            "last_offset": progress.last_offset,
            "processed_point_ids": list(progress.processed_point_ids),
            "started_at": progress.started_at,
            "last_updated": progress.last_updated,
        }
        with open(self._checkpoint_file, "w") as f:
            json.dump(data, f, indent=2)

    def clear_checkpoint(self) -> None:
        if self._checkpoint_file.exists():
            self._checkpoint_file.unlink()
            logger.info("GROBID code repo extraction checkpoint cleared")
