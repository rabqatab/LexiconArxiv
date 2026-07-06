# LexiconArxiv — TODO

Tracked enhancement backlog. Items are grouped by priority and area.

---

## High Priority

### Critical Data Quality
- [x] **Deduplicator doesn't check Qdrant** — The in-memory `Deduplicator` only deduplicates within a single collection run. Incremental runs re-add papers already in the corpus (e.g., 4,919 AAAI papers added twice, inflating 153K to 159K). Fix: check `storage.queries.exists_by_doi()` or `exists_by_openalex_id()` before inserting. Then deduplicate existing duplicates in v3.
- [x] **Qdrant filter-index gap — 5 missing payload indices caused today's cascading incremental fatals** (fixed 2026-07-06 in-incident) — Incremental cycles `830c` / `d582` / `7e38` all died at Step 2/3a with server-side 60-148 s `scroll_by_id` / `retrieve` timeouts. Root cause: enrichers filter on unindexed payload fields (`abstract`, `referenced_works`), so Qdrant does a 6.2 M-point full scan every batch. Fixed by adding online payload indices on `abstract_structure_source`, `injected_from_snapshot`, `snapshot_filled_at`, `year`, `type`; adding server-side `fetched_since` filter to `get_papers_missing_abstracts` + `get_papers_missing_references`; wiring `--recent-days` through enrich-6/enrich-4/enrich-2 CLIs; wrapping bulk-scroll reads in `_retry_qdrant_call`. Rule added to [`docs/design/bulk-vs-incremental-audit.md`](../design/bulk-vs-incremental-audit.md) §Third rule and runbook at [`docs/runbooks/qdrant-tuning.md`](../runbooks/qdrant-tuning.md) §Payload indices. Follow-ups queued as Wave 1e items below.
- [ ] **[Wave 4c] Corpus CS-relevance cleanup — delete ~2.4 M non-CS papers, gate P2/P3 durably** (proposed 2026-07-06) — Full plan: [`2026-07-06-corpus-cs-cleanup.md`](2026-07-06-corpus-cs-cleanup.md). Corpus audit (100 K sample) shows only 32.6 % of the 3.56 M non-stub real papers are AI/NLP-adjacent by `primary_topic.field`. Two-thirds (~2.38 M) are Medicine / Engineering / Biochemistry / Physics / Environmental / Business / Materials / etc. — cross-domain references pulled in by anchor+concept P3 injection with no topic gate. Plan is 4 phases: (1) dry-run + reversibility rehearsal, (2) durable `KEEP_FIELDS = {CS, Math, Decision Sci, Neuroscience, Psychology} ∪ subfield=Language-and-Linguistics` gate added to P2 and P3 code paths, (3) one-shot filter delete + downstream cleanup + analytics recompute, (4) chronological chunking of the now-~950 K labeling backlog. Trigger: post-catchup-stable. Whitelist policy explicitly reasoned in the plan (Neuroscience for brain-inspired models, Psychology for cog sci / psycholinguistics, Ling subfield for pure linguistics under Arts and Humanities).
- [ ] **Corpus quality audit — cross-provenance review** (discovered 2026-07-06) — Two intertwined issues found during catchup labeling. The item covers both.
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
- [ ] **Enrich high-value stubs** — 23,960 stubs cited by 20+ core papers have zero metadata (no title, abstract, authors). Enrich via OpenAlex by identifier (DOI/arXiv/OpenAlex ID). Target: top 25K stubs.
- [ ] **Resolve TITLE: stubs** — Many stubs have `identifier_type=title` with raw title strings from GROBID. Search OpenAlex by title to find DOI/metadata and merge.
- [ ] **Corpus gap dashboard** — Dashboard section showing: top 100 most-cited stubs (= most-cited papers NOT in corpus), venues most referenced but not collected, stubs that could be promoted.
- [ ] **Stub → core promotion** — When incremental collection adds a paper matching an existing stub, preserve the stub's `cited_by` data on the promoted paper. Verify dedup handles this correctly.

