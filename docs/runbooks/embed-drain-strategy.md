# Embed Drain Strategy — Post-P3 Playbook

**Date drafted:** 2026-07-03
**Trigger:** P3 (`discover-corpus-gaps`) completes with ~2-4M new papers queued for embedding.
**Goal:** Get hybrid search useful on the highest-quality subset in **hours** instead of the full drain's **days**, without touching the vector schema mid-bootstrap.

## Situation snapshot

At P3 completion the queue at `~/dagster_home/snapshot_checkpoints/embedding_queue.jsonl` will hold `~len(P3.injected)` entries. Each injected paper was written with `vector={}` (see `src/core/storage/writer.py:514`) — **both dense and BM25 vectors are absent**, so P3 papers are **totally invisible to hybrid search** until embedded.

Observed vector count per fresh P3 paper (no labeling yet):
- `abstract-qwen3-8b` — full-abstract embedding (see [ponytail audit #24](../refactoring/2026-06-24-ponytail-audit.md) for why this is deferred-removable)
- `structured-abstract` — falls back to raw abstract when `abstract_structure` is missing (identical to abstract-qwen3-8b for unlabeled papers)
- `bm25` — sparse, cheap to generate

Section vectors (`section-{method,task,domain,background,approach,result,contribution}`) are **only** generated when `abstract_structure` is populated by the abstract-labeling stage. Fresh P3 injections do not have this, so they cost 3 vectors each (not 9).

## The four levers

| Lever | Change | Expected gain | Cost |
|---|---|---|---|
| **A. Parallelism** | `-p 4 → -p 12` (or benchmark result) | 2–3× (Ollama GPU idle) | verify `nvidia-smi` first |
| **B. Sample benchmark** | 5K-paper sweep of (concurrency × batch_size) before committing | prevents wrong tuning | 1–2 hours upfront |
| **C. P4 in parallel** | Kick `extend-cited-by-from-snapshot` on sparkq while drain runs | saves ~2–3 h wall clock | small — P4 doesn't need embeddings, orthogonal |
| **D. Tier-priority drain** | `--priority-tier 1` for hot subset first | search useful in hours, not days | none — code already landed (commit `b1b1747`) |

## Verification checklist (before running anything)

Run these three commands and file their outputs in the sparkq report if anything surprises:

```bash
# 1. GPU idle?
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
# expect: ~0% while P3 is CPU-bound

# 2. Real free memory (GB10 unified pool — nvidia-smi memory is N/A)
grep -E "MemFree|MemAvailable" /proc/meminfo
# need ≥ 30G for a -p 12 embed drain (each Ollama request ~2G peak)

# 3. Queue depth (rough embed workload size)
uv run python -c "from src.core.snapshot import embedding_queue; print(f'{len(embedding_queue.peek_all()):,} items queued')"
```

## Execution order (once P3 completes)

### Step 1 — Sample benchmark (Lever B)

Snapshot the queue, run three concurrency settings on a 5K sample, pick the winner.

```bash
# Save queue backup (safety — the benchmark uses the real queue, so
# a fresh append-only marker guards against accidental full-drain)
cp ~/dagster_home/snapshot_checkpoints/embedding_queue.jsonl \
   ~/dagster_home/snapshot_checkpoints/embedding_queue.jsonl.pre-bench

# Dry-run each config on the first 5K items using --limit
for P in 4 8 12; do
  echo "=== -p $P ==="
  time uv run python -m src.cli.core_collect embed-papers \
        --consume-snapshot-queue --limit 5000 \
        -p "$P" --batch-size 8 --embed-batch-size 64 \
      2>&1 | tail -5
done
```

Interpret: the winner is the one that finishes ~5K items fastest **without** stalling on `Ollama connection refused` in the logs. If `-p 12` and `-p 16` are within ~10%, prefer the lower for stability headroom.

**Rollback if bench went sideways:** the queue's `remove()` writes cancellation records, so restoring the backup is `cp .pre-bench embedding_queue.jsonl` — but the papers that DID get embedded in the bench stay embedded (harmless).

### Step 2 — Priority pass (Lever D)

Run tier 0/1 first so search becomes useful ASAP. Ballpark: tier 0/1 papers are ~30% of a fresh P3 injection (verify with `get_corpus_stats` after P3 to check).

```bash
sparkq submit "uv run python -m src.cli.core_collect embed-papers \
    --consume-snapshot-queue --priority-tier 1 -p <bench-winner>" \
    --node 1 --gpu-mem 12G --cpu-mem 16G --eta 8h \
    --tag embed-priority --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key embed-priority-2026-07-04 \
    --json
```

Expected wall clock: ~30% of corpus × <bench throughput>/hr. Should finish in <8 hours if the bench came in at ~15K papers/hr.

### Step 3 — P4 in parallel (Lever C)

**As soon as** step 2 kicks off, launch P4 on the same node — it's CPU-bound (Qdrant scroll + payload updates) and won't fight Ollama for GPU.

```bash
sparkq submit "uv run python -m src.cli.core_collect extend-cited-by-from-snapshot" \
    --node 1 --gpu-mem 0 --cpu-mem 6G --eta 3h \
    --tag snapshot-p4 --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key snapshot-p4-2026-07-04 \
    --json
```

Wait: `sparkq status` should show both `embed-priority` and `snapshot-p4` running concurrently. If sparkq's real-memory gate defers P4 because embed is using all the CPU RAM, that's fine — P4 will start when embed's peak passes.

### Step 4 — Full drain (Lever A + drain the rest)

After the priority pass drains its tier 0/1 subset, kick the unfiltered drain to catch the tier 2+ / no-tier papers.

```bash
sparkq submit "uv run python -m src.cli.core_collect embed-papers \
    --consume-snapshot-queue -p <bench-winner>" \
    --node 1 --gpu-mem 12G --cpu-mem 16G --eta 60h \
    --tag embed-full --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key embed-full-2026-07-04 \
    --after <embed-priority-job-id> \
    --json
```

`--after` chains: this stays queued until the priority pass finishes cleanly. If the priority pass fails (embedder crash, Qdrant down), the full drain stays queued indefinitely — which is what we want, don't paper over problems.

### Step 5 — DQ asset_checks

Post-full-drain, run the DQ suite to verify search-critical invariants:

```bash
uv run python -m src.cli.core_collect data-quality-checks --json
```

Expected: all checks pass. Any FAIL blocks the "bootstrap complete" declaration; investigate before enabling the [Snapshot Live Mode](../pipelines/snapshot-live-mode.md) daily schedule.

## What NOT to do

- **Don't remove `abstract-qwen3-8b` mid-drain.** Yes, it's dead work; yes, it's 33% GPU time. But changing the vector schema while millions of upserts flow through is asking for a "why did clustering just break" incident. Deferred as [ponytail audit #24](../refactoring/2026-06-24-ponytail-audit.md).
- **Don't run drain across both nodes yet.** Node 2 has no NFS write access to the queue file today. Split-queue coordination is a separate design; single-node drain with `-p 12` should be enough.
- **Don't skip DQ.** Every incident in the 2026-06/07 window (P2 slowdown, embed queue loss, MCP search) was signalled by a DQ check that either didn't exist or wasn't being run. Trust the invariants, run the checks.

## References

- `drain_snapshot_queue()` — `src/cli/commands/embedding.py:12` (extracted 2026-07-03, commit `25a262a`)
- Priority filter — added 2026-07-03, commit `b1b1747`
- Related incidents: [`2026-06-30 embed queue data loss`](../incidents/2026-06-30-embed-queue-data-loss.md), [`2026-06-29 P2 missing indices`](../incidents/2026-06-29-p2-missing-payload-indices.md)
- Ponytail deferrals: [`abstract-qwen3-8b removal`](../refactoring/2026-06-24-ponytail-audit.md) item #24
- Broader bootstrap plan: [`Snapshot Bootstrap`](./snapshot-bootstrap.md)
