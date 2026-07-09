# Snapshot Live Mode

Daily catch-up pass that keeps the corpus current between quarterly bootstrap
runs. Same phase logic as the bootstrap (Plans 1–4), driven by the OpenAlex
public API instead of the local snapshot files.

## What it does

`live_worker.run_live_delta()` performs ONE pass:

1. **Build phase indexes once** from the current corpus state
   (`iter_all_real_papers_minimal`, `iter_stubs_for_resolution`,
   `build_identifier_index_for_dedup`, `build_referenced_openalex_id_set`,
   `build_openalex_id_to_point_id_map`).
2. **Fetch the delta** from `iter_live_works(since=yesterday)` —
   OpenAlex `/works?filter=from_updated_date:YYYY-MM-DD` with cursor pagination.
3. **For each work, chain `process_one` across all four phases:**
   P1 (metadata fill) → P2 (stub→real promotion) → P3 (gap discovery + inject)
   → P4 (external_cited_by extension). P2/P3 apply the Wave 4c topic gate
   automatically (shared `process_one`), so live mode won't re-introduce the
   non-CS papers Wave 4c demoted — see [`corpus-gap-discovery.md`](corpus-gap-discovery.md) §Topic gate.
4. **Update the per-phase high-water marks** so re-running the same delta date
   is a no-op (each phase is independently fill-only-missing / dedup-guarded).

## Where it differs from bootstrap

| Aspect | Bootstrap (Plans 1–4) | Live mode (Plan 5) |
|---|---|---|
| Work source | Snapshot files on disk | OpenAlex API `/works` filtered by date |
| Cadence | Manual, quarterly (1 day for full pass) | Daily, cron-scheduled |
| Phase ordering | Per-phase batches (all P1, then all P2…) | Per-work chain (each work through all 4) |
| Embedding drain | Operator runs `embed-papers --consume-snapshot-queue` between phases | Same drain command; runs as a separate step or on the next cron |

## Triggers

- **CLI:** `uv run python -m src.cli.core_collect snapshot-live-delta [--days-back N | --since YYYY-MM-DD] [--dry-run] [--max-injections N]`
- **Dagster:** `snapshot_live_delta` asset (`snapshot_live_delta_job`), scheduled by
  `daily_snapshot_live_schedule` (cron `0 5 * * *` Asia/Seoul). **Default:
  STOPPED** — operator explicitly enables after the bootstrap is stable.

## Operational notes

- Idempotency: re-running the same `--since` date is safe. Each phase is
  fill-only-missing (P1, P2 enrich path) or dedup-guarded (P2 promotion, P3
  injection, P4 union).
- Rate limits: OpenAlex polite-pool (10 requests/sec with `mailto`). The worker
  passes `OPENALEX_EMAIL` from env. For ~few-thousand-work daily deltas this is
  comfortably under limit.
- Failure modes: per-work exceptions are caught + counted; the pass continues.
  Aggregate `worker_errors` surfaces in the summary. The HWM is updated only on
  a clean pass (not on early exit from `--max-injections`).
