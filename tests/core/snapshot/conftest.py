"""In-memory storage stub for L1/L2 snapshot tests."""
import json
from pathlib import Path

import pytest


class _MockStorage:
    """In-memory dict-backed storage stub.

    Methods cover every storage call the snapshot phases make. New methods
    are added here as storage extensions land in Plan 1 Tasks 10-20.
    """

    def __init__(self) -> None:
        self._payloads: dict[str, dict] = {}
        self._vectors: set[str] = set()

    # core
    def set_payload(self, point_id: str, payload: dict) -> None:
        existing = self._payloads.get(point_id, {})
        existing.update(payload)
        self._payloads[point_id] = existing

    def get_payload(self, point_id: str) -> dict | None:
        return self._payloads.get(point_id)

    def scroll_payloads(self) -> list[tuple[str, dict]]:
        return list(self._payloads.items())

    def seed_from_json(self, path: Path) -> None:
        for entry in json.loads(path.read_text()):
            self._payloads[entry["point_id"]] = dict(entry["payload"])

    def has_vector(self, point_id: str) -> bool:
        return point_id in self._vectors

    def vector_set(self, point_id: str) -> None:
        self._vectors.add(point_id)

    def count_with_filter(
        self,
        *,
        must_not_is_stub: bool = False,
        must_is_stub: bool = False,
        missing_field: str | None = None,
    ) -> int:
        n = 0
        for _, p in self._payloads.items():
            if must_not_is_stub and p.get("is_stub") is True:
                continue
            if must_is_stub and p.get("is_stub") is not True:
                continue
            if missing_field is not None and p.get(missing_field):
                continue
            n += 1
        return n

    # ----- read helpers used by phases -----
    def iter_all_real_papers_minimal(self, batch_size: int = 1000):
        from src.core.deduplication import Deduplicator
        for pid, pl in self._payloads.items():
            if pl.get("is_stub") is True:
                continue
            title = pl.get("title")
            yield {
                "point_id": pid,
                "doi": pl.get("doi"),
                "openalex_id": pl.get("openalex_id"),
                "title": title,
                "title_norm": Deduplicator.normalize_title(title) if title else None,
            }

    def build_referenced_openalex_id_set(self) -> dict:
        out: dict = {}
        for pid, pl in self._payloads.items():
            if pl.get("is_stub") is True:
                continue
            for ref in pl.get("referenced_works") or []:
                wid = ref.rsplit("/", 1)[-1] if isinstance(ref, str) else None
                if wid and wid.startswith("W"):
                    out[wid] = out.get(wid, 0) + 1
        return out

    def build_openalex_id_to_point_id_map(self) -> dict:
        out: dict = {}
        for pid, pl in self._payloads.items():
            if pl.get("is_stub") is True:
                continue
            if oa := pl.get("openalex_id"):
                out[oa] = pid
        return out

    def build_identifier_index_for_dedup(self) -> dict:
        from src.core.deduplication import Deduplicator
        out = {"doi": set(), "openalex_id": set(), "title_norm": set()}
        for _, pl in self._payloads.items():
            if pl.get("doi"):
                out["doi"].add(pl["doi"])
            if pl.get("openalex_id"):
                out["openalex_id"].add(pl["openalex_id"])
            if pl.get("title"):
                n = Deduplicator.normalize_title(pl["title"])
                if n:
                    out["title_norm"].add(n)
        return out

    def iter_stubs_for_resolution(self, batch_size: int = 500):
        for pid, pl in self._payloads.items():
            if pl.get("is_stub") is not True:
                continue
            yield {
                "point_id": pid,
                "identifier": pl.get("identifier"),
                "identifier_type": pl.get("identifier_type"),
                "doi": pl.get("doi"),
                "arxiv_id": pl.get("arxiv_id"),
                "openalex_id": pl.get("openalex_id"),
                "title": pl.get("title"),
                "year": pl.get("year"),
                "first_author": None,
                "authors": pl.get("authors") or [],
                "cited_by": list(pl.get("cited_by") or []),
                "cited_by_count_internal": pl.get("cited_by_count_internal", 0),
                "alternate_identifiers": pl.get("alternate_identifiers") or {},
            }

    def find_real_by_identifier(self, fields: dict) -> str | None:
        for pid, pl in self._payloads.items():
            if pl.get("is_stub") is True:
                continue
            for key in ("doi", "openalex_id", "arxiv_id"):
                if (v := fields.get(key)) and pl.get(key) == v:
                    return pid
        return None

    def merge_stub_into_real(self, stub_pid: str, real_pid: str) -> None:
        if stub_pid == real_pid:
            raise ValueError("cannot merge a point into itself")
        stub = self._payloads.get(stub_pid)
        real = self._payloads.get(real_pid)
        if not stub or not real:
            return
        merged = sorted(set(stub.get("cited_by") or []) | set(real.get("cited_by") or []))
        real["cited_by"] = merged
        real["cited_by_count"] = len(merged)
        real["alternate_identifiers"] = {**(real.get("alternate_identifiers") or {}), **(stub.get("alternate_identifiers") or {})}
        del self._payloads[stub_pid]

    # ----- write helpers -----
    def batch_apply_field_fill(self, updates, *, provenance_key: str = "snapshot_filled_at") -> int:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        n = 0
        for pid, fields in updates:
            if not fields:
                continue
            self.set_payload(pid, {**fields, provenance_key: today})
            n += 1
        return n

    def batch_promote_stubs(self, promotions) -> list[dict]:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        results = []
        for pr in promotions:
            pid = pr["point_id"]
            fields = pr["work_fields"]
            cited_by = pr.get("preserved_cited_by") or []
            self.set_payload(pid, {
                **fields,
                "is_stub": False,
                "cited_by": list(cited_by),
                "cited_by_count": len(cited_by),
                "cited_by_count_internal": pr.get("preserved_cited_by_count_internal", 0),
                "alternate_identifiers": pr.get("preserved_alternate_identifiers") or {},
                "promoted_from_stub": True,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_filled_at": today,
            })
            results.append({"point_id": pid, "status": "promoted"})
        return results

    def batch_inject_papers(self, papers) -> list[dict]:
        from datetime import datetime, timezone
        import uuid
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        results = []
        for entry in papers:
            oa = entry["openalex_id"]
            # dedup by openalex_id
            dup = any(pl.get("openalex_id") == oa for pl in self._payloads.values())
            if dup:
                results.append({"openalex_id": oa, "point_id": None, "status": "skipped_dup"})
                continue
            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"openalex:{oa}"))
            self._payloads[pid] = {
                **entry["work_fields"],
                "is_stub": False,
                "injected_from_snapshot": True,
                "injection_path": entry.get("injection_path", "unknown"),
                "injected_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_filled_at": today,
            }
            results.append({"openalex_id": oa, "point_id": pid, "status": "created"})
        return results

    def batch_extend_external_cited_by(self, updates: dict, *, cap: int = 300) -> int:
        total = 0
        for pid, new_entries in updates.items():
            if pid not in self._payloads:
                continue
            existing = self._payloads[pid].get("external_cited_by") or []
            by_id = {e["openalex_id"]: e for e in existing if e.get("openalex_id")}
            for entry in new_entries:
                oa = entry.get("openalex_id")
                if not oa or oa in by_id:
                    continue
                by_id[oa] = entry
                total += 1
            merged = sorted(by_id.values(),
                            key=lambda x: (x.get("year") or 0, x.get("cited_by_count") or 0),
                            reverse=True)[:cap]
            self._payloads[pid]["external_cited_by"] = merged
            self._payloads[pid]["external_cited_by_count"] = len(merged)
        return total


@pytest.fixture
def mock_storage() -> _MockStorage:
    return _MockStorage()
