"""Offline cost / time estimator for the LLM stages of an incremental update.

Samples real papers from Qdrant, runs them through the actual prompt templates
(without making any LLM calls), counts tokens with tiktoken (a close proxy for
Gemini's tokenizer), and projects:

  - Closed-LLM $ cost (Gemini 2.5/3 Flash pricing, editable below)
  - Open-LLM wall-clock time (per model tok/s throughput, editable below)

Run:
    uv run python estimate_incremental_llm_cost.py --days 1 --sample 100
"""
import argparse
from statistics import mean, median

import tiktoken
from qdrant_client.http import models as q

from src.core.keyword.llm_base import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT,
    EXTRACTION_USER_PROMPT_TITLE_ONLY,
    JUDGE_SYSTEM_PROMPT,
    JUDGE_USER_PROMPT,
)
from src.core.labeling.llm_base import (
    LABELING_SYSTEM_PROMPT,
    LABELING_USER_PROMPT,
    format_numbered_sentences,
)
from src.core.storage import QdrantStorage

# --- Tunables (edit to your quotes) -----------------------------------------
GEMINI_MODELS = {
    # Public list pricing per 1M tokens. Edit if you have enterprise quotes.
    "gemini-2.5-flash":        {"in": 0.30,  "out": 2.50},
    "gemini-3-flash-preview":  {"in": 0.30,  "out": 2.50},   # placeholder; verify
    "gemini-2.5-pro":          {"in": 1.25,  "out": 10.00},
}

OPEN_MODELS_TOK_PER_SEC = {
    # Measured throughput on your hardware. Edit with real numbers.
    "llama3.1-8b (Ollama on Spark)":   80.0,
    "llama3.1-70b (Ollama on Spark)":  15.0,
    "qwen3-embedding-8b (Ollama)":    250.0,   # embedding is way faster
}

# Rough output sizes from inspection of prompts + schema
KEYWORD_OUT_TOKENS   = 180   # 7 categories x ~2-3 keywords, JSON overhead
JUDGE_OUT_TOKENS     = 100   # ~10 relevant keywords, JSON overhead
LABELING_OUT_TOKENS  = 220   # ~10 sentences x ~2 labels each, JSON overhead
EMBEDDING_OUT_TOKENS = 0     # embeddings produce vectors, not tokens


def _tok_count(enc: tiktoken.Encoding, text: str) -> int:
    return len(enc.encode(text, disallowed_special=()))


