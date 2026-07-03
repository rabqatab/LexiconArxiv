"""Regression for 2026-07-03 polish: get_corpus_stats returned 1.6MB / 38K
lines because the formatter dumped every one of ~thousands of unique venues.
This test locks in the bounded top-N + tail-summary contract."""

from src.mcp.formatters import format_corpus_stats


def _many_venues(n: int) -> dict[str, int]:
    # Descending counts so ordering is deterministic
    return {f"Venue{i:04d}": (n - i) for i in range(n)}


def test_top_venues_capped_at_default_30():
    venue_stats = _many_venues(500)
    out = format_corpus_stats(
        total=1_000_000, real=800_000, stubs=200_000, venue_stats=venue_stats
    )
    # Only 30 venue bullets, not 500
    assert out.count("\n- Venue") == 30
    # Long-tail footer with exact remaining count and tail sum
    assert "…and 470 more venues" in out
    # Tail sum = sum of counts[30:] = sum(500-i for i in 30..499)
    tail = sum(500 - i for i in range(30, 500))
    assert f"covering {tail:,} papers" in out


def test_explicit_top_venues_respected():
    venue_stats = _many_venues(50)
    out = format_corpus_stats(
        total=100, real=100, stubs=0, venue_stats=venue_stats, top_venues=10
    )
    assert out.count("\n- Venue") == 10
    assert "…and 40 more venues" in out


def test_below_limit_no_footer():
    """If we have 5 venues and ask for top 30, show all 5 with no '…and N more'."""
    venue_stats = _many_venues(5)
    out = format_corpus_stats(
        total=15, real=15, stubs=0, venue_stats=venue_stats, top_venues=30
    )
    assert out.count("\n- Venue") == 5
    assert "…and" not in out
    # Heading reflects actual count, not the ceiling we passed
    assert "## Top 5 Venues (of 5)" in out


def test_empty_corpus_no_venue_section():
    out = format_corpus_stats(
        total=0, real=0, stubs=0, venue_stats={}, top_venues=30
    )
    assert "**Distinct venues:** 0" in out
    assert "## Top" not in out
    assert "…and" not in out


def test_zero_top_venues_shows_only_summary():
    """A caller who only wants the header numbers can pass top_venues=0."""
    venue_stats = _many_venues(500)
    out = format_corpus_stats(
        total=1_000_000, real=800_000, stubs=200_000,
        venue_stats=venue_stats, top_venues=0,
    )
    assert "\n- Venue" not in out
    # Still reports the tail so caller knows the distinct-venue count
    assert "…and 500 more venues" in out


def test_response_size_bounded_for_realistic_corpus():
    """Direct guard against the 1.6MB regression: even with 5000 venues and
    default top-30, response stays well under 10KB."""
    venue_stats = _many_venues(5000)
    out = format_corpus_stats(
        total=3_600_000, real=1_400_000, stubs=2_200_000, venue_stats=venue_stats
    )
    assert len(out) < 10_000, f"response too large: {len(out)} bytes"


def test_numbers_use_thousands_separators():
    """Readability check: 3600000 → '3,600,000'."""
    out = format_corpus_stats(
        total=3_600_000, real=1_400_000, stubs=2_200_000,
        venue_stats={"NeurIPS": 12345},
    )
    assert "3,600,000" in out
    assert "1,400,000" in out
    assert "12,345" in out
