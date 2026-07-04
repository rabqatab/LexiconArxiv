# Archived Plans — `docs/plans/`

These are historical implementation plans whose deliverables are shipped and no longer part of the active roadmap. Kept for provenance and archaeology only. **For the live backlog, see [`../TODO.md`](../TODO.md).**

Do not treat any file here as a source of truth for current behavior — it captures how something was planned, not necessarily how the shipped code works today.

| File | Shipped in | Notes |
|---|---|---|
| [`2026-02-15-multiple-openalex-keys-design.md`](2026-02-15-multiple-openalex-keys-design.md) + [plan](2026-02-15-multiple-openalex-keys-plan.md) | v0.11.1 | Multi-key OpenAlex round-robin + rate limiting. |
| [`2026-03-18-phase1-embedding-pipeline.md`](2026-03-18-phase1-embedding-pipeline.md) | v0.11 | Qwen3-Embedding-8B + Matryoshka. |
| [`2026-03-18-phase2-search-api.md`](2026-03-18-phase2-search-api.md) | v0.11 | Hybrid search (dense + BM25 RRF), search API. |
| [`2026-03-18-phase3-mcp-server.md`](2026-03-18-phase3-mcp-server.md) | v0.11 | Initial MCP server. Superseded by MCP polish waves in v0.13.2 (see [`../../reference/mcp-server.md`](../../reference/mcp-server.md)). |
| [`2026-03-18-phase4-on-demand-retrieval.md`](2026-03-18-phase4-on-demand-retrieval.md) | v0.11 | On-demand arXiv+OpenAlex expansion with core/connected/external labeling. |
| [`2026-03-18-phase5-trends-notable.md`](2026-03-18-phase5-trends-notable.md) | v0.11 | Notable-paper scoring + trends UI. |

## Related archives

- Superpowers plans (Dagster, snapshot utilization, LLM migration): [`../../superpowers/plans/archive/`](../../superpowers/plans/archive/)
- Post-bootstrap catchup / vLLM Phase 1 / labeling gap runtime discoveries are documented in place under [`../../runbooks/`](../../runbooks/), [`../../design/`](../../design/), and the [`README.md`](../../../README.md) v0.13.3 changelog.
