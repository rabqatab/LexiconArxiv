from pathlib import Path

from src.core.snapshot import embedding_queue as q


def test_append_then_drain(tmp_path: Path):
    q.append("p-1", "promotion", root=tmp_path)
    q.append("p-2", "injection", root=tmp_path)
    assert q.depth(root=tmp_path) == 2
    out = list(q.drain(root=tmp_path))
    assert out == [("p-1", "promotion"), ("p-2", "injection")]
    assert q.depth(root=tmp_path) == 0


def test_cancel_removes_entry(tmp_path: Path):
    q.append("p-1", "promotion", root=tmp_path)
    q.append("p-2", "injection", root=tmp_path)
    q.cancel("p-1", root=tmp_path)
    out = list(q.drain(root=tmp_path))
    assert out == [("p-2", "injection")]


def test_persistence_across_processes(tmp_path: Path):
    q.append("p-1", "promotion", root=tmp_path)
    # simulate restart by calling again from "scratch"
    assert q.depth(root=tmp_path) == 1
    out = list(q.drain(root=tmp_path))
    assert out == [("p-1", "promotion")]


def test_duplicate_append_dedupes_on_drain(tmp_path: Path):
    q.append("p-1", "promotion", root=tmp_path)
    q.append("p-1", "promotion", root=tmp_path)
    out = list(q.drain(root=tmp_path))
    assert out == [("p-1", "promotion")]


# --- explicit-ack pattern (peek_all + remove) — survives consumer crash ---


def test_peek_all_does_not_clear_queue(tmp_path: Path):
    """Regression for 2026-06-30 incident: peek_all must be idempotent."""
    q.append("p-1", "promotion", root=tmp_path)
    q.append("p-2", "injection", root=tmp_path)
    first = q.peek_all(root=tmp_path)
    assert first == [("p-1", "promotion"), ("p-2", "injection")]
    # If consumer crashed here, second peek must return the SAME items
    second = q.peek_all(root=tmp_path)
    assert second == first
    assert q.depth(root=tmp_path) == 2


def test_remove_acknowledges_processed_items(tmp_path: Path):
    q.append("p-1", "promotion", root=tmp_path)
    q.append("p-2", "injection", root=tmp_path)
    q.append("p-3", "promotion", root=tmp_path)
    items = q.peek_all(root=tmp_path)
    # process p-1 and p-2 successfully, then ack just those
    q.remove(items[:2], root=tmp_path)
    remaining = q.peek_all(root=tmp_path)
    assert remaining == [("p-3", "promotion")]


def test_remove_is_idempotent(tmp_path: Path):
    """Calling remove with items already gone is a no-op."""
    q.append("p-1", "promotion", root=tmp_path)
    items = q.peek_all(root=tmp_path)
    q.remove(items, root=tmp_path)
    assert q.peek_all(root=tmp_path) == []
    # Second remove with the same items — must not error
    q.remove(items, root=tmp_path)
    assert q.peek_all(root=tmp_path) == []


def test_consumer_crash_does_not_lose_items(tmp_path: Path):
    """Simulate the 2026-06-30 incident: consumer reads, crashes, retries.

    The legacy drain() loses the items on the first call (file cleared).
    The new peek_all/remove pattern keeps them until explicit ack."""
    for i in range(5):
        q.append(f"p-{i}", "promotion", root=tmp_path)

    # First consumer attempt — peek then "crash" before remove()
    items = q.peek_all(root=tmp_path)
    assert len(items) == 5
    # ...consumer crashes here without calling remove()...

    # Second consumer attempt — items must still be there
    items_again = q.peek_all(root=tmp_path)
    assert items_again == items
    # Now process and ack
    q.remove(items_again, root=tmp_path)
    assert q.peek_all(root=tmp_path) == []


def test_legacy_drain_emits_deprecation_warning(tmp_path: Path):
    """drain() still works but warns operators to migrate."""
    import warnings
    q.append("p-1", "promotion", root=tmp_path)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = list(q.drain(root=tmp_path))
        assert any(issubclass(warning.category, DeprecationWarning) for warning in w)
    assert out == [("p-1", "promotion")]
