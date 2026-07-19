# LexiconArxiv — TODO

Tracked enhancement backlog. Items are grouped by priority and area.

---

## High Priority

### Critical Data Quality
- [x] **Deduplicator doesn't check Qdrant** — The in-memory `Deduplicator` only deduplicates within a single collection run. Incremental runs re-add papers already in the corpus (e.g., 4,919 AAAI papers added twice, inflating 153K to 159K). Fix: check `storage.queries.exists_by_doi()` or `exists_by_openalex_id()` before inserting. Then deduplicate existing duplicates in v3.
- [x] **True-incremental overhaul — first end-to-end incremental completion** (2026-07-08, v0.13.4) — After 7 failed attempts (830c → 7a34), run `6283` (v8) completed all 10 steps in ~1.5 h. Shipped: `--recent-days` on every eligible stage (keywords/labeling/resolve-refs/embed + all enrichers), GROBID Step 4b/4c with arm64 Docker auto-start, Step 9 index-only filter, `graph_indexed` index, 25-sentence vLLM truncation contract. Fourth rule added to [`bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md): "incremental" is a property each stage must enforce, not one the script name grants. Wave 1e-quinquies/-sexies closed in the [overhaul plan](../refactoring/2026-07-04-code-overhaul-plan.md).
- [x] **Qdrant filter-index gap — 5 missing payload indices caused today's cascading incremental fatals** (fixed 2026-07-06 in-incident) — Incremental cycles `830c` / `d582` / `7e38` all died at Step 2/3a with server-side 60-148 s `scroll_by_id` / `retrieve` timeouts. Root cause: enrichers filter on unindexed payload fields (`abstract`, `referenced_works`), so Qdrant does a 6.2 M-point full scan every batch. Fixed by adding online payload indices on `abstract_structure_source`, `injected_from_snapshot`, `snapshot_filled_at`, `year`, `type`; adding server-side `fetched_since` filter to `get_papers_missing_abstracts` + `get_papers_missing_references`; wiring `--recent-days` through enrich-6/enrich-4/enrich-2 CLIs; wrapping bulk-scroll reads in `_retry_qdrant_call`. Rule added to [`docs/design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §Third rule and runbook at [`docs/runbooks/qdrant-tuning.md`](../runbooks/qdrant-tuning.md) §Payload indices. Follow-ups queued as Wave 1e items below.
- [x] **[Wave 4c] Corpus CS-relevance cleanup — gate P2/P3 durably + demote non-CS** (done 2026-07-09) — Full record: [`2026-07-06-corpus-cs-cleanup.md`](2026-07-06-corpus-cs-cleanup.md) §8. Corpus was only 32.6 % AI-adjacent. Shipped: durable `topic_gate.is_keep_topic` at P2/P3 (`KEEP_FIELDS = {CS, Math, Decision Sci, Neuroscience, Psychology} ∪ subfield Language-and-Linguistics`) + 2 provenance-scoped DQ checks; **demoted (not deleted) 2,483,834 non-CS P2/P3 papers to stubs** — non-stub 3.74 M → 1.26 M, MCP search ~2× faster (p50 433 → 200 ms). Chose demote over delete (hard delete reclaimed only ~35 GB); crawler papers protected by provenance clause. **Remaining → Phase 4** (below).
- [x] **[Wave 4c Phase 4/4b] Label + re-embed the 2020+ keep-set** (done 2026-07-17) — vLLM-labeled 2025-26 (2,109) + 2020-24 (103,297) at ~6 K/hr; **pre-2020 deliberately skipped** (recent = search-relevant). Then re-embedded 113,033 papers to generate `section-*` vectors (indexed_vectors 2.3 M → 3.19 M) — without this the labels never reached search. Search verified hybrid + section-level. Enablers committed: `label-abstracts --year-min/--year-max`, stub-exclusion in the labeling filter, `scripts/analytics/reembed_labeled_sections.py`. Also fixed MCP search's silent `bm25_only` fallback (embed-model startup preload + 30 s timeouts). **Remaining sub-items:** pre-2020 labeling (skipped, resume if wanted). (Ollama-partial re-label / Issue B — CLOSED 2026-07-17 as unnecessary; same model + no truncation, see §Critical Data Quality. A wider labels-reach-search gap — ~51 K labeled papers missing `section-*` vectors — was found and a 2010+ (~31 K) re-embed run.)
- [x] **Corpus quality audit — cross-provenance review** (discovered 2026-07-06; CLOSED 2026-07-17) — Two intertwined issues found during catchup labeling. **Wave 4c update:** the non-CS slice of Issue A is resolved — most non-article junk (books/peer-reviews/editorials) was cross-domain P2/P3 injection and is now demoted to stubs (out of search). **A1(a) DONE 2026-07-17:** the in-keep-set `type` filter shipped — measured 165 K non-article works inside the CS keep-set, demoted 44,287 clear non-paper types (`book`/`paratext`/`other`/`editorial`/`reference-entry`/`erratum`/`standard`/`retraction`/`peer-review`) to stubs (user "junk-only" policy: KEPT `review`(60.7 K surveys), `book-chapter`, `dissertation`, `report`, `dataset`, `letter`, and all no-type crawler papers). Durable `topic_gate.is_keep_type` gate at P2/P3 + `nonpaper_type_share` DQ warn-check (baseline 0 %). Tooling: `scripts/analytics/{count_type_in_keepset,demote_types_in_keepset}.py`. **Issue B (Ollama re-label) RESOLVED 2026-07-17 — no re-label needed.** Two premises checked and both false: (1) same underlying model — Ollama used `granite4.1:8b`, vLLM uses `ibm-granite/granite-4.1-8b`, so labels are equal quality (the migration was throughput, 750/hr → 30K/hr, not quality); (2) the "Ollama truncates long abstracts" claim is disproven — long-abstract (>1200 char) Ollama-labeled papers carry `result`/`contribution` tail roles **100 %** of the time (vs 97 % for short), so no tail was dropped. Scope was also far smaller than feared: **9,670** Ollama-labeled papers, not ~250 K. The one real gap was **section vectors, not labels** — 964 Ollama-labeled papers (part of a wider ~51 K labeled-but-no-section-vector backlog, mostly vllm 2010+) lacked `section-*` vectors so their labels never reached search. Fixed by re-EMBED (not re-label) — `reembed_labeled_sections.py` now matches vllm OR ollama; 2010+ (~31 K) re-embed run 2026-07-17. **This whole quality-audit item is now closed** (A1(a) type gate + A1(b) re-label verdict both done).
    - **Issue A: non-article types leaked by P3.** P3 injection did not filter OpenAlex `type` field. Sampled 5 random long-abstract papers: 1 `article` (medical structured abstract, legit), 1 `book` (full table-of-contents + preface stored in `abstract`), 1 `peer-review` (26K-char eLife peer-review thread — not a paper at all), 1 `editorial` (opinion piece body-text), 1 more structured medical article. Estimated 10-20% of the P3-injected subset is non-article types with body-text in `abstract`. Impact today: (a) labeling wastes compute, (b) search returns book chapters and peer-review threads as "papers", (c) similarity edges to these are semantically meaningless.
    - **Issue B: Ollama-labeled papers are partial.** The 91K papers labeled during the 2026-07-04 catchup job `be19` used Ollama chat. Ollama silently truncates prompts at its default `num_ctx` (~4-8 K tokens), so long-abstract papers were labeled only from their first ~40 sentences. Downstream: `abstract_structure` for those papers is missing role tags for the tail (usually `result`, `contribution`). Papers touched: 91 K, of which perhaps ~55 % (per the long-abstract distribution) are affected. Also touches the ~152 K papers from the 2026-06-03 incremental run and any pre-Path-B labeling — all with `abstract_structure_source=ollama`.
    - **Fix plan (broadened to cross-provenance):**
        1. **Enumerate type distribution across the ENTIRE corpus** — not just P3 — broken down by provenance (`injected_from_snapshot=true` (P3), `snapshot_filled_at` set but not injected (P2 promotion), rest = original crawler + incremental runs). Report volume per (`type`, `provenance`) cell.
        2. **Design keep/delete policy** — probably keep `article`, `preprint`, `conference-paper`, `dissertation`; drop `book`, `peer-review`, `editorial`, `letter`, `erratum`, `retraction`, `other`. Confirm the policy against a small manual review of borderline types (`book-chapter` — sometimes legitimately a paper).
        3. **Delete non-article points + cleanup refs** — remove from Qdrant + purge references from similarity/cited_by/graph payloads on remaining papers.
        4. **Spot-check original-crawler papers** (~500 K + ~152 K incremental). ArXiv `type=other` and ACL workshop reports may include edge cases. Sample 20 per crawler.
        5. **Re-label Ollama-partial papers with vLLM** — filter to `abstract_structure_source=ollama` (excluding deleted non-articles) and run `label-abstracts --backend vllm --force`. Volume: ~91 K be19 + ~152 K last incremental + prior Ollama-labeled = ~250-400 K papers. Cost: ~10-20 h at vLLM production rate.
        6. **Add DQ warn-check for non-article proportion** so this doesn't recur silently.
        7. **Add `type` filter to `discover_corpus_gaps` (P3)** so the next quarterly bootstrap doesn't reintroduce non-articles.
    - **Trigger: after the post-bootstrap catchup completes stably.** Cross-refs: [`docs/design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §P3 data-quality gap + §Second rule; [`docs/refactoring/2026-07-04-code-overhaul-plan.md`](../refactoring/2026-07-04-code-overhaul-plan.md) §Wave 4b.

### Stub Enrichment & Corpus Gaps
- [~] **Enrich high-value stubs** (A3, 2026-07-17 — structural fix DONE, run low-yield) — The real blocker was **scale**: `get_most_cited_stubs` full-scrolled all 5.0M stubs + sorted in Python on every call, so enrichment never actually reached them. Fixed with an integer index on `cited_by_count_internal` + keyword on `identifier_type` and a server-side `order_by` rewrite (5M-scroll → 39ms; commit `751a401`). **Enrichment yield is inherently low**, though: the highest-cited stubs are ~17% fabricated 6-billion OpenAlex IDs (HTTP 404) and a large share are `S2:`/`title` types enrich-8 can't resolve; only ~470 new ≥20-cite titles landed. **Enricher-hang FIXED 2026-07-17 (commit `8d0ae88`):** the stall root cause was NOT the 20K-task gather (that hypothesis was wrong — bounded chunking alone didn't fix it) but `find_stub_by_alternate_identifier` scrolling `alternate_identifiers.{doi,arxiv,openalex}` — all **unindexed** — over 5M stubs = 60-150s server-side timeout per enriched stub, serialized on the async loop. Indexed the three nested fields → arxiv `--limit 30` went from >100s hang to **7.2s** (30 processed, 7 enriched, 16 merged). Bounded-chunk batching kept as defense-in-depth. **arxiv/doi run DONE 2026-07-17:** arxiv ≥5 went 11,695 → 459 no-title (8,235 processed → 3,173 enriched + **4,603 merged** + 459 not_found, 0 errors — 94 % hit rate; the 4.6 K merges also cleaned duplicate stubs, improving the citation graph); doi ≥5 → 62 resolved / 151 remaining (mostly unreachable IDs). **openalex not run** — ~17 % fabricated 6 B IDs + fast-404 low yield; skip unless needed. Remaining no-title high-value stubs are genuine not-founds (unreachable identifiers).
- [~] **Resolve TITLE: stubs** (code unblocked 2026-07-18, commit `2990ef5`; full run gated) — Root cause was NOT the enricher-hang but a matcher data-shape bug: the 751,936 `identifier_type=title` stubs leave `title` empty and carry the raw GROBID title in `identifier` as `TITLE:<text>`, but `build_stub_index` read only `stub['title']` — so they were **invisible to the snapshot matcher and never resolvable**. Fixed to derive the title from `identifier` (4-word floor drops bare fragments that would collide with generic titles); real-data check: 96.1 % of a 5K sample now index (was 0 %). Online title-search is a per-IP 429 trap ([[openalex-snapshot-offline-resolution]]) so resolution must run through the local 596 GB snapshot (P2 `resolve-stubs-from-snapshot`). **Remaining = the full P2 run** — a multi-hour scan + corpus mutation (promotions/merges); gate on disk headroom (Qdrant-RED memory).
- [x] **Corpus gap dashboard** (2026-07-18, commit 35ca809) — `storage.get_corpus_gaps()` + `/api/corpus-gaps` endpoint + a Data Health Monitor section. Shows the top-100 most-cited **enriched** stubs (most-cited papers NOT in corpus — e.g. "Bleu", "Classifier-Free Diffusion Guidance", "Judging LLM-as-a-Judge") linked to DOI/arXiv/OpenAlex, plus a most-referenced-uncollected-venue tally. Server-side `order_by` on the `cited_by_count_internal` index (317 ms, no full scroll); cached 5 min. "Stubs that could be promoted" is covered by the reconcile-stubs feature above rather than a separate live count (corpus-wide promotable scan is expensive).
- [x] **Stub → core promotion** (2026-07-18, commit `22e2bbe`) — Incremental collection adds a real paper for a work a prior reference already stubbed, leaving two points + orphaned `cited_by` (probe: ~1.77 % of real papers shadow a stub, ~21K corpus-wide). Shipped `reconcile_stub_duplicates` + `find_stub_by_identifier` (indexed doi/openalex/arxiv probes), a `reconcile-stubs` CLI, and **Step 8.5** in the incremental script (before build-cited-by so counts land on the promoted paper). `merge_stub_into_real` preserves cited_by. Bulk-safe (recent-days scoped; bootstrap has no stubs). Unit-tested (in-memory fake). **Optional one-time corpus-wide backfill** (`reconcile-stubs` with no --recent-days) would clean the ~21K existing shadows — moderate mutation, gate it.

### Pipeline Performance
- [x] **S2 multi-key rotation** — `S2_API_KEYS` env var supports comma-separated keys with round-robin rotation and per-key rate limiting/cooldown.
- [x] **Incremental collection force=True for non-OpenAlex sources** — ACL, DBLP, OpenReview, ACM, AAAI now support forced re-collection.
- [x] **OpenAlex 429 handling + publication_year fallback** — Graceful handling of 429 rate limits with key cooldown. `from_updated_date` falls back to `publication_year` filtering when Premium plan is unavailable.
- [x] **--recent-days for S2 enricher** — Prioritize recently collected papers for incremental enrichment.
- [x] **S2 enricher scroll optimization** — Added `must_not: [is_stub=true]` to `get_papers_missing_references()` and `get_papers_without_doi_missing_references()`. Reduced scroll from 666K to 7K papers.
- [x] **QdrantStorage `fetched_since` passthrough** — Fixed the storage facade to forward `fetched_since` parameter to underlying query methods.
- [x] **OpenReview missing `httpx` import** — Fixed runtime import error in OpenReview collector.
- [x] **Similarity graph performance** (A4, 2026-07-17, commit `7f19d48`) — Was 7.4s/paper; the bottleneck was the per-paper `set_payload` write loop, not the query (already a mega-batch). Now writes the whole batch in one `batch_update_points(wait=False)` call + a `--only-missing` incremental mode (453,728 embedded papers → 137,378 without edges) + default batch 20→50. **Verified 0.11s/paper** (200 papers / 21.9s). Full recompute ~14h; incremental `--only-missing` ~4h; daily runs touch only new papers.

### Advanced Retrieval Pipeline
- [x] **Advanced Retrieval Pipeline (HyDE, multi-vector, reranker, citation boost, MMR)** — HyDE generates hypothetical abstracts for vague queries. Multi-vector prefetch searches section-level vectors fused with RRF. Cross-encoder reranking via Qwen3-Reranker-0.6B. Citation-aware score boosting. MMR diversity post-processing.
- [x] **research_topic API and MCP tool** — Dedicated endpoint and MCP tool for topic-oriented research exploration.
- [x] **Research API paper type filter** (2026-07-18, commit `9d1ffdb`) — The `exclude_types` option (benchmark/dataset/survey) already existed end-to-end; it's a post-retrieval title-keyword filter (those are content categories, not payload types — no clean Qdrant filter, and `title` has no text index, so a `must_not` MatchText would need a 6.2M-point index build, disproportionate). Fixed the real defect: the fetch was hardcoded at 50, so excluding many hits could return fewer than the caller's `limit`. Now over-fetches `limit*4` when excluding (else `max(50, limit*2)`). Smoke: limit=10 stays 10 with exclusion on.
- [x] **Venue name normalization** (already shipped) — `venue` carries a Qdrant TEXT index (WORD tokenizer, lowercase) and search uses `MatchText` + a `VENUE_ALIASES` map (`src/core/search/venue_map.py`), so filtering "ICLR" matches "ICLR 2025 Poster" (36,159 pts) and the full-name variant. The `venue_canonical` field the TODO floated as the heavier alternative is unnecessary. Alias map is extensible if new venues need full-name expansion.

### Advanced Query Processing
- [x] **RAG-Fusion** — Shipped (`rag_fusion` flag + `generate_query_variants`). 2026-07-17: added `think:false` so qwen3:8b stops spending the 10s budget on `<think>` tokens (was silently timing out to empty).
- [x] **Query decomposition** (B, 2026-07-17, commit `ff83721`) — `generate_query_decomposition` splits a compound/comparative query into independent sub-questions (qwen3:8b), fused via RRF. Distinct from RAG-Fusion (reformulation). Verified: "BERT vs GPT for code generation" → 3 sub-queries, 2.6s hybrid.

---

## Medium Priority

### Stub Vectors & Search
- [x] **Embed enriched stubs / BM25 on enriched stubs** (B, 2026-07-17, commit `0393472`) — `embed_high_value_stubs.py` embeds cited≥5 abstract-bearing stubs (~10.8K, ~2% index growth) into structured-abstract + full + BM25, flags `searchable_stub=True`. `_build_filters`' stub-exclusion became "is_stub AND NOT searchable_stub", so exactly these high-value cited-but-absent papers surface while the other ~5M stubs stay out of the HNSW (verified 96 flagged → 96 pass, 0 leak). Wave 4c's search-speed win is preserved.

### Retrieval Enhancements
- [ ] **SPLADE sparse vectors** — Replace BM25 with learned sparse retrieval (SPLADE++). +10-20% over BM25 but requires re-indexing. (Deferred — overkill at current scale per note.)
- [x] **Neural PRF (2-pass)** (B, 2026-07-17, commit `ff83721`) — `neural_prf` flag: average the query vector with the top-K result vectors, re-search on structured-abstract. Verified reshaping the ranking (DiffCSE → SimCSE top), +~200ms.
- [x] **Adaptive weighted RRF** (B, 2026-07-17, commit `ff83721`) — `adaptive_rrf` flag: tilt dense-vs-BM25 candidate share by query shape (short/acronym/quoted → BM25; long NL → dense) via per-modality prefetch limits. Unit-tested heuristic.

### Configurable Pipeline
- [x] **RetrievalConfig dataclass / Pipeline presets / Pipeline info** — All shipped (`src/core/search/config.py`: `fast()`/`quality()`/`comprehensive()`; `pipeline.stages_applied`/`vectors_searched` in the response). `comprehensive()` now also enables decomposition + PRF + adaptive RRF (2026-07-17).

---

## Lower Priority

### Data Quality
- [x] **Stub dedup audit** (2026-07-18, closed — merge logic is comprehensive) — Probed 40K stubs: **0 exact-identifier duplicates** (doi or openalex_id shared across two stubs) and **0/3000 cross-identifier duplicates** (a non-openalex stub whose openalex_id matches a separate openalex stub). Two structural defenses make this airtight, not luck: (1) a stub's point ID is `uuid5(identifier)`, so the same identifier collapses to one point at creation; (2) the resolver normalizes every reference to canonical form *before* stub creation, so a paper never spawns two stubs under different identifiers. No action.
- [x] **Zero-title stubs investigation** (2026-07-18, closed — not an enrich-8 bug) — 1,428,697 empty-title stubs (28.6 % of 4.996 M). Breakdown: **title** 751,936 (carry the raw title in `identifier`; resolvable only via the gated P2 snapshot scan, not enrich-8); **openalex** 413,726 (resolvable by ID but ~17 % are fabricated 6-billion IDs that 404, rest mostly low-cited); **arxiv** 100,608 (high-cited already done at 94 % hit, remainder cited < 5); **doi** 15,135 (small reachable remainder, only 1,687 cited ≥ 2). enrich-8 works (proven 94 % arxiv hit); the empty-titles are the gated title/snapshot class, unreachable/fabricated IDs, or low-priority low-cited — not a bug. Actionable reachable slice is small; run enrich-8 on the doi/arxiv cited≥2 tail if wanted.

### Search UX
- [ ] **Export (BibTeX/CSV/JSON)** — PRD Section 5.4 feature. Export search results for use in papers.
- [ ] **Saved queries & alerts** — PRD Section 5.4 feature. Save searches and get notified on new matching papers.

### Advanced Techniques
- [ ] **GRF (Generative Relevance Feedback)** — More sophisticated than HyDE. +17-24% nDCG@10 but higher latency.
- [ ] **ColBERT late interaction** — Overkill at 152K scale when cross-encoder reranking is available.

### Future External API Integrations (MCP candidates)
- [x] **Unpaywall** (2026-07-18) — Free OA PDF URLs by DOI. `UnpaywallEnricher` + `enrich-oa-pdf-by-doi-via-unpaywall` CLI fills `pdf_url` (+`oa_status`) for papers with a DOI but no PDF link. Reader `get_papers_with_doi_missing_pdf` (fetched_at-scoped for incremental); batched writer `batch_update_oa_pdf` (Wave 1e, wait=False, idempotent fill-only-missing). Email via UNPAYWALL_EMAIL/CROSSREF_EMAIL/OPENALEX_EMAIL, no API key. Live-verified (BERT N19-1423 + corpus DOI 10.7717/peerj.5987 → OA gold PDF). Not auto-wired into the pipeline — run on demand, or add a step later. MCP tool can wrap `fetch_oa_pdf` if on-demand resolution is wanted.
- [x] **DBLP API** (2026-07-19) — Structured author/venue/title search. `src/core/external/dblp.py` (`search_dblp` + `parse_dblp_hits`, no key) exposed as MCP tool `dblp_search`. Live-verified.
- [ ] **Hugging Face Papers** — Model-paper linking, trending ML papers.
- [x] **OpenCitations** (2026-07-19) — `src/core/external/opencitations.py` (`get_citation_count` + `get_citing_papers`; v2 API 301-redirects → follow_redirects) exposed as MCP tool `get_open_citations`. Live-verified (count=58). Note: OC gives citation counts + citing DOIs, not the citing *sentence* (that corpus isn't in the index API).
- [x] **CORE API** (2026-07-19) — `src/core/external/core_api.py` (`search_core` + `parse_core_results`, needs `CORE_API_KEY`) exposed as MCP tool `core_fulltext_search`. Full-text OA search beyond abstracts. Gracefully no-ops without the key.
- [x] **Export → Zotero** (2026-07-19) — `src/core/external/zotero.py` (`push_to_zotero` + `paper_to_zotero_item`) + `POST /api/zotero/push` (paper IDs → Zotero Web API; needs `ZOTERO_API_KEY` + `ZOTERO_LIBRARY_ID`, 50-item cap). Chose direct Web API push over BibTeX/RIS file export per user.
- [ ] **ORCID** — Author disambiguation across venues.
- [ ] **Altmetric** — Social media attention, news mentions, trending papers.
- [ ] **PubMed/Europe PMC** — Cross-domain when AI papers reference bio/medical work.

---

## Completed

- [x] Phase 1: Embedding Pipeline (section-level, 9 dense + BM25)
- [x] Phase 2: Search API + Web UI (hybrid search, RRF)
- [x] Phase 3: MCP Server (6 tools)
- [x] Phase 4: On-demand Retrieval (arXiv + OpenAlex)
- [x] Phase 5: Trends & Notable Papers (metrics + UMAP/HDBSCAN)
- [x] Phase 6: Semantic Similarity Graph (5 typed edge types)
- [x] Data Health Dashboard with pipeline alerting
- [x] Keyword autocomplete
- [x] Shared navigation, page titles, venue dropdown, landing state
- [x] Incremental pipeline updated for embedding/similarity/clustering
- [x] Multi-label sentence deduplication in structured-abstract
- [x] Title included in BM25 + dense vectors
- [x] Critical incremental update fixes (HasVectorCondition, partial chunk recovery)
- [x] First incremental crawling-preprocessing loop (152K core papers)
- [x] DBLP 5xx retry with exponential backoff (transient server errors previously dropped silently)
- [x] ACM DL stealth browser PDF downloader (Playwright/Crawl4AI, CPU-only, bypasses Cloudflare for primary ACM venues: KDD, SIGIR, WWW, RecSys, CIKM, WSDM)
- [x] `--doi-prefix` filter and `--retry-incomplete` flag for enrich-5 CLI
- [x] ACM pdf_url backfill for DBLP-sourced papers + orchestrator script
- [x] `sentence-transformers` dependency added for cross-encoder reranking
- [x] Plan doc drift fix (reranker model 8B→0.6B, Ollama→sentence-transformers)

## Refactoring / cleanup (deferred)

- [x] **Apply ponytail-audit cuts** (2026-07-08) — Both the 2026-06-24 list and the fresh 2026-07-07 re-audit applied in one wave: 17 commits, net ≈ −3,600 lines, −4 deps (`feedparser`, `cachetools`, `python-dateutil`, `auto-mix-prep`). Deleted: `src/collectors/`, keyword LLM path, `external_search`, deprecated snapshot runner chain, `get_payload` alias, stale scripts; unified retry (Wave 1e-bis) + title normalizer. Skips (facade dismantle → Wave 5; stub-ID uuid5 → would break 2.6 M persisted IDs; others) recorded with reasons in `docs/refactoring/2026-06-24-ponytail-audit.md` §Application record.
