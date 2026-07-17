# Bulk vs Incremental Pipeline — Gap Audit

**Date:** 2026-07-04
**Trigger:** The 2026-07-04 labeling gap discovery. P2 promoted ~940K stubs and P3 injected ~2M+ new real papers, all without abstract labeling — because **no snapshot bootstrap phase runs labeling, and nobody noticed**. This audit systematically maps every incremental pipeline step against the bulk bootstrap chain to catch the other hidden gaps before they surface as incidents.
**Owner:** MCH
**Status:** Analysis complete. Policy changes in progress (see §Ollama→vLLM policy).

---

## Terminology (three ingest paths — do not conflate)

The word "bulk" in this document means the **snapshot bootstrap**, not the crawler script. There are three distinct ingest paths:

| Term used here | What it is | Orchestrator |
|---|---|---|
| **snapshot bootstrap** ("bulk") | OpenAlex-snapshot phases P1→P4 (`enrich-corpus-fields` / `resolve-stubs-from-snapshot` / `discover-corpus-gaps` / `extend-cited-by-from-snapshot`). Built the 6.2M corpus. | none (CLI / `snapshot-live-delta`) |
| **crawler bulk** ("full") | Pull fresh papers from arXiv/ACL/DBLP/AAAI/OpenReview/ACM, then post-process. Legacy full rebuild. | `scripts/run_full_pipeline.sh` |
| **incremental** | Daily/weekly/quarterly trickle updates. | `scripts/run_incremental_pipeline.sh` |

The step-by-step mapping below is **snapshot bootstrap vs incremental**. `run_full_pipeline.sh` (crawler bulk) is a separate path and is not the "bulk" column here.

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

**Policy — Path B (finalized 2026-07-04)**: **Ollama chat is retired from every pipeline stage.** Ollama continues to serve search-time embedding and search-time HyDE; nothing else.

1. **Chat/labeling → vLLM everywhere.** Ollama's 750/hr ceiling makes even incremental cycles slow (a 152K-paper week takes 200+ hours of pure labeling). vLLM's ~30K+/hr keeps up with any realistic incremental volume and makes bulk feasible. Migration in progress ([`vllm-labeling-migration.md`](vllm-labeling-migration.md)). **Ollama backend is preserved as a fallback in the CLI** (`--backend ollama`) for dev laptops without a GPU, but no production incremental cycle should use it.
2. **Embedding → Ollama stays (bulk + incremental + search).** Measured at 88K/hr batched (`-p 4+`, GB10). Vector-space integrity is critical for search recall: query embeddings AND stored corpus embeddings must come from the same serving stack to guarantee cosine consistency. Path A (vLLM embedding for incremental, Ollama for search) was rejected because it would fork the vector space along the incremental frontier — silent recall degradation is an unacceptable risk.
3. **Keyword LLM (`--llm`, `--judge` flags on `extract-keywords`) → deprecated.** Default remains regex+KeyBERT (no LLM at all). If we ever want LLM keyword quality, add it via vLLM only. The `--llm/--judge` flags stay in the CLI for backward compatibility but the incremental runbook forbids them.
4. **HyDE (query analyzer) → Ollama stays (search-time only).** ~1 call per user query, ~10K/week. Ollama's serial chat throughput is irrelevant at this volume. Keeping HyDE on Ollama avoids requiring the vLLM server to be up during search — search availability is decoupled from labeling-cycle scheduling.

**MCP-level implication (verified 2026-07-04):** the default `search_papers` path (HyDE off in the shipped `RetrievalConfig`) touches only Ollama embed + Qdrant; ~400-600 ms total against the 5 s handler budget. If HyDE is ever enabled, the ~2-5 s Ollama chat call still fits under the 5 s budget for the same low-volume reason.

### Bulk-write concurrency rule (added 2026-07-04 after runtime discovery)

Qdrant cannot serve two heavy bulk write clients + user-facing search simultaneously. The 2026-07-04 catchup attempt tried Step 1 (labeling) and Step 2 (keywords) in parallel per the earlier post-bootstrap runbook — Step 1 died on the first batch of 500 papers with a `set_payload` timeout, and search hit Qdrant's own 60 s "fill query context" internal timeout.

**Rule:** post-bootstrap catchup phases run **strictly serial** (Step 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8), using sparkq `--after <job-id>` chaining. Under-the-hood defenses:

1. **Client-side retry on all bulk write paths.** `_retry_qdrant_call` (commit `c61a652`) wraps every `set_payload` in exponential backoff. `batch_update_abstract_structure` uses it today; the code overhaul plan Wave 1 generalizes to `batch_update_code_repos`, `batch_extend_external_cited_by`, `batch_inject_papers`.
2. **Qdrant background-thread caps.** `hnsw_config.max_indexing_threads=2` + `optimizers_config.max_optimization_threads=2` (commit `9636d66`) leaves 6-10 cores free for search under any bulk write load. Applies to fresh collections automatically; run the PATCH in [`docs/runbooks/qdrant-tuning.md`](../runbooks/qdrant-tuning.md) for existing ones.
3. **QdrantStorage default timeout 300 s** (`QDRANT_TIMEOUT` env override). Search/MCP callsites are still under their own 5 s handler budget.

