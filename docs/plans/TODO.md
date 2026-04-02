# LexiconArxiv — TODO

Tracked enhancement backlog. Items are grouped by priority and area.

---

## High Priority

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
- [ ] **ColBERT late interaction** — Overkill at 145K scale when cross-encoder reranking is available.

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
