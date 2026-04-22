"""Backfill pdf_url on ACM papers (DOI prefix 10.1145/) that lack one.

Many ACM papers were collected via DBLP (metadata-only) and never had a
pdf_url set. For these, the canonical URL is deterministic:

    https://dl.acm.org/doi/pdf/{doi}

Setting this field lets the standard PDF enrichment pipeline
(`enrich-5-refs-by-pdf-via-grobid`) pick them up, where the new routing
in `src/core/enrichment/pdf.py` hands them off to the stealth browser.

This script is idempotent:
  - Only touches points where pdf_url is missing (IsEmpty / IsNull).
  - Does NOT overwrite existing pdf_url values.

Usage:
    uv run python scripts/enrichment/backfill_acm_pdf_urls.py --dry-run
    uv run python scripts/enrichment/backfill_acm_pdf_urls.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running as a standalone script: `uv run python scripts/enrichment/...`
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qdrant_client.http import models as q  # noqa: E402

from src.core.storage import QdrantStorage  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("backfill_acm_pdf_urls")

ACM_PDF_URL_FMT = "https://dl.acm.org/doi/pdf/{doi}"


def build_filter() -> q.Filter:
    """Real papers with ACM DOI and no pdf_url."""
    return q.Filter(
        must=[
            q.FieldCondition(key="doi", match=q.MatchText(text="10.1145/")),
            q.IsEmptyCondition(is_empty=q.PayloadField(key="pdf_url")),
        ],
        must_not=[q.FieldCondition(key="is_stub", match=q.MatchValue(value=True))],
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Only count, do not write")
    ap.add_argument("--batch-size", type=int, default=500, help="Scroll page size")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N updates (debug)")
    args = ap.parse_args()

    storage = QdrantStorage()
    flt = build_filter()

    total = storage.client.count(
        collection_name=storage.collection_name, count_filter=flt, exact=True
    ).count
    logger.info(f"ACM papers missing pdf_url: {total:,}")

    if args.dry_run:
        # Sample 3 to show what would happen
        pts, _ = storage.client.scroll(
            collection_name=storage.collection_name,
            scroll_filter=flt,
            limit=3,
            with_payload=["doi", "venue"],
        )
        for p in pts:
            doi = p.payload.get("doi")
            logger.info(
                f"[would set] id={p.id} doi={doi} venue={p.payload.get('venue', '?')}"
                f" -> {ACM_PDF_URL_FMT.format(doi=doi)}"
            )
        logger.info("Dry run — no changes written.")
        return

    updated = 0
    offset = None
    while True:
        pts, next_offset = storage.client.scroll(
            collection_name=storage.collection_name,
            scroll_filter=flt,
            limit=args.batch_size,
            with_payload=["doi"],
            offset=offset,
        )
        if not pts:
            break

        # Update one-by-one since each synthesized URL is per-paper
        for p in pts:
            doi = (p.payload or {}).get("doi")
            if not doi or not str(doi).startswith("10.1145/"):
                continue
            storage.client.set_payload(
                collection_name=storage.collection_name,
                payload={"pdf_url": ACM_PDF_URL_FMT.format(doi=doi)},
                points=[p.id],
                wait=False,  # fire and forget; Qdrant batches durably
            )
            updated += 1
            if args.limit and updated >= args.limit:
                logger.info(f"Reached --limit={args.limit}, stopping")
                logger.info(f"Updated {updated:,} ACM points with synthetic pdf_url.")
                return

        if len(pts) % 2500 == 0 or len(pts) < args.batch_size:
            logger.info(f"Updated so far: {updated:,}")
        if next_offset is None:
            break
        offset = next_offset

    logger.info(f"Done. Updated {updated:,} ACM points with synthetic pdf_url.")


if __name__ == "__main__":
    main()
