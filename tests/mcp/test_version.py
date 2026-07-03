"""Regression + design lock-in for the stale-MCP problem: per-Claude-session
subprocesses hold onto old code with no hot reload. get_mcp_version lets a
caller compare the running SHA against `git rev-parse HEAD` on disk."""

import pytest

from src.mcp import server


def test_version_resolves_git_sha():
    """In a git repo, _resolve_mcp_version returns a real short SHA."""
    v = server._resolve_mcp_version()
    # Short SHA is 7 hex chars in git's default; can be longer if abbrev is set
    assert v["sha"] != "unknown"
    assert 4 <= len(v["sha"]) <= 40
    assert all(c in "0123456789abcdef" for c in v["sha"])


def test_version_contains_required_keys():
    v = server._resolve_mcp_version()
    assert set(v.keys()) == {"sha", "startup_ts", "python"}
    # ISO 8601 UTC timestamp with 'Z' or '+00:00' suffix
    assert "T" in v["startup_ts"]
    assert v["python"].count(".") >= 1  # e.g. "3.12.3"


def test_module_version_is_frozen_at_import():
    """_VERSION is captured once at import time — two _resolve calls return
    different startup_ts (each is a fresh call), but the module-level _VERSION
    stays put. This is the whole point: freeze what's answering the tool now."""
    snapshot1 = server._VERSION
    snapshot2 = server._VERSION
    # Same dict identity — not re-resolved between accesses
    assert snapshot1 is snapshot2
    # A fresh _resolve_mcp_version call produces a NEW dict (different timestamps
    # possible, definitely different identity)
    fresh = server._resolve_mcp_version()
    assert fresh is not server._VERSION


@pytest.mark.asyncio
async def test_get_mcp_version_handler_returns_sha_and_startup():
    result = await server._handle_get_mcp_version({})
    text = result[0].text
    assert server._VERSION["sha"] in text
    assert server._VERSION["startup_ts"] in text
    assert server._VERSION["python"] in text
    # Diagnostic hint that tells the caller what to compare against
    assert "git rev-parse HEAD" in text


@pytest.mark.asyncio
async def test_get_mcp_version_survives_missing_git(monkeypatch):
    """If git isn't available (installed as a wheel, sandboxed), the tool must
    still respond with 'unknown' rather than crash the server."""

    def fake_check_output(*args, **kwargs):
        raise FileNotFoundError("git not on PATH")

    monkeypatch.setattr(server.subprocess, "check_output", fake_check_output)
    v = server._resolve_mcp_version()
    assert v["sha"] == "unknown"
    # Other fields still populated — no cascade failure
    assert v["python"]
    assert v["startup_ts"]


@pytest.mark.asyncio
async def test_get_mcp_version_dispatched_through_top_level():
    """End-to-end: _dispatch("get_mcp_version", ...) reaches the handler."""
    result = await server._dispatch("get_mcp_version", {})
    assert "git sha" in result[0].text
