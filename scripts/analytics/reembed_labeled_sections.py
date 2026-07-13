"""Wave 4c Phase 4b — re-embed labeled papers to generate section vectors.

The Phase 4 labeling wrote abstract_structure to ~113K 2020+ papers, but those
papers already had a (stale) structured-abstract vector, so the normal
embed-papers path (skip_embedded keys on structured-abstract) skips them and
they never get the 7 section-* vectors. Search multi-vector fusion collapses
without them. This targets exactly the labeled-but-missing-sections set and
regenerates all 9 dense vectors + BM25 via the real embedder.

Forward offset pagination over a stable-enough filter: as a page is embedded
it gains section-method and drops out of the filter, but the cursor has
already moved past it — one pass, no double-work, resumable (re-run continues
from what's still missing).

Usage: uv run python -m scripts.analytics.reembed_labeled_sections [--limit N] [--year-min 2020]
"""
import argparse
import asyncio
import time

from qdrant_client.http import models as q

from src.core.embedding.embedder import PaperEmbedder
from src.core.storage import QdrantStorage

PAGE = 96  # papers per scroll page / embed batch


def target_filter(year_min: int) -> q.Filter:
    return q.Filter(
        must=[
            q.FieldCondition(key="abstract_structure_source", match=q.MatchValue(value="vllm")),
            q.FieldCondition(key="year", range=q.Range(gte=year_min)),
        ],
        must_not=[
            q.FieldCondition(key="is_stub", match=q.MatchValue(value=True)),
            q.HasVectorCondition(has_vector="section-method"),
        ],
    )


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--year-min", type=int, default=2020)
    args = ap.parse_args()

    s = QdrantStorage()
    flt = target_filter(args.year_min)
    total = s.client.count(s.collection_name, exact=True, count_filter=flt).count
    cap = min(total, args.limit) if args.limit else total
    print(f"target (vllm-labeled >={args.year_min}, no section vectors): {total:,}; processing {cap:,}", flush=True)

    done = 0
    t0 = time.time()
    async with PaperEmbedder(max_concurrent=4) as embedder:
        offset = None
        while done < cap:
            pts, offset = s.client.scroll(
                s.collection_name, scroll_filter=flt, limit=PAGE, offset=offset,
                with_payload=["title", "abstract", "abstract_structure"], with_vectors=False,
            )
            if not pts:
                break
            papers = [(str(p.id), p.payload or {}) for p in pts]
            n = await embedder.embed_and_upsert_batch(papers, s, embed_batch_size=64)
            done += len(papers)
            rate = done / max(time.time() - t0, 1)
            eta = (cap - done) / max(rate, 1) / 60
            print(f"{done:,}/{cap:,}  (+{n} embedded, {rate:.0f} papers/s, eta {eta:.0f}m)", flush=True)
            if offset is None:
                break
    print(f"DONE {done:,} in {(time.time()-t0)/60:.1f}m", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
