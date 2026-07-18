"""Tests for stub→core reconciliation (promote stub shadowed by a real paper).

Uses a tiny in-memory fake that interprets the subset of Qdrant filters the
reconcile path builds: FieldCondition(MatchValue) and HasIdCondition.
"""

from types import SimpleNamespace

from src.core.storage.stubs import StubManager


class FakeClient:
    def __init__(self, points):
        # points: list of dicts {id, payload}
        self.points = {p["id"]: dict(p["payload"]) for p in points}

    # --- filter interpreter (only what reconcile uses) ---
    @staticmethod
    def _match(payload, cond):
        if hasattr(cond, "has_id") and cond.has_id is not None:
            return None  # handled by caller (id membership)
        key = getattr(cond, "key", None)
        m = getattr(cond, "match", None)
        if key is not None and m is not None and hasattr(m, "value"):
            return payload.get(key) == m.value
        return True  # unhandled (e.g. DatetimeRange) → don't constrain

    def _ids_from_hasid(self, flt):
        for cond in (flt.must or []):
            if hasattr(cond, "has_id") and cond.has_id is not None:
                return set(cond.has_id)
        return None

    def scroll(self, collection_name, scroll_filter=None, limit=10, offset=None,
               with_payload=None, with_vectors=None):
        flt = scroll_filter
        hasid = self._ids_from_hasid(flt) if flt else None
        out = []
        for pid, payload in list(self.points.items()):
            if hasid is not None and pid not in hasid:
                continue
            ok = True
            for cond in (getattr(flt, "must", None) or []):
                if hasattr(cond, "has_id") and cond.has_id is not None:
                    continue
                if self._match(payload, cond) is False:
                    ok = False
                    break
            for cond in (getattr(flt, "must_not", None) or []):
                if self._match(payload, cond) is True:
                    ok = False
                    break
            if ok:
                out.append(SimpleNamespace(id=pid, payload=dict(payload)))
            if len(out) >= limit:
                break
        return out, None

    def set_payload(self, collection_name, payload, points):
        for pid in points:
            self.points[pid].update(payload)

    def delete(self, collection_name, points_selector):
        for pid in points_selector.points:
            self.points.pop(pid, None)


def _mgr(points):
    return StubManager(FakeClient(points), "test")


REAL = {"id": "R1", "payload": {"doi": "10.1/x"}}                       # real paper, no is_stub
STUB = {"id": "S1", "payload": {"doi": "10.1/x", "is_stub": True,
                                "cited_by": ["C1", "C2"]}}              # its shadow stub
REAL2 = {"id": "R2", "payload": {"doi": "10.1/y"}}                      # real, no stub


def test_find_stub_by_identifier():
    mgr = _mgr([REAL, STUB, REAL2])
    assert mgr.find_stub_by_identifier({"doi": "10.1/x"}) == "S1"
    assert mgr.find_stub_by_identifier({"doi": "10.1/y"}) is None


def test_reconcile_promotes_and_preserves_cited_by():
    mgr = _mgr([REAL, STUB, REAL2])
    stats = mgr.reconcile_stub_duplicates(dry_run=False)
    assert stats["promoted"] == 1
    # stub gone, its cited_by folded onto the real paper
    assert "S1" not in mgr.client.points
    assert set(mgr.client.points["R1"]["cited_by"]) == {"C1", "C2"}


def test_reconcile_dry_run_mutates_nothing():
    mgr = _mgr([REAL, STUB, REAL2])
    stats = mgr.reconcile_stub_duplicates(dry_run=True)
    assert stats["promoted"] == 1
    assert "S1" in mgr.client.points                       # not deleted
    assert "cited_by" not in mgr.client.points["R1"]       # not merged
