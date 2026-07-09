"""Wave 4c search latency benchmark — MCP search path, before/after demotion.

Times SearchService.search (the path MCP search_papers uses) over a fixed
query set, warm (discards first run per query), reports per-query and overall
p50/p90/mean. Also records the searchable embedded-vector count so the two
runs are comparable.

Usage:
  uv run python -m scripts.analytics.bench_search --label before > bench-before.json
  uv run python -m scripts.analytics.bench_search --label after  > bench-after.json
"""
import argparse
import asyncio
import json
import statistics
import time

from qdrant_client import models

from src.core.search.service import SearchService
from src.core.storage import QdrantStorage

QUERIES = [
    "retrieval augmented generation evaluation",
    "instruction tuning large language models",
    "hallucination detection in LLM outputs",
    "low-resource neural machine translation",
    "chain of thought reasoning prompting",
    "named entity recognition transformer",
    "contrastive learning sentence embeddings",
    "parameter efficient fine-tuning adapters",
    "abstractive summarization factual consistency",
    "knowledge graph question answering",
    "speech recognition end to end",
    "vision language pretraining",
    "dialogue state tracking",
    "code generation large language model",
    "mixture of experts scaling",
]
WARMUP = 1
RUNS = 5


def searchable_vec_count(s):
    return s.client.count(
        s.collection_name, exact=True,
        count_filter=models.Filter(
            must=[models.HasVectorCondition(has_vector="abstract-qwen3-8b")],
            must_not=[models.FieldCondition(key="is_stub", match=models.MatchValue(value=True))],
        ),
    ).count


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--runs", type=int, default=RUNS)
    args = ap.parse_args()

    s = QdrantStorage()
    svc = SearchService()
    per_query = {}
    all_latencies = []

    for qtext in QUERIES:
        for _ in range(WARMUP):
            await svc.search(qtext, limit=20)
        lats = []
        for _ in range(args.runs):
            t0 = time.perf_counter()
            await svc.search(qtext, limit=20)
            lats.append((time.perf_counter() - t0) * 1000)
        per_query[qtext] = round(statistics.median(lats), 1)
        all_latencies.extend(lats)

    out = {
        "label": args.label,
        "searchable_embedded_vectors": searchable_vec_count(s),
        "queries": len(QUERIES),
        "runs_per_query": args.runs,
        "overall_ms": {
            "p50": round(statistics.median(all_latencies), 1),
            "p90": round(sorted(all_latencies)[int(len(all_latencies) * 0.9)], 1),
            "mean": round(statistics.mean(all_latencies), 1),
            "min": round(min(all_latencies), 1),
            "max": round(max(all_latencies), 1),
        },
        "per_query_median_ms": per_query,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
