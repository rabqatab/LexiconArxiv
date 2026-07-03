"""Regression + design lock-in for the 2026-07-03 60s-hang incident.

Motivation: `get_paper_by_arxiv_id` scrolled an unindexed `source_id` field
and blocked for 60s before erroring. The index fix landed, but there's no
guardrail that stops the *next* unindexed lookup from doing the same.
`_dispatch` now wraps every handler in `asyncio.wait_for` with a strict
5s default budget (per-handler overrides for legitimately slow endpoints).

These tests hit `_dispatch` directly rather than the `@app.call_tool()`
wrapper so they don't depend on MCP SDK internals."""

import asyncio

import pytest
from mcp.types import TextContent

from src.mcp import server


@pytest.mark.asyncio
async def test_dispatch_returns_result_within_budget(monkeypatch):
    """A fast handler under budget returns its payload cleanly."""

    async def fast_handler(_arguments):
        return [TextContent(type="text", text="ok")]

    monkeypatch.setitem(server._HANDLERS, "search_papers", fast_handler)
    result = await server._dispatch("search_papers", {})
    assert result[0].text == "ok"


@pytest.mark.asyncio
async def test_dispatch_times_out_slow_handler(monkeypatch):
    """A handler exceeding its budget returns a diagnostic timeout message."""

    async def slow_handler(_arguments):
        await asyncio.sleep(1.0)
        return [TextContent(type="text", text="never returned")]

    monkeypatch.setitem(server._HANDLERS, "search_papers", slow_handler)
    # Tighten the default so the test doesn't wait 5 real seconds
    monkeypatch.setattr(server, "_DEFAULT_HANDLER_TIMEOUT_SEC", 0.05)
    # Ensure no override rescues this handler
    monkeypatch.setattr(server, "_HANDLER_TIMEOUTS", {})

    result = await server._dispatch("search_papers", {})
    text = result[0].text
    assert "exceeded" in text
    assert "search_papers" in text
    # Diagnostic hint — future-us should be able to guess the failure mode
    assert "unindexed" in text


@pytest.mark.asyncio
async def test_dispatch_per_handler_override_wins(monkeypatch):
    """A slow-but-legitimate handler uses its explicit longer budget."""

    call_deadline = 0.15  # research_topic override raised for this test

    async def deliberate_handler(_arguments):
        await asyncio.sleep(0.10)  # under the 0.15 override, over the 0.05 default
        return [TextContent(type="text", text="research done")]

    monkeypatch.setitem(server._HANDLERS, "research_topic", deliberate_handler)
    monkeypatch.setattr(server, "_DEFAULT_HANDLER_TIMEOUT_SEC", 0.05)
    monkeypatch.setattr(
        server, "_HANDLER_TIMEOUTS", {"research_topic": call_deadline}
    )

    result = await server._dispatch("research_topic", {})
    assert result[0].text == "research done"


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error():
    result = await server._dispatch("no_such_tool", {})
    assert "Unknown tool" in result[0].text


@pytest.mark.asyncio
async def test_dispatch_handler_exception_is_caught(monkeypatch):
    """Handler exceptions surface as text — do not propagate to MCP client."""

    async def broken(_arguments):
        raise ValueError("simulated backend explosion")

    monkeypatch.setitem(server._HANDLERS, "search_papers", broken)
    result = await server._dispatch("search_papers", {})
    assert "Error" in result[0].text
    assert "simulated backend explosion" in result[0].text


def test_all_registered_tools_have_handlers():
    """Every tool advertised in the schema must have a dispatch entry, else
    call_tool will return 'Unknown tool' for it — silent breakage."""

    # Names declared in the tool schema — must match _HANDLERS keys exactly
    advertised = {
        "search_papers",
        "get_paper",
        "get_citations",
        "get_corpus_stats",
        "get_similar_papers",
        "expand_search",
        "research_topic",
        "get_mcp_version",
    }
    assert advertised == set(server._HANDLERS.keys())


def test_slow_handler_overrides_are_sane():
    """Guard against a typo like 60.0 becoming 6.0 in the overrides table.
    Every override must be >= the default (otherwise it'd be tightening,
    not loosening, which is a footgun — use the default instead)."""

    for name, timeout in server._HANDLER_TIMEOUTS.items():
        assert timeout >= server._DEFAULT_HANDLER_TIMEOUT_SEC, (
            f"{name} override {timeout}s is TIGHTER than default "
            f"{server._DEFAULT_HANDLER_TIMEOUT_SEC}s — this makes no sense"
        )
