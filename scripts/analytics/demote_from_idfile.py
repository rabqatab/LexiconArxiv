"""Wave 4c Phase 3 (Option B) — demote by id-file, no filter evaluation.

Reads snapshots/2026-07-06-cs-cleanup/delete-ids.jsonl (dumped in Phase 1)
and demotes each point to a stub in id-chunks. Filter-based ops re-evaluate
the expensive provenance+primary_topic filter over 6.2M points on every call
and time out; operating on explicit point-id lists touches only named points.

Idempotent: re-running over already-demoted ids just re-applies no-op strips.
Resumable: pass --skip N to skip the first N ids.

Usage:
  uv run python -m scripts.analytics.demote_from_idfile [--skip N] [--chunk 20000]
"""
import argparse
import json
import time

from qdrant_client import models

from src.core.storage import QdrantStorage
from src.core.storage._retry import retry_qdrant

ID_FILE = "snapshots/2026-07-06-cs-cleanup/delete-ids.jsonl"

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


def demote_ids(s, ids):
    sel = models.PointIdsList(points=ids)
    retry_qdrant(lambda: s.client.delete_vectors(
        s.collection_name, vectors=DENSE_VECTORS + SPARSE_VECTORS, points=sel, wait=True),
        label="delete_vectors")
    retry_qdrant(lambda: s.client.delete_payload(
        s.collection_name, keys=STRIP_KEYS, points=sel, wait=True),
        label="delete_payload")
    retry_qdrant(lambda: s.client.set_payload(
        s.collection_name,
        payload={"is_stub": True, "demoted_from_real": True, "demoted_reason": "wave4c-noncs"},
        points=sel, wait=True),
        label="set_payload_stub")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--chunk", type=int, default=20000)
    args = ap.parse_args()
    s = QdrantStorage()

    ids = []
    with open(ID_FILE) as f:
        for line in f:
            ids.append(json.loads(line)["point_id"])
    total = len(ids)
    print(f"loaded {total:,} ids; skipping {args.skip:,}", flush=True)

    t0 = time.time()
    done = args.skip
    for i in range(args.skip, total, args.chunk):
        demote_ids(s, ids[i:i + args.chunk])
        done = min(i + args.chunk, total)
        rate = (done - args.skip) / max(time.time() - t0, 1)
        eta = (total - done) / max(rate, 1)
        print(f"{done:,}/{total:,}  ({rate:.0f} ids/s, eta {eta/60:.0f}m)", flush=True)
    print(f"DONE {done:,} in {(time.time()-t0)/60:.1f}m", flush=True)


if __name__ == "__main__":
    main()