def estimate_per_paper(
    enc: tiktoken.Encoding,
    title: str,
    abstract: str,
    judge_enabled: bool,
    labeling_enabled: bool,
) -> dict:
    """Return input/output token counts for each LLM stage, plus embedding input."""
    sizes: dict[str, dict[str, int]] = {}

    # Stage 6a: keyword extraction (title + abstract)
    ext_user = (EXTRACTION_USER_PROMPT if abstract else EXTRACTION_USER_PROMPT_TITLE_ONLY).format(
        title=title, abstract=abstract or ""
    )
    sizes["keyword_extract"] = {
        "in":  _tok_count(enc, EXTRACTION_SYSTEM_PROMPT) + _tok_count(enc, ext_user),
        "out": KEYWORD_OUT_TOKENS,
    }

    # Stage 6b: keyword judge (only if enabled & we have abstract)
    if judge_enabled and abstract:
        # We don't know the candidate keyword list until after extraction; use a
        # conservative proxy of 15 keywords.
        proxy_kw = ", ".join(["candidate"] * 15)
        judge_user = JUDGE_USER_PROMPT.format(title=title, abstract=abstract, keywords=proxy_kw)
        sizes["keyword_judge"] = {
            "in":  _tok_count(enc, JUDGE_SYSTEM_PROMPT) + _tok_count(enc, judge_user),
            "out": JUDGE_OUT_TOKENS,
        }

    # Stage 7: abstract labeling (only if abstract present)
    if labeling_enabled and abstract:
        # Rough sentence split by ". " is fine for token estimation.
        sentences = [s.strip() for s in abstract.replace("\n", " ").split(". ") if s.strip()]
        numbered = format_numbered_sentences(sentences)
        label_user = LABELING_USER_PROMPT.format(title=title, abstract=abstract, sentences=numbered)
        sizes["label_abstract"] = {
            "in":  _tok_count(enc, LABELING_SYSTEM_PROMPT) + _tok_count(enc, label_user),
            "out": LABELING_OUT_TOKENS,
        }

    # Embedding (open-source only; input = title + abstract)
    sizes["embed_abstract"] = {
        "in":  _tok_count(enc, f"{title}\n\n{abstract or ''}"),
        "out": EMBEDDING_OUT_TOKENS,
    }
    return sizes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days",   type=int, default=1,   help="Project for this many days of incremental")
    ap.add_argument("--sample", type=int, default=100, help="Sample size from real corpus")
    ap.add_argument("--rate",   type=float, default=240.0,
                    help="Assumed papers/day for incremental (default 240 from last 30d)")
    ap.add_argument("--no-judge", action="store_true", help="Estimate without keyword judge stage")
    ap.add_argument("--no-labeling", action="store_true", help="Estimate without labeling stage")
    args = ap.parse_args()

    enc = tiktoken.get_encoding("cl100k_base")  # Gemini-ish proxy; good enough for $ estimate
    storage = QdrantStorage()

    not_stub = q.Filter(must_not=[q.FieldCondition(key="is_stub", match=q.MatchValue(value=True))])
    pts, _ = storage.client.scroll(
        collection_name=storage.collection_name,
        scroll_filter=not_stub,
        limit=args.sample,
        with_payload=["title", "abstract"],
    )
    papers = [(p.payload.get("title") or "", p.payload.get("abstract") or "") for p in pts]
    with_abs = sum(1 for _, a in papers if a)
    print(f"Sampled {len(papers)} real papers ({with_abs} have abstracts)")

    per_stage_in:  dict[str, list[int]] = {}
    per_stage_out: dict[str, list[int]] = {}
    for title, abstract in papers:
        sizes = estimate_per_paper(
            enc, title, abstract,
            judge_enabled=not args.no_judge,
            labeling_enabled=not args.no_labeling,
        )
        for stage, tok in sizes.items():
            per_stage_in.setdefault(stage,  []).append(tok["in"])
            per_stage_out.setdefault(stage, []).append(tok["out"])

    N = int(args.rate * args.days)
    print(f"\n=== Projection: N = {N:,} papers ({args.rate}/day × {args.days}d) ===\n")

    # Per-stage table
    print(f"{'Stage':<20} {'mean_in':>10} {'median_in':>12} {'mean_out':>10}")
    for stage in per_stage_in:
        mi = mean(per_stage_in[stage])
        md = median(per_stage_in[stage])
        mo = mean(per_stage_out[stage])
        print(f"{stage:<20} {mi:>10.0f} {md:>12.0f} {mo:>10.0f}")

    # Total tokens for N papers
    total_in  = sum(mean(v) for v in per_stage_in.values())  * N
    total_out = sum(mean(v) for v in per_stage_out.values()) * N
    llm_in    = sum(mean(v) for k, v in per_stage_in.items()  if k != "embed_abstract") * N
    llm_out   = sum(mean(v) for k, v in per_stage_out.items() if k != "embed_abstract") * N
    print(f"\nTotal tokens across N papers:")
    print(f"  LLM stages  input:  {llm_in:>15,.0f}")
    print(f"  LLM stages  output: {llm_out:>15,.0f}")
    print(f"  Embedding   input:  {mean(per_stage_in['embed_abstract']) * N:>15,.0f}")

    print("\n=== Closed-LLM $ cost (Gemini) ===")
    for model, px in GEMINI_MODELS.items():
        cost = llm_in / 1e6 * px["in"] + llm_out / 1e6 * px["out"]
        print(f"  {model:<30} ${cost:>8.2f}")

    print("\n=== Open-LLM wall-clock (sequential, naïve) ===")
    for model, tps in OPEN_MODELS_TOK_PER_SEC.items():
        # Each LLM stage sequentially generates its output tokens; input is near-free
        # on decoder-only models (prefill is much faster than decode). Approximate
        # by output-token budget plus ~10% for prefill.
        stages_out = sum(mean(v) for k, v in per_stage_out.items() if k != "embed_abstract")
        seq_seconds_per_paper = stages_out / tps * 1.1
        total_hours = seq_seconds_per_paper * N / 3600
        print(f"  {model:<35} {seq_seconds_per_paper:>6.1f}s/paper → {total_hours:>6.2f}h for N")

    # Embedding throughput (parallel by abstract length, negligible per paper)
    emb_in_per_paper = mean(per_stage_in["embed_abstract"])
    emb_tps = OPEN_MODELS_TOK_PER_SEC.get("qwen3-embedding-8b (Ollama)", 250.0)
    emb_seconds_per_paper = emb_in_per_paper / emb_tps
    print(f"\n  Embedding wall-clock: {emb_seconds_per_paper:.2f}s/paper "
          f"→ {emb_seconds_per_paper * N / 60:.1f}min for N")


if __name__ == "__main__":
    main()
