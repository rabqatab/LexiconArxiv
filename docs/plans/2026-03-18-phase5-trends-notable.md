# Phase 5: Trends & Notable Papers — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two-layered analytics: metrics-based notable papers + keyword trends (Layer 1), and embedding-based topic clustering with UMAP+HDBSCAN (Layer 2). Exposed via API endpoints and a trends web UI.

**Architecture:** Layer 1 uses existing Qdrant payloads (citation_count, pagerank, keywords_structured, year). Layer 2 uses paper vectors for UMAP dimensionality reduction + HDBSCAN clustering, stored back as Qdrant payload fields. API routes serve both layers. Trends page visualizes rising keywords and topic map.

**Tech Stack:** scikit-learn (HDBSCAN), umap-learn (UMAP), existing QdrantStorage, FastAPI

**Spec:** `docs/specs/2026-03-18-search-engine-mvp-design.md` — Section 7

---

## File Structure

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/core/analytics/__init__.py` | Package init |
| Create | `src/core/analytics/notable.py` | Notable paper scoring |
| Create | `src/core/analytics/keyword_trends.py` | Keyword time-series analysis |
| Create | `src/core/analytics/clustering.py` | UMAP + HDBSCAN topic clustering |
| Create | `src/api/models/trends.py` | Pydantic models for trends responses |
| Create | `src/api/routes/trends.py` | Trends API router |
| Modify | `src/api/main.py` | Register trends router |
| Create | `src/api/static/trends.html` | Trends visualization page |
| Create | `scripts/analytics/run_clustering.sh` | Clustering recompute script |
| Create | `tests/test_analytics.py` | Unit tests |

**New dependencies:** `umap-learn`, `scikit-learn` (for HDBSCAN)

---

## Task 1: Add dependencies + create Pydantic models

- [ ] Run `uv add umap-learn scikit-learn`
- [ ] Create `src/api/models/trends.py` with models for NotablePaperItem, KeywordTrendItem, TopicCluster, TrendMapPoint, and response types
- [ ] Commit

---

## Task 2: Implement notable paper scoring

`src/core/analytics/notable.py`:
- `score_notable_papers(storage, weights, limit, filters)` → scrolls papers, computes weighted score from citation_count, pagerank, recency, tier
- Formula: `w1*norm(citations) + w2*norm(pagerank) + w3*recency_boost(year) + w4*tier_boost(tier)`
- Returns sorted list of scored papers

Tests: verify scoring formula, verify sorting, verify filters

---

## Task 3: Implement keyword trend analysis

`src/core/analytics/keyword_trends.py`:
- `compute_keyword_trends(storage, category, min_count)` → scrolls papers with keywords_structured, counts keywords per year, computes growth rates
- `get_rising_keywords(storage, top_k, category)` → top-K by growth rate above threshold
- Uses `keywords_structured` payload: `{task, method, model, domain, dataset, contribution_type, modality}`

Tests: verify growth rate calculation, verify filtering by category

---

## Task 4: Implement UMAP + HDBSCAN clustering

`src/core/analytics/clustering.py`:
- `compute_clusters(storage, n_components, min_cluster_size)` → loads vectors from Qdrant, runs UMAP(1024→50d), HDBSCAN, labels clusters via top keywords
- `store_cluster_results(storage, results)` → writes cluster_id, umap_x, umap_y back to Qdrant payloads
- CLI command + shell script for periodic recompute

Tests: verify on small synthetic vector set

---

## Task 5: Create trends API router + wire into app

`src/api/routes/trends.py`:
- `GET /api/trends/notable` — top papers by notable score
- `GET /api/trends/keywords` — keyword frequency time-series
- `GET /api/trends/rising` — fastest-growing keywords
- `GET /api/trends/topics` — topic clusters (if clustering has been computed)
- `GET /api/trends/topics/{id}` — papers in a cluster
- `GET /api/trends/map` — UMAP 2D coordinates for scatter plot

Register router in `src/api/main.py`. Add `/trends` page route.

---

## Task 6: Create trends web UI

`src/api/static/trends.html`:
- Rising keywords bar chart (grouped by category)
- Notable papers ranked list with score breakdown
- 2D topic map scatter plot (UMAP coordinates, clusters color-coded)
- Hover for paper details, click to search within cluster
- Same dark theme as search UI

---

## Execution Checklist

| Task | Description | Estimated Time |
|------|-------------|---------------|
| 1 | Dependencies + Pydantic models | 5 min |
| 2 | Notable paper scoring | 15 min |
| 3 | Keyword trend analysis | 15 min |
| 4 | UMAP + HDBSCAN clustering | 20 min |
| 5 | Trends API router | 10 min |
| 6 | Trends web UI | 15 min |
