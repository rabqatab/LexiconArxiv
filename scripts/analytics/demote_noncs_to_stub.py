"""Wave 4c Phase 3 (Option B): demote non-CS P2/P3 papers to stubs.

Strips heavy payload + vectors and sets is_stub=True on the delete-set defined
in docs/plans/2026-07-06-corpus-cs-cleanup.md, but PRESERVES identity +
citation-graph edges (cited_by) so "AI paper X cites Nature paper Y" survives
and any paper can be re-promoted later. Filter-based ops, one year bucket at a
time for observability.

Usage:
  uv run python -m scripts.analytics.demote_noncs_to_stub --dry-run
  uv run python -m scripts.analytics.demote_noncs_to_stub --bucket 2025-2026
  uv run python -m scripts.analytics.demote_noncs_to_stub            # all buckets
"""
import argparse
import time

from qdrant_client import models

from src.core.snapshot.topic_gate import KEEP_FIELDS, KEEP_SUBFIELDS
from src.core.storage import QdrantStorage
from src.core.storage._retry import retry_qdrant

FIELD = "primary_topic.field.display_name"
SUBFIELD = "primary_topic.subfield.display_name"
_STUB = models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))

DENSE_VECTORS = [
    "abstract-qwen3-8b", "structured-abstract", "section-approach",
    "section-background", "section-contribution", "section-domain",
    "section-method", "section-result", "section-task",
]
SPARSE_VECTORS = ["bm25"]

# Heavy / derived fields removed on demotion. Everything NOT listed is kept:
# title, doi, openalex_id, arxiv_id, year, authors, venue, cited_by,
# cited_by_count*, alternate_identifiers, identifier*, is_core, provenance flags.
STRIP_KEYS = [
    "abstract", "abstract_structure", "abstract_structure_source",
    "concepts", "mesh", "topics", "primary_topic",
    "referenced_works", "resolved_references", "counts_by_year",
    "funders", "orcid_map", "keywords", "keywords_source", "keywords_structured",
    "best_oa_pdf_url", "open_access", "fwci", "citation_normalized_percentile",
    "publication_date", "language", "type", "injection_path", "snapshot_filled_at",
    "graph_indexed", "pagerank", "hub_score", "authority_score", "community_id",
    "sustainable_development_goals", "enriched_at",
]

YEAR_BUCKETS = [
    ("pre-2009", None, 2009), ("2010-2014", 2010, 2014), ("2015-2019", 2015, 2019),
    ("2020-2024", 2020, 2024), ("2025-2026", 2025, 2026),
]


def base_filter(extra_must=None):
    return models.Filter(
        must=[models.Filter(should=[
            models.FieldCondition(key="injected_from_snapshot", match=models.MatchValue(value=True)),
            models.FieldCondition(key="promoted_from_stub", match=models.MatchValue(value=True)),
        ])] + (extra_must or []),
        must_not=[
            _STUB,
            models.FieldCondition(key=FIELD, match=models.MatchAny(any=sorted(KEEP_FIELDS))),
            models.FieldCondition(key=SUBFIELD, match=models.MatchAny(any=sorted(KEEP_SUBFIELDS))),
        ],
    )


def bucket_filter(lo, hi):
    rng = models.Range(gte=lo, lte=hi) if lo else models.Range(lte=hi)
    return base_filter([models.FieldCondition(key="year", range=rng)])


CHUNK = 20000


def count(s, flt):
    return s.client.count(s.collection_name, exact=True, count_filter=flt).count


def demote_bucket(s, name, flt, dry_run):
    n = count(s, flt)
    print(f"[{name}] {n:,} points", flush=True)
    if dry_run or n == 0:
        return n
    # id-based chunking: collect ids one scroll page at a time and operate on
    # explicit PointIdsList. A filter-wide delete_payload/delete_vectors
    # re-evaluates the (expensive provenance + primary_topic) filter over all
    # 6.2M points on every call and blows past the client timeout; id-list ops
    # touch only the named points. Scroll always re-reads from the top because
    # set_payload(is_stub) flips processed points out of `flt`.
    done = 0
    while True:
        pts, _ = retry_qdrant(
            lambda: s.client.scroll(s.collection_name, scroll_filter=flt,
                                    limit=CHUNK, with_payload=False, with_vectors=False),
            label=f"scroll({name})")
        if not pts:
            break
        ids = [p.id for p in pts]
        sel = models.PointIdsList(points=ids)
        retry_qdrant(lambda: s.client.delete_vectors(
            s.collection_name, vectors=DENSE_VECTORS + SPARSE_VECTORS, points=sel, wait=True),
            label=f"delete_vectors({name})")
        retry_qdrant(lambda: s.client.delete_payload(
            s.collection_name, keys=STRIP_KEYS, points=sel, wait=True),
            label=f"delete_payload({name})")
        retry_qdrant(lambda: s.client.set_payload(
            s.collection_name,
            payload={"is_stub": True, "demoted_from_real": True, "demoted_reason": "wave4c-noncs"},
            points=sel, wait=True),
            label=f"set_payload_stub({name})")
        done += len(ids)
        print(f"[{name}] {done:,}/{n:,}", flush=True)
    print(f"[{name}] done ({done:,})", flush=True)
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bucket", help="only this bucket (e.g. 2025-2026)")
    args = ap.parse_args()
    s = QdrantStorage()

    buckets = YEAR_BUCKETS if not args.bucket else [b for b in YEAR_BUCKETS if b[0] == args.bucket]
    if args.bucket and not buckets:
        raise SystemExit(f"unknown bucket {args.bucket}; choices: {[b[0] for b in YEAR_BUCKETS]}")

    t0 = time.time()
    total = 0
    for name, lo, hi in buckets:
        total += demote_bucket(s, name, bucket_filter(lo, hi), args.dry_run)
    # sweep the no-year remainder only on a full run
    if not args.bucket:
        total += demote_bucket(s, "no-year-remainder", base_filter(), args.dry_run)
    print(f"\n{'DRY-RUN ' if args.dry_run else ''}TOTAL: {total:,} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
