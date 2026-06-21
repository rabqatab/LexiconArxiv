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