Together these turn what was a hard failure ("cannot label under production Qdrant load") into a soft slowdown ("search takes ~2 s instead of ~500 ms while labeling runs"). Search remains functional; MCP remains within budget.

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

## P3 data-quality gap (added 2026-07-06)

While running the catchup labeling, we discovered a **different** class of P3 gap — not "downstream stages didn't run" (the original 7 gaps above) but "P3 injected the wrong kind of points to begin with."

**Root cause.** `discover_corpus_gaps` (P3) filters OpenAlex snapshot works by anchor + concept classification but **does not filter by `type`**. As a result the ~2 M P3-injected points include:

- `book` — full table-of-contents + preface stored in the `abstract` field.
- `peer-review` — an entire peer-review thread (26 K-char single "abstract") stored as if it were a paper.
- `editorial` — opinion-piece body text stored as an "abstract".
- `letter`, `erratum`, `retraction`, `other` — likely present at lower volume; not yet enumerated.

The catchup labeling exposed this because these non-article "abstracts" are far longer than legitimate paper abstracts (measured p90 = 25 647 chars, some >30 000 chars), which blows past vLLM's `max_model_len`. Sampling five random long-abstract papers hit 3 non-article types in the sample.

**Impact today:**

- **Labeling** wastes vLLM cycles trying to structure body text into rhetorical roles that don't apply.
- **Search** surfaces book chapters and peer-review threads as "papers."
- **Similarity edges** into these are semantically meaningless.
- **Downstream analytics** (topic clusters, notable-paper scoring) treats them as first-class papers.

**Estimated share.** Not yet enumerated; sampling suggests ≥ 10-20 % of the P3-injected subset.

**Fix plan (deferred to post-catchup — see live backlog [`docs/plans/TODO.md`](../plans/TODO.md)):**

1. Count `type` distribution across P2/P3-injected papers.
2. Design keep/delete policy — probably keep `article`, `preprint`, `conference-paper`, `dissertation`; drop `book`, `peer-review`, `editorial`, `letter`, `erratum`, `retraction`, `other`.
3. Delete + cleanup similarity/cited_by/graph refs pointing at the deleted points.
4. Add a DQ warn-check for non-article proportion so this doesn't recur silently.
5. Add a `type` filter to `discover_corpus_gaps` (P3) so the next quarterly bootstrap doesn't reintroduce them.

Trigger: after post-bootstrap catchup completes stably (same rule as [ponytail audit](../refactoring/2026-06-24-ponytail-audit.md) and [code overhaul plan](../refactoring/2026-07-04-code-overhaul-plan.md)).

## Qdrant filter-index gap (added 2026-07-06)

A **third** class of gap surfaced during the same catchup effort. This one is not about missing pipeline stages or wrong point types — it's about **Qdrant filter shapes that were fine at 100 K corpus scale silently becoming unusable at 6 M**.

**Root cause.** Every enricher scroll uses a payload filter like `abstract == ""` or `IsEmpty(referenced_works)`. At small corpus size Qdrant's brute-force filter path returns in milliseconds. At 6 M points with **no payload index on the filtered field**, the same query goes over Qdrant's server-side 60-second `scroll_by_id` / 148-second `retrieve` timeout and returns a 500. Retry doesn't help: the second scan is the same speed as the first.

**How we found it.** Incremental cycles `830c`, `d582`, `7e38` all died at Step 2 or Step 3a. Each traceback pointed at a different reader function — `get_papers_missing_abstracts`, then `get_papers_missing_references` — but the pattern was identical:

```
qdrant_client.http.exceptions.UnexpectedResponse: 500
Timeout error: Operation 'scroll_by_id' timed out after 60s
```

When we inspected `payload_schema` on the running collection, only seven fields were indexed (`fetched_at`, `source_id`, `is_stub`, `doi`, `openalex_id`, `arxiv_id`, `venue`). Every enricher filter was hitting an unindexed field.

**Fix (this ships during the incident, not post-catchup):**

1. **Add the seven missing indices online.** No collection downtime, ~10–30 min per field in parallel. Fields chosen by walking every scroll/count callsite in `src/core/storage/reader.py`, then extended when the Wave 4b/4c cleanup planning needed provenance-based cuts:
   - `abstract_structure_source` (keyword)
   - `injected_from_snapshot` (bool)
   - `snapshot_filled_at` (datetime)
   - `year` (integer)
   - `type` (keyword)
   - `promoted_from_stub` (bool)
   - `tier` (integer)
2. **Add a `fetched_since` filter to the reader** where a scroll had none, using the indexed `fetched_at` — so the enricher only scans papers we actually just crawled, not the full 6 M corpus. Wired through `enrich-6-abstracts-by-doi-via-openalex`, `enrich-4-refs-by-doi-via-s2`, `enrich-2-refs-by-doi-via-crossref` as `--recent-days N`. Set in `run_incremental_pipeline.sh` to `DAYS + 2`.
3. **Wrap reader scrolls in `_retry_qdrant_call`** so transient contention (real Qdrant hiccups, not the deterministic-slow-query class) is survivable.

