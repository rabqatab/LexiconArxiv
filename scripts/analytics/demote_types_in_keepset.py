"""A1(a) — demote non-paper `type` works INSIDE the CS keep-set to stubs.

Wave 4c removed the cross-domain junk by topic; this removes the non-paper
*types* that remain on-topic (a `book` in CS, an `editorial` in a CS journal).
Same demotion machinery as demote_noncs_to_stub.py (strip heavy payload +
vectors, set is_stub, PRESERVE identity + cited_by so re-promotion stays
possible), but the filter is inverted: keep-topic KEPT, junk type MATCHED.

Provenance-scoped to P2/P3 injections (injected_from_snapshot OR
promoted_from_stub), same as Wave 4c — crawler venues (arXiv/ACL/DBLP/AAAI/
OpenReview) don't produce books/editorials, so a crawler paper mistyped by
OpenAlex is protected. article / preprint / no-type are never touched.

Policy (user decision 2026-07-17, "junk only"): demote the 9 clear non-paper
types; KEEP review (surveys), book-chapter, dissertation, report, dataset,
letter.

Usage:
  uv run python -m scripts.analytics.demote_types_in_keepset --dry-run
  uv run python -m scripts.analytics.demote_types_in_keepset --type book
  uv run python -m scripts.analytics.demote_types_in_keepset            # all 9 types
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

# Reuse the Wave 4c strip/vector lists verbatim (same demotion contract).
DENSE_VECTORS = [
    "abstract-qwen3-8b", "structured-abstract", "section-approach",
    "section-background", "section-contribution", "section-domain",
    "section-method", "section-result", "section-task",
]
SPARSE_VECTORS = ["bm25"]
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

DEMOTE_TYPES = [
    "book", "paratext", "other", "editorial", "reference-entry",
    "erratum", "standard", "retraction", "peer-review",
]

CHUNK = 20000


def type_filter(t):
    """keep-topic (KEPT) AND type==t AND P2/P3 provenance AND not-already-stub."""
    return models.Filter(
        must=[
            models.Filter(should=[
                models.FieldCondition(key="injected_from_snapshot", match=models.MatchValue(value=True)),
                models.FieldCondition(key="promoted_from_stub", match=models.MatchValue(value=True)),
            ]),
            models.Filter(should=[
                models.FieldCondition(key=FIELD, match=models.MatchAny(any=sorted(KEEP_FIELDS))),
                models.FieldCondition(key=SUBFIELD, match=models.MatchAny(any=sorted(KEEP_SUBFIELDS))),
            ]),
            models.FieldCondition(key="type", match=models.MatchValue(value=t)),
        ],
        must_not=[_STUB],
    )


def count(s, flt):
    return s.client.count(s.collection_name, exact=True, count_filter=flt).count


def demote_type(s, t, dry_run):
    flt = type_filter(t)
    n = count(s, flt)
    print(f"[{t}] {n:,} points", flush=True)
    if dry_run or n == 0:
        return n
    done = 0
    while True:
        pts, _ = retry_qdrant(
            lambda: s.client.scroll(s.collection_name, scroll_filter=flt,
                                    limit=CHUNK, with_payload=False, with_vectors=False),
            label=f"scroll({t})")
        if not pts:
            break
        sel = models.PointIdsList(points=[p.id for p in pts])
        retry_qdrant(lambda: s.client.delete_vectors(
            s.collection_name, vectors=DENSE_VECTORS + SPARSE_VECTORS, points=sel, wait=True),
            label=f"delete_vectors({t})")
        retry_qdrant(lambda: s.client.delete_payload(
            s.collection_name, keys=STRIP_KEYS, points=sel, wait=True),
            label=f"delete_payload({t})")
        retry_qdrant(lambda: s.client.set_payload(
            s.collection_name,
            payload={"is_stub": True, "demoted_from_real": True,
                     "demoted_reason": f"a1a-nonpaper-type:{t}"},
            points=sel, wait=True),
            label=f"set_payload_stub({t})")
        done += len(pts)
        print(f"[{t}] {done:,}/{n:,}", flush=True)
    print(f"[{t}] done ({done:,})", flush=True)
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--type", help="only this type (e.g. book)")
    args = ap.parse_args()
    s = QdrantStorage()

    types = DEMOTE_TYPES if not args.type else [args.type]
    if args.type and args.type not in DEMOTE_TYPES:
        raise SystemExit(f"{args.type} not in demote set: {DEMOTE_TYPES}")

    t0 = time.time()
    total = sum(demote_type(s, t, args.dry_run) for t in types)
    print(f"\n{'DRY-RUN ' if args.dry_run else ''}TOTAL: {total:,} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
