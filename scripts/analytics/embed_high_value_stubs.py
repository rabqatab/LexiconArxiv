"""B stub-vectors — embed high-value stubs so cited-but-absent papers surface.

Targets stubs that are cited by >= MIN_CITES core papers AND already have an
abstract (from prior enrichment), embeds their abstract into the
structured-abstract + full + BM25 vectors (no section vectors — stubs have no
abstract_structure), and flags searchable_stub=True so the main search's
stub-exclusion lets exactly these through (see service._build_filters).

Wave 4c pulled all stubs out of the HNSW graph for search speed; this re-adds
only the ~11K most-cited ones with abstracts, ~2% index growth.

Forward-offset pagination: once a stub is embedded + flagged it drops out of the
scroll filter (must_not searchable_stub), so one pass, resumable.

Usage: uv run python -m scripts.analytics.embed_high_value_stubs [--min-cites 5] [--limit N]
"""
import argparse
import asyncio
import time

from qdrant_client.http import models as q

from src.core.embedding.embedder import PaperEmbedder
from src.core.storage import QdrantStorage

PAGE = 96


def target_filter(min_cites: int) -> q.Filter:
    return q.Filter(
        must=[
            q.FieldCondition(key="is_stub", match=q.MatchValue(value=True)),
            q.FieldCondition(key="cited_by_count_internal", range=q.Range(gte=min_cites)),
        ],
        must_not=[
            q.IsEmptyCondition(is_empty=q.PayloadField(key="abstract")),
            q.FieldCondition(key="searchable_stub", match=q.MatchValue(value=True)),
        ],
    )


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-cites", type=int, default=5)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    s = QdrantStorage()
    s.ensure_stub_enrichment_indices()  # searchable_stub index must exist first
    flt = target_filter(args.min_cites)
    total = s.client.count(s.collection_name, exact=True, count_filter=flt).count
    cap = min(total, args.limit) if args.limit else total
    print(f"high-value embeddable stubs (cited>={args.min_cites}, has abstract): {total:,}; processing {cap:,}", flush=True)

    done = 0
    t0 = time.time()
    async with PaperEmbedder(max_concurrent=4) as embedder:
        while done < cap:
            pts, _ = s.client.scroll(
                s.collection_name, scroll_filter=flt, limit=PAGE, offset=None,
                with_payload=["title", "abstract"], with_vectors=False,
            )
            if not pts:
                break
            papers = [(str(p.id), p.payload or {}) for p in pts]
            n = await embedder.embed_and_upsert_batch(papers, s, embed_batch_size=64)
            # flag them searchable so they (a) surface in search and (b) drop out
            # of the scroll filter on the next page (forward-safe pagination).
            s.client.set_payload(
                s.collection_name,
                payload={"searchable_stub": True},
                points=[pid for pid, _ in papers],
                wait=True,
            )
            done += len(papers)
            rate = done / max(time.time() - t0, 1)
            print(f"{done:,}/{cap:,}  (+{n} embedded, {rate:.0f}/s)", flush=True)
    print(f"DONE {done:,} in {(time.time()-t0)/60:.1f}m", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
