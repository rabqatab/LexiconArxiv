# Post-Bootstrap Catchup — Sequence

**When to run:** After the snapshot bootstrap chain (P1 → P2 → P3 → P4) completes. This runbook fills every gap that the bootstrap does NOT populate — labeling, keywords, references, embeddings, similarity, graph analysis, topic clusters. Without it, downstream search/analytics silently degrade on the newly-added corpus (~2-4M papers per bootstrap).

**Rationale:** See [`docs/design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md). The bootstrap chain focuses on ingestion + payload correctness. Everything the incremental pipeline does *after* payload correctness (steps 5-13 in `run_incremental_pipeline.sh`) is missing from the bootstrap. This runbook is that "everything else."

**Wall clock (measured 2026-07-04 for a ~3.74 M-paper post-P3 catchup):**
- Labeling (vLLM @ 35.6 K/hr at `--vllm-max-concurrent 128` on GB10): **~4.4 days** (~105 h). Ollama baseline projection at 750/hr was ~208 days — infeasible.
- Keyword extraction (regex+KeyBERT, no LLM): ~1 day
- Reference resolution: ~1-2 days
- Embed drain: ~5-7 days (can start on already-labeled subset while remaining labeling continues)
- Similarity + graph analysis: ~1 day (weekly rerun)
- Topic clustering: ~2 hours (quarterly rerun)

**Total: ~2 weeks** with the Phase 1-verified vLLM labeling backend; ~6+ months with the Ollama fallback.

Throughput gate detail: [`vllm-labeling-migration.md`](../design/vllm-labeling-migration.md) §Throughput gate; [`vllm-labeling.md`](vllm-labeling.md) has the scaling table for future capacity-planning re-measures.

---

## Preconditions

- `snapshot-status --json` reports P1, P2, P3, P4 all `complete`.
- vLLM labeling server available (either running or ready to launch). See [`docs/design/vllm-labeling-migration.md`](../design/vllm-labeling-migration.md).
- Qdrant healthy (`curl http://localhost:6333/healthz`).
- No active incremental cycle running (avoid contention with `run_incremental_pipeline.sh`).

## Order matters — do NOT reorder

The steps have a topological dependency:
```
labeling ─┐
          ├─→ embed ─→ similarity ─→ (topics if quarterly)
keywords ─┤
refs ─────┴─→ citation-graph ─→ (analytics via embedded corpus)
```

Specifically: **embed depends on labeling** (section vectors require `abstract_structure`), and **similarity depends on embed** (edges are vector queries).

## Bulk write concurrency — do NOT parallelize

**Serialize Steps 1 → 2 → 3.** The 2026-07-04 catchup attempt tried to run Step 1 (labeling) and Step 2 (keywords) in parallel per the earlier draft of this runbook and hit an immediate wall: Qdrant CPU was already ~78% at baseline (post-P3 indexing), two concurrent bulk clients pushed it into 60 s+ read/write timeouts, and Step 1's `batch_update_abstract_structure` died on the very first batch of 500 papers. See the [`qdrant-tuning.md`](qdrant-tuning.md) runbook for the search-under-load recovery pattern, and [`vllm-labeling.md`](vllm-labeling.md) §Troubleshooting matrix for the `batch_update_abstract_structure` retry note.

**Rule**: never more than one bulk write client against the same Qdrant collection at a time. Use sparkq `--after <job-id>` to chain — the correct commands are shown inline with each step below.

---

## Step 1 — Labeling (vLLM)

**What it fixes:** Gap #1. Populates `abstract_structure` on P2/P3 papers so the embedder generates all 7 section-level vectors instead of just 2 fallback dense vectors.

**Serve vLLM:**
```bash
sparkq submit "./scripts/labeling/serve_vllm.sh" \
    --node 1 --gpu-mem 40G --cpu-mem 24G --max-runtime 96h \
    --tag vllm-labeling --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key vllm-labeling-$(date -u +%Y%m%d) --json
```

Wait for `curl http://localhost:8000/v1/models` to return the model. Then:

**Quality gate (60-paper eval):** Before running against production, verify vLLM output matches Ollama baseline on the 2026-06-19 60-paper set. Pass condition: ≥85% agreement at (sentence, role) tuple level. See [`vllm-labeling-migration.md`](../design/vllm-labeling-migration.md) §Quality gate.

**Throughput gate (500-paper bench):** Verify ≥30K papers/hr sustained. If below, tune `--vllm-max-concurrent` and `--gpu-memory-utilization` before proceeding.

**Full labeling:**
```bash
sparkq submit "uv run python -m src.cli.core_collect label-abstracts \
    --backend vllm --batch-size 500" \
    --node 1 --gpu-mem 0 --cpu-mem 6G --max-runtime 120h \
    --tag label-full --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key label-full-$(date -u +%Y%m%d) --json
```

**Verify:** `curl -s http://localhost:6333/collections/lexicon_arxiv_v3/points/count -X POST -H 'Content-Type: application/json' -d '{"filter":{"must":[{"is_empty":{"key":"abstract_structure"}}],"must_not":[{"is_null":{"key":"abstract"}},{"key":"abstract","match":{"value":""}}]},"exact":true}' | jq .result.count` should return 0 (or very close).

---

## Step 2 — Keyword extraction (AFTER Step 1)

**What it fixes:** Gap #6. Populates `keywords` and `keywords_structured` on P2/P3 papers. Powers autocomplete and BM25 term weighting.

**CPU-only** — but do NOT run in parallel with Step 1 (see §Bulk write concurrency above; 2026-07-04 caused Qdrant read/write timeouts). Chain with `--after`:

```bash
sparkq submit "uv run python -m src.cli.core_collect extract-keywords" \
    --node 1 --gpu-mem 0 --cpu-mem 8G --max-runtime 48h \
    --tag catchup-keywords --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key catchup-keywords-$(date -u +%Y%m%d) \
    --after <STEP1_JOB_ID> --json
```

Default is regex + KeyBERT (no LLM). Don't add `--llm` at bootstrap scale — Ollama keyword extraction has the same serial-chat ceiling as labeling did.

**Verify:** `curl -s http://localhost:6333/collections/lexicon_arxiv_v3/points/count -X POST -d '{"filter":{"must_not":[{"is_empty":{"key":"keywords"}}]},"exact":true}' | jq .result.count` grows to match the real-paper count.

---

## Step 3 — Reference resolution (AFTER Step 2)

**What it fixes:** Gap #3. `resolve-refs --create-stubs` walks each paper's `references` list and creates stub records for any target that doesn't exist as a Qdrant point. Without this, the citation graph out of P2/P3 papers has dangling edges.

Serial chain per §Bulk write concurrency:

```bash
sparkq submit "uv run python -m src.cli.core_collect resolve-refs --create-stubs" \
    --node 1 --gpu-mem 0 --cpu-mem 8G --max-runtime 48h \
    --tag catchup-refs --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key catchup-refs-$(date -u +%Y%m%d) \
    --after <STEP2_JOB_ID> --json
```

**Warning — new stubs need enrichment.** After Step 3 completes, the freshly-created stubs have only reference identifiers (DOI/OpenAlex ID) in payload. Run [`enrich-8-metadata-by-stub-via-openalex`](../pipelines/enrichment.md) to fill title/authors/venue/year on the new stubs before treating them as searchable.

---

## Step 4 — Embed drain

**What it fixes:** Gap #2. Generates all 9 dense vectors + BM25 for every paper in the embedding queue (populated by P3, plus any papers added by Step 3's stub creation).

**Depends on Step 1.** Do not start until labeling is complete on the papers you want fully-vectorized. Papers embedded before their labeling completes will only get 2 dense vectors (raw abstract + structured-fallback) — you'd have to `--force` re-embed them later.

**Also serial with Steps 2/3** per §Bulk write concurrency. Chain via `--after <STEP3_JOB_ID>` on the priority pass. Two concurrent bulk write clients against Qdrant have been proven to fail (2026-07-04 catchup Step 1 + Step 2 experiment).

Full playbook: [`docs/runbooks/embed-drain-strategy.md`](embed-drain-strategy.md). Executive summary:

```bash
# Priority pass: tier 0/1 first, so search becomes useful ASAP
sparkq submit "uv run python -m src.cli.core_collect embed-papers \
    --consume-snapshot-queue --priority-tier 1 -p 12" \
    --node 1 --gpu-mem 12G --cpu-mem 16G --eta 24h \
    --tag embed-priority --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key embed-priority-$(date -u +%Y%m%d) --json

# Full drain: everything remaining
sparkq submit "uv run python -m src.cli.core_collect embed-papers \
    --consume-snapshot-queue -p 12" \
    --node 1 --gpu-mem 12G --cpu-mem 16G --eta 120h \
    --tag embed-full --after <embed-priority-job-id> \
    --idempotency-key embed-full-$(date -u +%Y%m%d) --json
```

**Verify:** `count(has_vector: structured-abstract) == count(real papers)`. See the embed-drain runbook for the exact curl.

---

## Step 5 — Similarity graph (weekly cadence)

**What it fixes:** Gap #4. Populates precomputed typed similarity edges (`same_method`, `same_task`, `same_result`, `method_transfer`, `overall`) on every paper — the backbone of the `get_similar_papers` MCP tool.

**Depends on Step 4.** All target vectors (section-* + structured-abstract) must exist first.

```bash
sparkq submit "uv run python -m src.cli.core_collect compute-similarity --batch-size 50" \
    --node 1 --gpu-mem 0 --cpu-mem 16G --max-runtime 24h \
    --tag compute-similarity-catchup --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key similarity-catchup-$(date -u +%Y%m%d) --json
```

**Verify:** Pick a well-known paper (e.g. the Attention paper) and confirm `get_similar_papers` returns nontrivial results across edge types.

---

## Step 6 — Citation graph analysis (weekly cadence)

**What it fixes:** Gap #5. Populates `pagerank`, `hits_hub`, `hits_authority`, `community_id` on every paper. These drive the notable-paper scoring in `research_topic` and the `/api/graph/*` endpoints.

**Independent of Step 4/5** — runs on citation edges, not embeddings. Can run in parallel.

```bash
sparkq submit "uv run python -m src.cli.core_collect analyze-citation-graph --all --store" \
    --node 1 --gpu-mem 0 --cpu-mem 24G --max-runtime 24h \
    --tag graph-analysis-catchup --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key graph-catchup-$(date -u +%Y%m%d) --json
```

---

## Step 7 — Topic clustering (quarterly cadence)

**What it fixes:** Gap #7. Populates `cluster_id`, `umap_x`, `umap_y` on every paper. Drives the trends UI topic map.

**Depends on Step 4.** UMAP + HDBSCAN operate on `abstract-qwen3-8b` vectors.

```bash
sparkq submit "uv run python -m src.cli.core_collect compute-topics" \
    --node 1 --gpu-mem 0 --cpu-mem 32G --max-runtime 4h \
    --tag compute-topics-catchup --workdir /home/alphabridge/LexiconArxiv \
    --idempotency-key topics-catchup-$(date -u +%Y%m%d) --json
```

---

## Step 8 — DQ asset checks

**Final gate.** Same DQ suite as normal bootstrap:

```bash
uv run python -m src.cli.core_collect data-quality --json > catchup-dq-$(date -u +%Y%m%d).json
```

**Pass condition:** Every asset check returns `status: PASS`. If any FAIL: investigate before declaring the corpus catchup complete. Do NOT enable the daily snapshot-live schedule until all pass.

---

## Rollback

Each step is independently resumable — the CLI uses queue/scroll offsets, not full-corpus locks. If a step crashes:

- **Labeling:** re-invoke; the `skip_existing=True` default picks only papers without `abstract_structure`. Zero risk of double-labeling.
- **Keywords/refs:** same pattern — filters skip papers with the field already populated.
- **Embed:** `drain_snapshot_queue` uses explicit ack (see [incident 2026-06-30](../incidents/2026-06-30-embed-queue-data-loss.md)); a mid-run crash preserves unacked items.
- **Similarity/graph/topics:** overwrite semantics; re-running is safe but wastes previous work. If the crash happened after N% completion, expect roughly N% wasted compute on re-run.

If a bigger issue emerges (bad vLLM output causing garbage `abstract_structure`, e.g.), rollback to the snapshot at [`docs/runbooks/snapshot-rollback.md`](snapshot-rollback.md).

---

## References

- [`docs/design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) — the audit that discovered these gaps.
- [`docs/design/vllm-labeling-migration.md`](../design/vllm-labeling-migration.md) — the labeling backend used in Step 1.
- [`docs/runbooks/embed-drain-strategy.md`](embed-drain-strategy.md) — the deeper playbook for Step 4.
- [`docs/runbooks/snapshot-bootstrap.md`](snapshot-bootstrap.md) — the P1-P4 chain this runbook follows.
- [`scripts/run_incremental_pipeline.sh`](../../scripts/run_incremental_pipeline.sh) — the reference for step order.
