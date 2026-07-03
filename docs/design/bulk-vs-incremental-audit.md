# Bulk vs Incremental Pipeline — Gap Audit

**Date:** 2026-07-04
**Trigger:** The 2026-07-04 labeling gap discovery. P2 promoted ~940K stubs and P3 injected ~2M+ new real papers, all without abstract labeling — because **no snapshot bootstrap phase runs labeling, and nobody noticed**. This audit systematically maps every incremental pipeline step against the bulk bootstrap chain to catch the other hidden gaps before they surface as incidents.
**Owner:** MCH
**Status:** Analysis complete. Policy changes in progress (see §Ollama→vLLM policy).

---

## Motivation

The bulk snapshot bootstrap (P1→P4) and the incremental pipeline (`run_incremental_pipeline.sh`) were designed by different tracks at different times. Bootstrap treats "papers arrive in millions from a JSONL snapshot"; incremental treats "papers trickle in daily from API sources." Each was carefully engineered on its own — but the mapping between them was never written down. The labeling gap is proof: if you're not looking at both sides at once, you can lose an entire pipeline stage on 3 million papers without a single test failure or user error.

The 2026-06-30 embed-queue incident and the 2026-07-03 MCP search incident had the same shape at a smaller scale: something the bootstrap layer produced (unindexed source_id filter, None citation_count) didn't match what the search layer consumed. This audit generalizes that pattern.

---

## Step-by-step mapping

For each step in the incremental pipeline, we ask: does the bulk bootstrap chain do this step? If not, are the P2/P3 papers going to be broken until someone remembers to run the incremental version afterward?

### Legend

- ✅ Present in both, or covered semantically. Safe.
- ⚠️ Present in both but with different semantics or coverage. Investigate before assuming equivalence.
- ❌ Present in incremental but NOT in bulk. **Papers from P2/P3 are broken in this dimension until the incremental step is run against them.**

### Table

| # | Step (CLI) | In incremental | In bulk | Status | Notes |
|---|---|---|---|---|---|
| 1 | `collect-incremental` | ✅ Step 1 | Snapshot itself is the source (P1-P4 read from JSONL) | ✅ | Bulk bypasses collection; the "collection" is the OpenAlex snapshot. |
| 2 | `enrich-6-abstracts-by-doi-via-openalex` | ✅ Step 2 | P1 (`enrich-corpus-fields`) fills 15 fields including abstract | ✅ | Both fill abstract; different source (API vs snapshot). Covered. |
| 3 | `enrich-4-refs-by-doi-via-s2` (S2 references) | ✅ Step 3 | Bulk doesn't call S2 | ⚠️ | Bulk uses snapshot's `referenced_works` directly. S2 gives US-slice more thorough. Post-bootstrap papers miss S2 enrichment until next incremental. Likely acceptable — snapshot refs are comprehensive. |
| 4 | `enrich-2-refs-by-doi-via-crossref` | ✅ Step 4 | Bulk doesn't call CrossRef | ⚠️ | Similar to (3). CrossRef references are a supplement. Bulk papers are OK on primary refs. |
| 5 | **`extract-keywords`** | ✅ Step 5 | **NOT in bulk** | ❌ | **GAP.** P2/P3 papers have empty `keywords` field. Autocomplete `/api/search/suggest` misses them. BM25 keyword-weighted search degraded. Default is regex + KeyBERT (fast, non-LLM). No throughput obstacle — this is a scheduling gap, not a compute one. |
| 6 | **`label-abstracts`** | ✅ Step 6 (Ollama LLM) | **NOT in bulk** | ❌ | **GAP #1 (the one we found).** P2/P3 papers have empty `abstract_structure`. Section-* vectors never generated. Default MCP search (multi_vector) collapses to 1/3 dense signals. See [`vllm-labeling-migration.md`](vllm-labeling-migration.md) for the fix. |
| 7 | **`resolve-refs --create-stubs`** | ✅ Step 7 | **NOT in bulk** | ❌ | **GAP.** P2/P3 papers have raw reference lists in payload but no stub records were created in Qdrant for those references. Citation graph edges from P2/P3 outward are missing. `get_citations` on a P2/P3 paper returns fewer results than reality warrants. |
| 8 | `enrich-8-metadata-by-stub-via-openalex` | ✅ Step 8 | P2 (`resolve-stubs-from-snapshot`) does the equivalent | ✅ | Both promote stubs. Semantics differ (API vs snapshot lookup) but the payload endpoint is the same. Covered. |
| 9 | `build-cited-by --incremental` | ✅ Step 9 | P4 (`extend-cited-by-from-snapshot`) does this | ✅ | Both extend `external_cited_by`. Covered. |
| 10 | **`embed-papers`** | ✅ Step 10 (Ollama embedding) | **NOT in bulk** (papers queued to `embedding_queue.jsonl`, must be manually drained) | ❌ | **GAP.** Well-known — [`embed-drain-strategy.md`](../runbooks/embed-drain-strategy.md) covers execution. But note: P2/P3 papers stay invisible to hybrid search (both dense AND BM25) until this runs. |
| 11 | `compute-similarity` (weekly) | ✅ Step 11 | Not applicable to bulk directly | ❌ | **GAP.** Post-P2/P3, similarity edges for the new papers don't exist. Search-critical for `get_similar_papers` MCP tool. |
| 12 | `analyze-citation-graph --all --store` (weekly) | ✅ Step 12 | Not applicable | ❌ | **GAP.** PageRank / HITS / community IDs on new papers are unset. Affects notable-paper scoring in `research_topic`. |
| 13 | `compute-topics` (quarterly) | ✅ Step 13 | Not applicable | ❌ | **GAP.** UMAP+HDBSCAN topic clusters have no assignments for new papers. Affects trends UI, topic map. |

