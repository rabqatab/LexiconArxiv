# OpenAlex Snapshot → Qdrant Payload Field Mapping

This is the source-of-truth mapping from the **49 fields** in an OpenAlex `works`
snapshot record to the payload keys Lexicon Arxiv stores on a real paper point.

| OpenAlex field | Payload key | Filled by | Notes |
|---|---|---|---|
| `id` | `openalex_id` | P1, P2 (full), P3 (full) | Normalized to just the `W...` ID, no URL prefix |
| `doi` | `doi` | P1, P2 (full), P3 (full) | Lowercased; `https://doi.org/` / `doi:` prefixes stripped |
| `title` / `display_name` | `title` | P2 (full), P3 (full) | P1 never overwrites title |
| `publication_year` | `year` | P2, P3 | |
| `publication_date` | `publication_date` | P2, P3 | |
| `language` | `language` | P1 | |
| `type` | `type` | P2, P3 | |
| `authorships[].author.display_name` | `authors[].display_name` | P2, P3 | |
| `authorships[].author.orcid` | `orcid_map` | P1 | `{display_name: orcid_url}` |
| `concepts[]` | `concepts` | P1 | List as-is from snapshot |
| `topics[]` | `topics` | P1 | |
| `primary_topic` | `primary_topic` | P1 | |
| `primary_location.source.display_name` | `venue` | P2, P3 | |
| `best_oa_location.pdf_url` | `best_oa_pdf_url` | P1 | Free OA full text |
| `referenced_works[]` | `referenced_works` | P2, P3 | Raw OpenAlex Work IDs; NOT resolved to internal point IDs |
| `abstract_inverted_index` | `abstract` | P2, P3 (via `reconstruct_abstract`) | |
| `cited_by_count` | `cited_by_count` | P1, P2, P3 | Global (snapshot-time) count |
| `counts_by_year` | `counts_by_year` | P1 | Citation velocity |
| `fwci` | `fwci` | P1 | Field-weighted citation impact |
| `citation_normalized_percentile` | `citation_normalized_percentile` | P1 | |
| `mesh` | `mesh` | P1 | Biomedical only |
| `sustainable_development_goals` | `sustainable_development_goals` | P1 | |
| `funders` | `funders` | P1 | |
| `institutions` | `institutions` | P1 | |
| `open_access` | `open_access` | P1 | |
| `is_retracted` | `is_retracted` | P2, P3 | Only emitted when `True` |

## Payload keys we DO NOT take from the snapshot

| Payload key | Reason |
|---|---|
| `cited_by` | Built by `build_cited_by_index` from corpus-internal `resolved_references`. Snapshot does not know about our point IDs. |
| `resolved_references` | Same — internal-only, built by `ReferenceResolver`. |
| `pagerank`, `hub_score`, `authority_score`, `community_id` | Computed by `analyze_graph` over the in-memory NetworkX graph. |
| `abstract_structure` | Built by the labeling pipeline (granite4.1:8b). |
| Section / dense vectors | Built by the embedding pipeline. |
| `external_cited_by`, `external_cited_by_count` | Built by P4 (writes from snapshot, but the field is OURS, not OpenAlex's). |

## Provenance keys (always added when a phase touches a point)

| Key | Written by | Value |
|---|---|---|
| `snapshot_filled_at` | P1, P2, P3 (any snapshot pass) | UTC date `YYYY-MM-DD` |
| `live_filled_at` | live mode (Plan 5) | UTC date `YYYY-MM-DD` |
| `promoted_from_stub` | P2 promotion | `True` |
| `promoted_at` | P2 promotion | UTC ISO timestamp |
| `injected_from_snapshot` | P3 injection | `True` |
| `injection_path` | P3 injection | `"anchor"` or `"concept"` |
| `injected_at` | P3 injection | UTC ISO timestamp |