**Follow-up gaps still open** (queued as [Wave 1e / 4b](../refactoring/2026-07-04-code-overhaul-plan.md) items):

- `fetched_at` only exists on 178 K of 6.2 M points — P2/P3 injections don't write it. The `--recent-days` filter therefore only reaches original-crawler papers. Enough for incremental cycles; not enough if we ever need enrichers to hit snapshot-injected papers. Backfill via `snapshot_filled_at` (now indexed).
- Every OTHER bulk-scroll reader path — `get_papers_missing_references_no_doi`, `get_papers_for_abstract_labeling`, etc. — is the same shape of landmine. Today's fix touches only the two that killed the pipeline; Wave 1e generalizes.
- A payload-schema lint check that fails CI if any bulk-scroll filter shape references a field not in `payload_schema`.

**Rule** (added to Lessons below): at 6M+ corpus scale, **payload filters treated as free at 100K become deterministic 60s failures**. Any new bulk-read path should either use one of the already-indexed fields or add its own index; never merge a bulk scroll whose filter shape hits an unindexed field.

Instrumentation runbook: [`../runbooks/qdrant-tuning.md`](../runbooks/qdrant-tuning.md) §Payload indices.

## Lessons

**The gap wasn't the labeling code — it was the schema of "bootstrap complete."** No single test could catch it because both pipelines were internally correct. What was wrong was the *seam* between them, and the seam was in nobody's head.

**Preventive rule going forward**: **any new bulk phase must include a "gap check" against the incremental pipeline before it's declared production-ready.** The check is: for every downstream consumer of the corpus (search, MCP, analytics), what fields does it read? Are all those fields populated by the bulk phase? If not, the bulk phase is not done — it queues a follow-up job or it's a documented incomplete state.

This audit is that check for the current bootstrap. Future bootstraps repeat the process.

**Second rule (added 2026-07-06 after the P3 type-cleanup discovery)**: **any new bulk phase must also filter by document type**. `discover_corpus_gaps` filtered by anchor + AI-concept classification but not by `type`; the result was a mix of non-paper entities in the "corpus." Downstream stages assumed everything was a paper. Explicit type whitelist at the source of the bulk write is cheaper than corpus cleanup after the fact.

**Third rule (added 2026-07-06 after the Qdrant filter-index gap)**: **the shape of a bulk-read filter changes with corpus scale — treat it as a load-bearing decision, not incidental syntax**. A filter that used an unindexed payload field was fine at 100 K corpus and fatal at 6 M. Every bulk-scroll reader in `src/core/storage/reader.py` should either filter on an already-indexed field, add its own index at collection creation, or bound the scan with an indexed `fetched_at` / `snapshot_filled_at` range. Payload indexing is not a performance tweak — it is a correctness precondition for the enrichment pipeline at real corpus scale.

**Fourth rule (added 2026-07-08 after the true-incremental overhaul)**: **"incremental" is a property each stage must enforce, not a property the script name grants**. Before 2026-07-07, `run_incremental_pipeline.sh` Steps 5/6/7/10 default-swept their full corpus-wide backlogs — the reader filters said "everything not yet processed", and at bootstrap scale "not yet processed" was millions of papers. A run meant to fill a 33-day gap became a 3.97 M-paper keyword sweep and a 13 h labeling job, and the operator only noticed when the wall-clock exploded. Every stage in an incremental pipeline must accept and enforce an explicit scope bound (`--recent-days` → indexed `fetched_at` range); a stage without one silently degrades into a bulk job the moment the corpus outgrows its backlog. Corollary: an index-only filter shape matters even for logically-incremental stages — Step 9's mark-and-skip logic was correct, but its `must` clause on the unindexed `resolved_references` still forced a full scan until it was rewritten to filter on indexed fields (`graph_indexed`, `is_stub`) and check the unindexed field client-side.

**One companion note on runtime deps**: the GROBID fallback (Step 4b/4c, added 2026-07-07) auto-starts its Docker container and needs the **aarch64-built image** (`grobid-arm64:latest`) — the upstream `lfoppiano/grobid` is amd64-only and silently fails `/api/isalive` on the DGX Spark. If Step 4b logs `[SKIP]`, check `docker images | grep grobid` first.

---

## References

- [`docs/design/vllm-labeling-migration.md`](vllm-labeling-migration.md) — the labeling migration triggered by this audit's #1 gap.
- [`docs/runbooks/embed-drain-strategy.md`](../runbooks/embed-drain-strategy.md) — the embed drain phase covering gap #2.
- [`docs/incidents/2026-07-03-mcp-search-endpoints-broken.md`](../incidents/2026-07-03-mcp-search-endpoints-broken.md) — the sibling category of "bulk-writes-something-search-doesn't-expect" bugs.
- [`docs/runbooks/snapshot-bootstrap.md`](../runbooks/snapshot-bootstrap.md) — will be updated with post-bootstrap catchup pointers.