### Pipeline Performance
- [x] **S2 multi-key rotation** — `S2_API_KEYS` env var supports comma-separated keys with round-robin rotation and per-key rate limiting/cooldown.
- [x] **Incremental collection force=True for non-OpenAlex sources** — ACL, DBLP, OpenReview, ACM, AAAI now support forced re-collection.
- [x] **OpenAlex 429 handling + publication_year fallback** — Graceful handling of 429 rate limits with key cooldown. `from_updated_date` falls back to `publication_year` filtering when Premium plan is unavailable.
- [x] **--recent-days for S2 enricher** — Prioritize recently collected papers for incremental enrichment.
- [x] **S2 enricher scroll optimization** — Added `must_not: [is_stub=true]` to `get_papers_missing_references()` and `get_papers_without_doi_missing_references()`. Reduced scroll from 666K to 7K papers.
- [x] **QdrantStorage `fetched_since` passthrough** — Fixed the storage facade to forward `fetched_since` parameter to underlying query methods.
- [x] **OpenReview missing `httpx` import** — Fixed runtime import error in OpenReview collector.
- [ ] **Similarity graph performance** — At 7.4s/paper (3.5M point collection), computing similarity for 120K papers takes ~10 days. Needs: (a) reduce collection size by deleting old v1/v2 collections, (b) pre-filter to only search among papers with vectors, (c) consider approximate methods or incremental-only computation for new papers.

### Advanced Retrieval Pipeline
- [x] **Advanced Retrieval Pipeline (HyDE, multi-vector, reranker, citation boost, MMR)** — HyDE generates hypothetical abstracts for vague queries. Multi-vector prefetch searches section-level vectors fused with RRF. Cross-encoder reranking via Qwen3-Reranker-0.6B. Citation-aware score boosting. MMR diversity post-processing.
- [x] **research_topic API and MCP tool** — Dedicated endpoint and MCP tool for topic-oriented research exploration.
- [ ] **Research API paper type filter** — Add option to exclude benchmark/dataset papers from `/api/research` results (currently filtered client-side).
- [ ] **Venue name normalization** — "ICLR 2025 Poster" should match filter "ICLR". Add `venue_canonical` field or use substring matching.

### Advanced Query Processing
- [ ] **RAG-Fusion** — Generate 3-5 query variants via LLM, search each, fuse with RRF. +8-10% accuracy. Qdrant prefetch supports natively.
- [ ] **Query decomposition** — "BERT vs GPT for code" → 3 sub-queries targeting different section vectors.

---

## Medium Priority

### Stub Vectors & Search
- [ ] **Embed enriched stubs** — Once high-value stubs have abstracts, embed them (dense + BM25). Enables cross-boundary similarity and makes stubs discoverable in search.
- [ ] **BM25 on enriched stubs** — Stubs with titles/abstracts get BM25 vectors so users can find cited papers even if not in core corpus.

### Retrieval Enhancements
- [ ] **SPLADE sparse vectors** — Replace BM25 with learned sparse retrieval (SPLADE++). +10-20% over BM25 but requires re-indexing.
- [ ] **Neural PRF (2-pass)** — Average top-5 result vectors with query for refined second pass. +26% MAP.
- [ ] **Adaptive weighted RRF** — Dynamically weight dense vs BM25 based on query characteristics.

### Configurable Pipeline
- [ ] **RetrievalConfig dataclass** — Toggle each technique on/off via API parameters and server defaults.
- [ ] **Pipeline presets** — "Fast" (default), "Quality" (+ HyDE + reranker), "Comprehensive" (+ RAG-Fusion + MMR).
- [ ] **Pipeline info in response** — Return which stages were applied, detected intent, vectors searched, etc.

---

## Lower Priority

### Data Quality
- [ ] **Stub dedup audit** — Multiple stubs may refer to the same paper via different identifiers. Verify merge logic is comprehensive.
- [ ] **Zero-title stubs investigation** — Investigate why `enrich-8-metadata-by-stub-via-openalex` didn't populate titles. May need to re-run or fix the enricher.

### Search UX
- [ ] **Export (BibTeX/CSV/JSON)** — PRD Section 5.4 feature. Export search results for use in papers.
- [ ] **Saved queries & alerts** — PRD Section 5.4 feature. Save searches and get notified on new matching papers.

### Advanced Techniques
- [ ] **GRF (Generative Relevance Feedback)** — More sophisticated than HyDE. +17-24% nDCG@10 but higher latency.
- [ ] **ColBERT late interaction** — Overkill at 152K scale when cross-encoder reranking is available.

### Future External API Integrations (MCP candidates)
- [ ] **Unpaywall** — Free OA PDF URLs by DOI. Trivial to add, high user value.
- [ ] **DBLP API** — Structured author/venue queries ("all papers by X at Y"). Complements semantic search.
- [ ] **Hugging Face Papers** — Model-paper linking, trending ML papers.
- [ ] **OpenCitations** — Citation context (the sentence where A cites B). Deep analysis.
- [ ] **CORE API** — 200M+ open access full-text search beyond abstracts.
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

- [ ] **Apply ponytail-audit cuts** — ~1800 lines, 4 deps removable. **Trigger:** apply only after snapshot bootstrap completes + corpus is verified stable for ≥1 week. See `docs/refactoring/2026-06-24-ponytail-audit.md` for the ranked list and apply-procedure.