**Positive check** — `discover-corpus-gaps` (P3) has NO incremental equivalent. This is intentional — incremental crawls from known sources; snapshot-based gap discovery is a bulk-only concept.

---

## Summary of gaps

Ranked by user-visible impact:

| Rank | Gap | Impact today |
|---|---|---|
| 1 | **Labeling** (step 6) | Section-aware search dead on 90% of corpus. Already tracked in [`vllm-labeling-migration.md`](vllm-labeling-migration.md). |
| 2 | **Embedding** (step 10) | P2/P3 papers invisible to hybrid search until drain. Tracked in [`embed-drain-strategy.md`](../runbooks/embed-drain-strategy.md). |
| 3 | **Reference resolution** (step 7) | Incomplete citation graph on P2/P3 outbound edges. `get_citations` returns partial results. Affects graph analysis quality. |
| 4 | **Similarity** (step 11) | `get_similar_papers` MCP tool returns nothing for P2/P3 papers. |
| 5 | **Citation graph analysis** (step 12) | PageRank / notable-paper scoring degraded for P2/P3 papers. |
| 6 | **Keyword extraction** (step 5) | Empty `keywords` field on P2/P3 papers. Autocomplete + keyword-weighted BM25 slightly degraded. |
| 7 | **Topic clustering** (step 13) | Trends UI shows P2/P3 papers as cluster_id=-1 (unassigned). Cosmetic + affects analytics. |

**Gaps not currently on any bootstrap plan**: 3, 4, 5, 7. These need explicit runbook steps or they'll silently degrade the corpus quality for another quarter until someone spot-checks.

---

## Ollama → vLLM policy (per 2026-07-04 requirement)

Ollama's ceiling is workload-dependent. Measurements on GB10:

| Workload | Ollama concurrency | Throughput | Notes |
|---|---|---|---|
| **Chat / labeling** (granite4.1:8b) | `-p 1` → `-p 8`: identical | ~750/hr | **Serial** — one request at a time on GPU. |
| **Embedding** (qwen3-embedding:8b) | `-p 1`: 28K/hr → `-p 4`: 88K/hr → `-p 8`: 89K/hr | ~88K/hr ceiling | **Batched** — Ollama batches concurrent embed requests internally. |

**Policy** (unified for bulk AND incremental):

