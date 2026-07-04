# Archived Superpowers Plans

Implementation plans that shipped and are no longer active. Kept for provenance. Live docs about the running system are under `docs/design/`, `docs/runbooks/`, and `docs/pipelines/`.

## Contents

| File | Shipped in | Superseded / follow-ups |
|---|---|---|
| [`2026-06-03-dagster-orchestration-phase1.md`](2026-06-03-dagster-orchestration-phase1.md) | v0.13.0 | Dagster foundation. Live status: see `MEMORY.md` [dagster-orchestration-status](../../../../.claude/projects/-home-alphabridge-LexiconArxiv/memory/project_dagster_status.md). |
| [`2026-06-17-dagster-orchestration-phase2.md`](2026-06-17-dagster-orchestration-phase2.md) | v0.13.0 | Phase 2 asset graph. |
| [`2026-06-18-open-source-llm-migration.md`](2026-06-18-open-source-llm-migration.md) | v0.12 | Gemini → Ollama migration. **Superseded 2026-07-04 by Path B** — see [`docs/design/vllm-labeling-migration.md`](../../../design/vllm-labeling-migration.md) and [`docs/design/bulk-vs-incremental-audit.md`](../../../design/bulk-vs-incremental-audit.md) §Ollama→vLLM policy. Under Path B, Ollama chat is retired from every pipeline stage; Ollama continues only for embedding + search-time HyDE + query embed. |
| [`2026-06-18-openalex-snapshot-offline-resolution.md`](2026-06-18-openalex-snapshot-offline-resolution.md) | v0.13.0 | Enrich-from-snapshot as bypass for the OpenAlex title-search 429 bottleneck. Live tool: `enrich-from-openalex-snapshot`. Memory pointer: [openalex-snapshot-offline-resolution](../../../../.claude/projects/-home-alphabridge-LexiconArxiv/memory/reference_openalex_snapshot.md). |
| [`2026-06-21-snapshot-utilization-plan1-foundation.md`](2026-06-21-snapshot-utilization-plan1-foundation.md) | v0.13.0 | Snapshot foundation. Live docs: `docs/pipelines/{stub-promotion,corpus-gap-discovery,snapshot-live-mode}.md`. |
| [`2026-06-21-snapshot-utilization-plan2-p1-p4.md`](2026-06-21-snapshot-utilization-plan2-p1-p4.md) | v0.13.0 | The 4-phase bootstrap chain (P1 metadata fill, P2 stub promotion, P3 gap discovery, P4 external_cited_by). Live runbook: [`docs/runbooks/snapshot-bootstrap.md`](../../../runbooks/snapshot-bootstrap.md). **Important follow-up:** the 2026-07-04 bulk-vs-incremental audit ([`docs/design/bulk-vs-incremental-audit.md`](../../../design/bulk-vs-incremental-audit.md)) found that P1-P4 alone is not enough — the post-bootstrap catchup runbook fills the 7 downstream gaps this plan didn't cover. |
| [`2026-06-21-snapshot-utilization-plan3-p2-promotion.md`](2026-06-21-snapshot-utilization-plan3-p2-promotion.md) | v0.13.0 | P2 stub → real promotion detail. |
| [`2026-06-21-snapshot-utilization-plan4-p3-gaps.md`](2026-06-21-snapshot-utilization-plan4-p3-gaps.md) | v0.13.0 | P3 corpus gap discovery detail. |
| [`2026-06-23-snapshot-utilization-plan5-live-mode.md`](2026-06-23-snapshot-utilization-plan5-live-mode.md) | v0.13.0 | Daily OpenAlex API delta chain. Live pipeline doc: [`docs/pipelines/snapshot-live-mode.md`](../../../pipelines/snapshot-live-mode.md). |

## Still-active plans (NOT archived)

These remain in `docs/superpowers/plans/` because they are deferred, not shipped:

- `2026-06-17-dagster-orchestration-phase3.md` — DQ asset_checks. Partial (labeling-gap DQ shipped 2026-07-04); rest still on the deferred list.
- `2026-06-17-dagster-orchestration-phase4.md` — Dagster schedules for the snapshot chain. All schedules `STOPPED` by default; enabled only after post-bootstrap catchup completes stably per [`docs/runbooks/post-bootstrap-catchup.md`](../../../runbooks/post-bootstrap-catchup.md).

## Superseding docs to consult instead

- Labeling backend: [`docs/design/vllm-labeling-migration.md`](../../../design/vllm-labeling-migration.md)
- Post-bootstrap steps: [`docs/runbooks/post-bootstrap-catchup.md`](../../../runbooks/post-bootstrap-catchup.md)
- Bulk-vs-incremental pipeline audit: [`docs/design/bulk-vs-incremental-audit.md`](../../../design/bulk-vs-incremental-audit.md)
- Qdrant tuning: [`docs/runbooks/qdrant-tuning.md`](../../../runbooks/qdrant-tuning.md)
- Code overhaul plan (post-bootstrap deferred): [`docs/refactoring/2026-07-04-code-overhaul-plan.md`](../../../refactoring/2026-07-04-code-overhaul-plan.md)
