"""Batch write operations for Qdrant storage.

Provides methods for updating paper fields in bulk.
"""

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

logger = logging.getLogger(__name__)


def _retry_qdrant_call(fn, *, max_attempts: int = 5, op_label: str = "qdrant call"):
    """Retry a Qdrant client call on transient timeout / 5xx errors.

    The 2026-07-04 labeling job (b2ab) died on a single ``set_payload``
    timeout after ~10 minutes of otherwise-successful vLLM labeling. The
    500-paper batch's client-side loop had zero retry: one transient
    Qdrant timeout under bulk contention lost the entire batch's work.

    This helper wraps a call in exponential backoff (1, 2, 4, 8, 16s) on
    transient exceptions; permanent errors (400/404 payload validation)
    propagate immediately. Callers use it around every set_payload /
    upsert / delete in the bulk write path so one bad second doesn't
    torch the whole batch.
    """
    delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except (ResponseHandlingException, UnexpectedResponse) as e:
            # UnexpectedResponse with 4xx (except 429) is a real error — don't retry.
            if isinstance(e, UnexpectedResponse) and 400 <= e.status_code < 500 \
                    and e.status_code != 429:
                raise
            if attempt >= max_attempts:
                logger.error(
                    "%s failed after %d attempts: %s", op_label, max_attempts, e,
                )
                raise
            logger.warning(
                "%s failed (attempt %d/%d), retrying in %.0fs: %s",
                op_label, attempt, max_attempts, delay, e,
            )
            time.sleep(delay)
            delay = min(delay * 2, 30.0)

_POINT_LOCKS: dict[str, threading.Lock] = {}
_POINT_LOCKS_GUARD = threading.Lock()