1. **Chat/labeling → vLLM everywhere.** Ollama's 750/hr ceiling makes even incremental cycles slow (~150K papers/week is at the edge, 200 hours of pure labeling for a 152K-paper week). vLLM's ~30K+/hr keeps up with any realistic incremental volume and makes bulk feasible. Migration in progress ([`vllm-labeling-migration.md`](vllm-labeling-migration.md)). **Ollama backend remains supported as a fallback** — the `--backend ollama|vllm` flag lets a machine without vLLM serving still run labeling for small ad-hoc runs.
2. **Embedding → Ollama stays.** Measured at 88K/hr — the ceiling is model-throughput, not concurrency. vLLM has ~2-3× additional headroom for embedding models but the migration cost isn't justified until embed drain becomes the sole bottleneck. Reassess after Phase 2 drain wall-clock.
3. **Keyword extraction — Ollama-optional today, vLLM-first if enabled.** Default is regex+KeyBERT (no LLM). If we ever want LLM keyword judge at bootstrap scale, use vLLM. Not on the critical path this quarter.
4. **HyDE (query analyzer)** — search-time only, ~1 call per user query. Ollama is fine at this volume; no policy change.

---

## Action items

### Immediate (Phase 0 continuation, 2026-07-04)

- [ ] **Update `docs/design/vllm-labeling-migration.md`** to reflect the unified policy: "vLLM is the default for all bulk AND incremental labeling; Ollama is the fallback." **Removes the earlier statement that Ollama was fine for incremental.**
- [ ] **Update `docs/runbooks/snapshot-bootstrap.md`** to make it explicit that the bootstrap chain must be followed by the incremental steps 5→7→10→11→12→13 (in that order). Add cross-refs to the individual runbooks.
- [ ] **Create `docs/runbooks/post-bootstrap-catchup.md`** — the exact sequence of CLIs to run after P4 completes to bring the corpus into a state equivalent to running the full incremental pipeline. This catches all 7 gaps above in one runbook.

### Phase 1 (after P3 completes)

- [ ] Execute the post-bootstrap catchup runbook against the P2/P3 additions.
- [ ] Add a DQ check that WARNS when the corpus has >N papers with abstract but no abstract_structure (early signal of the labeling gap recurring).

### Deferred (post-bootstrap stability)

- [ ] Refactor `run_incremental_pipeline.sh` to explicitly call out the "post-bulk catch-up" mode — either as a flag or as a separate script — so the sequence is executable end-to-end from a fresh checkout.
- [ ] Add integration test: seed a fake snapshot with 10 papers, run bootstrap, then run catchup, then verify every paper has `abstract_structure`, `keywords`, similarity edges, embeddings, cluster_id. This catches the whole class of gaps at CI time.
- [ ] Consider a Dagster asset graph for the post-bootstrap catchup so the sequence is orchestrated instead of scripted.

---

## Lessons

**The gap wasn't the labeling code — it was the schema of "bootstrap complete."** No single test could catch it because both pipelines were internally correct. What was wrong was the *seam* between them, and the seam was in nobody's head.

**Preventive rule going forward**: **any new bulk phase must include a "gap check" against the incremental pipeline before it's declared production-ready.** The check is: for every downstream consumer of the corpus (search, MCP, analytics), what fields does it read? Are all those fields populated by the bulk phase? If not, the bulk phase is not done — it queues a follow-up job or it's a documented incomplete state.

This audit is that check for the current bootstrap. Future bootstraps repeat the process.

---

## References

- [`docs/design/vllm-labeling-migration.md`](vllm-labeling-migration.md) — the labeling migration triggered by this audit's #1 gap.
- [`docs/runbooks/embed-drain-strategy.md`](../runbooks/embed-drain-strategy.md) — the embed drain phase covering gap #2.
- [`docs/incidents/2026-07-03-mcp-search-endpoints-broken.md`](../incidents/2026-07-03-mcp-search-endpoints-broken.md) — the sibling category of "bulk-writes-something-search-doesn't-expect" bugs.
- [`docs/runbooks/snapshot-bootstrap.md`](../runbooks/snapshot-bootstrap.md) — will be updated with post-bootstrap catchup pointers.