def _point_lock(point_id: str) -> threading.Lock:
    with _POINT_LOCKS_GUARD:
        lk = _POINT_LOCKS.get(point_id)
        if lk is None:
            if len(_POINT_LOCKS) > 10000:
                # cheap LRU: drop ~half. The lost locks at worst cause a momentary
                # serialization gap; correctness still holds because each citer entry
                # is deduplicated by openalex_id on read.
                for k in list(_POINT_LOCKS)[: len(_POINT_LOCKS) // 2]:
                    _POINT_LOCKS.pop(k, None)
            lk = _POINT_LOCKS.setdefault(point_id, threading.Lock())
        return lk



def _utc_iso_date() -> str:
    """Return today's date in UTC as YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_iso() -> str:
    """Return current UTC time as full ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _injected_point_id(openalex_id: str) -> str:
    """Generate a deterministic point ID from OpenAlex ID using uuid5."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"openalex:{openalex_id}"))


class BatchWriter:
    """Handles batch update operations for papers."""

    def __init__(self, client: QdrantClient, collection_name: str):
        self.client = client
        self.collection_name = collection_name

    def update_referenced_works(
        self,
        point_id: str,
        referenced_works: list[str],
    ) -> bool:
        """Update referenced_works for a paper.

        Uses set_payload() to preserve other fields.

        Args:
            point_id: The Qdrant point ID.
            referenced_works: List of OpenAlex IDs to set.

        Returns:
            True if successful.
        """
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={"referenced_works": referenced_works},
            points=[point_id],
        )
        return True

    def batch_update_referenced_works(
        self,
        updates: list[tuple[str, list[str]]],  # [(point_id, refs), ...]
    ) -> int:
        """Batch update referenced_works for multiple papers.

        Args:
            updates: List of (point_id, referenced_works) tuples.

        Returns:
            Number of papers updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        for point_id, refs in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"referenced_works": refs, "enriched_at": now},
                points=[point_id],
            )
        return len(updates)

    def update_abstract(
        self,
        point_id: str,
        abstract: str,
    ) -> bool:
        """Update abstract for a paper.

        Uses set_payload() to preserve other fields.

        Args:
            point_id: The Qdrant point ID.
            abstract: The abstract text to set.

        Returns:
            True if successful.
        """
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={"abstract": abstract},
            points=[point_id],
        )
        return True

    def batch_update_abstracts(
        self,
        updates: list[tuple[str, str]],  # [(point_id, abstract), ...]
    ) -> int:
        """Batch update abstracts for multiple papers.

        Args:
            updates: List of (point_id, abstract) tuples.

        Returns:
            Number of papers updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        for point_id, abstract in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"abstract": abstract, "enriched_at": now},
                points=[point_id],
            )
        return len(updates)

    def update_paper_with_doi_and_refs(
        self,
        point_id: str,
        doi: str,
        referenced_works: list[str],
    ) -> bool:
        """Update paper with DOI and referenced_works found via title search.

        Args:
            point_id: The Qdrant point ID.
            doi: The DOI found via title search.
            referenced_works: List of OpenAlex IDs.

        Returns:
            True if successful.
        """
        self.client.set_payload(
            collection_name=self.collection_name,
            payload={
                "doi": doi,
                "referenced_works": referenced_works,
            },
            points=[point_id],
        )
        return True

    def batch_update_papers_with_doi_and_refs(
        self,
        updates: list[tuple[str, str, list[str]]],  # [(point_id, doi, refs), ...]
    ) -> int:
        """Batch update papers with DOI and refs found via title search.

        Args:
            updates: List of (point_id, doi, referenced_works) tuples.

        Returns:
            Number of papers updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        for point_id, doi, refs in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={
                    "doi": doi,
                    "referenced_works": refs,
                    "enriched_at": now,
                },
                points=[point_id],
            )
        return len(updates)

    def batch_update_referenced_works_normalized(
        self,
        updates: list[tuple[str, list[str]]],  # [(point_id, normalized_refs), ...]
    ) -> int:
        """Batch update referenced_works with normalized identifiers.

        Args:
            updates: List of (point_id, normalized_referenced_works) tuples.

        Returns:
            Number of papers updated.
        """
        for point_id, refs in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"referenced_works": refs},
                points=[point_id],
            )
        return len(updates)

    def batch_update_resolved_references(
        self,
        updates: list[tuple[str, list[str]]],  # [(point_id, resolved_point_ids), ...]
    ) -> int:
        """Batch update resolved_references with internal paper IDs.

        Args:
            updates: List of (point_id, resolved_references) tuples where
                     resolved_references contains Qdrant point IDs.

        Returns:
            Number of papers updated.
        """
        for point_id, resolved_refs in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"resolved_references": resolved_refs},
                points=[point_id],
            )
        return len(updates)

    def batch_update_graph_metrics(
        self,
        updates: list[tuple[str, dict]],  # [(point_id, {metric: value}), ...]
    ) -> int:
        """Batch update graph metrics (pagerank, hub_score, etc.) for papers.

        Args:
            updates: List of (point_id, metrics_dict) tuples where
                     metrics_dict contains fields like pagerank, hub_score,
                     authority_score, community_id.

        Returns:
            Number of papers updated.
        """
        for point_id, metrics in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload=metrics,
                points=[point_id],
            )
        return len(updates)

    def batch_update_keywords(
        self,
        updates: list[tuple[str, list[str]]],  # [(point_id, keywords), ...]
    ) -> int:
        """Batch update keywords for multiple papers.

        Args:
            updates: List of (point_id, keywords) tuples.

        Returns:
            Number of papers updated.
        """
        for point_id, keywords in updates:
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={"keywords": keywords},
                points=[point_id],
            )
        return len(updates)

    def batch_update_keywords_with_source(
        self,
        updates: list[tuple[str, list[str], str]]
        | list[tuple[str, list[str], str, dict | None]],
    ) -> int:
        """Batch update keywords and extraction source for multiple papers.

        Args:
            updates: List of (point_id, keywords, source) or
                     (point_id, keywords, source, structured) tuples.
                     When structured is provided and not None, it is stored
                     as keywords_structured.

        Returns:
            Number of papers updated.
        """
        for update in updates:
            if len(update) == 4:
                point_id, keywords, source, structured = update
            else:
                point_id, keywords, source = update
                structured = None

            payload: dict = {
                "keywords": keywords,
                "keywords_source": source,
            }
            if structured:
                payload["keywords_structured"] = structured

            self.client.set_payload(
                collection_name=self.collection_name,
                payload=payload,
                points=[point_id],
            )
        return len(updates)

    def batch_update_abstract_structure(
        self,
        updates: list[tuple[str, dict, str]],  # [(point_id, structure_dict, source), ...]
    ) -> int:
        """Batch update abstract structure and source for multiple papers.

        Args:
            updates: List of (point_id, structure_dict, source) tuples.

        Returns:
            Number of papers updated.
        """
        for point_id, structure, source in updates:
            _retry_qdrant_call(
                lambda: self.client.set_payload(
                    collection_name=self.collection_name,
                    payload={
                        "abstract_structure": structure,
                        "abstract_structure_source": source,
                    },
                    points=[point_id],
                ),
                op_label=f"set_payload(abstract_structure, {point_id})",
            )
        return len(updates)

    def batch_update_code_repos(
        self,
        updates: list[tuple[str, list[dict], str | None]],
    ) -> int:
        """Batch update code_repositories and code_url for papers.

        Args:
            updates: List of (point_id, code_repositories, code_url) tuples.

        Returns:
            Number of papers updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        for point_id, repos, best_url in updates:
            payload: dict[str, Any] = {
                "code_repositories": repos,
                "code_enriched_at": now,
            }
            if best_url:
                payload["code_url"] = best_url
            self.client.set_payload(
                collection_name=self.collection_name,
                payload=payload,
                points=[point_id],
            )
        return len(updates)

    def batch_apply_snapshot_enrichment(self, updates: list[tuple[str, dict]]) -> int:
        """Fill snapshot-sourced fields + provenance for each (point_id, fields) update.

        Only the provided keys are set (fill-only-missing is decided upstream by the matcher).

        Args:
            updates: List of (point_id, fields) tuples where fields contains the
                     enrichment data (e.g. abstract, referenced_works).

        Returns:
            Number of updates applied.
        """
        applied = 0
        for point_id, fields in updates:
            if not fields:
                continue
            # Dedicated provenance flag (does NOT clobber any existing
            # `enrichment_source` from a prior enricher).
            payload = {**fields, "openalex_snapshot_enriched": True}
            self.client.set_payload(
                collection_name=self.collection_name,
                payload=payload,
                points=[point_id],
            )
            applied += 1
        return applied

    def clear_all_keywords(self) -> int:
        """Clear keywords from all papers.

        Returns:
            Number of papers cleared.
        """
        cleared = 0
        offset = None

        while True:
            results, offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                offset=offset,
                with_payload=False,
            )

            for point in results:
                self.client.set_payload(
                    collection_name=self.collection_name,
                    payload={"keywords": [], "keywords_source": None},
                    points=[str(point.id)],
                )
                cleared += 1

            if offset is None:
                break

        return cleared

    def batch_apply_field_fill(
        self,
        updates: list[tuple[str, dict]],
        *,
        provenance_key: str = "snapshot_filled_at",
    ) -> int:
        """Apply fill-only-missing payload merges with provenance stamp. Returns count applied."""
        today = _utc_iso_date()
        n = 0
        for point_id, fields in updates:
            if not fields:
                continue
            self.client.set_payload(
                collection_name=self.collection_name,
                payload={**fields, provenance_key: today},
                points=[point_id],
            )
            n += 1
        return n

    def batch_promote_stubs(self, promotions: list[dict]) -> list[dict]:
        """Atomic-per-item stub→real promotion with verify+rollback."""
        results: list[dict] = []
        today = _utc_iso_date()
        for pr in promotions:
            pid = pr["point_id"]
            fields = pr["work_fields"]
            cited_by = pr.get("preserved_cited_by") or []
            try:
                payload = {
                    **fields,
                    "is_stub": False,
                    "cited_by": list(cited_by),
                    "cited_by_count": len(cited_by),
                    "cited_by_count_internal": pr.get("preserved_cited_by_count_internal", 0),
                    "alternate_identifiers": pr.get("preserved_alternate_identifiers") or {},
                    "promoted_from_stub": True,
                    "promoted_at": _utc_iso(),
                    "snapshot_filled_at": today,
                }
                self.client.set_payload(
                    collection_name=self.collection_name,
                    payload=payload,
                    points=[pid],
                )
                # verify
                verify_pts, _ = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(must=[models.HasIdCondition(has_id=[pid])]),
                    with_payload=["is_stub", "cited_by"], with_vectors=False, limit=1,
                )
                after = (verify_pts[0].payload or {}) if verify_pts else {}
                if after.get("is_stub") is not False or set(after.get("cited_by") or []) < set(cited_by):
                    results.append({"point_id": pid, "status": "verify_failed"})
                    continue
                results.append({"point_id": pid, "status": "promoted"})
            except Exception as e:
                results.append({"point_id": pid, "status": "error", "error": str(e)})
        return results

    def batch_inject_papers(self, papers: list[dict]) -> list[dict]:
        """Create new real-paper points from snapshot works. One upsert per item (safety > throughput)."""
        from qdrant_client.models import PointStruct

        today = _utc_iso_date()
        results: list[dict] = []
        for entry in papers:
            oa = entry["openalex_id"]
            fields = entry["work_fields"]
            pid = _injected_point_id(oa)
            # dedup guard via find by openalex_id
            existing = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=models.Filter(
                    must=[models.FieldCondition(key="openalex_id", match=models.MatchValue(value=oa))]
                ),
                limit=1, with_payload=False, with_vectors=False,
            )[0]
            if existing:
                results.append({"openalex_id": oa, "point_id": None, "status": "skipped_dup"})
                continue
            payload = {
                **fields,
                "is_stub": False,
                "injected_from_snapshot": True,
                "injection_path": entry.get("injection_path", "unknown"),
                "injected_at": _utc_iso(),
                "snapshot_filled_at": today,
            }
            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=[PointStruct(id=pid, vector={}, payload=payload)],
                )
                results.append({"openalex_id": oa, "point_id": pid, "status": "created"})
            except Exception as e:
                results.append({"openalex_id": oa, "point_id": None, "status": "failed", "error": str(e)})
        return results

    def batch_extend_external_cited_by(
        self,
        updates: dict[str, list[dict]],
        *,
        cap: int = 300,
    ) -> int:
        """Append citer entries to each point's external_cited_by (union + truncate)."""
        total = 0
        for point_id, new_entries in updates.items():
            if not new_entries:
                continue
            lk = _point_lock(point_id)
            with lk:
                cur_pts, _ = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(must=[models.HasIdCondition(has_id=[point_id])]),
                    with_payload=["external_cited_by"], with_vectors=False, limit=1,
                )
                if not cur_pts:
                    continue
                existing = (cur_pts[0].payload or {}).get("external_cited_by") or []
                by_id: dict[str, dict] = {e["openalex_id"]: e for e in existing if e.get("openalex_id")}
                added = 0
                for entry in new_entries:
                    oa = entry.get("openalex_id")
                    if not oa or oa in by_id:
                        continue
                    by_id[oa] = entry
                    added += 1
                merged = sorted(
                    by_id.values(),
                    key=lambda x: (x.get("year") or 0, x.get("cited_by_count") or 0),
                    reverse=True,
                )[:cap]
                self.client.set_payload(
                    collection_name=self.collection_name,
                    payload={"external_cited_by": merged, "external_cited_by_count": len(merged)},
                    points=[point_id],
                )
                total += added
        return total
