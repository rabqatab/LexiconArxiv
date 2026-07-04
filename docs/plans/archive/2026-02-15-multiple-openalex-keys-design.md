# Multiple OpenAlex API Keys Support

**Date**: 2026-02-15
**Status**: Approved

## Problem

OpenAlex rate limits are a bottleneck even with the existing single-key + email fallback mechanism. A single API key provides 100K credits/day, which can be exhausted during large enrichment runs. The email polite pool fallback is too slow (1 concurrent, ~10 req/s) for large-scale operations.

## Solution

Support multiple API keys with round-robin rotation and per-key cooldown tracking. When one key is exhausted, the system transparently rotates to the next available key. Only when ALL keys are exhausted does it fall back to the email polite pool.

## Configuration

```env
# New (multi-key) — comma-separated
OPENALEX_API_KEYS=key1,key2,key3

# Old (still works, treated as single-key pool)
OPENALEX_API_KEY=single_key

# Fallback (unchanged)
OPENALEX_EMAIL=your-email@example.com
```

**Resolution priority**:
1. `OPENALEX_API_KEYS` (comma-separated) — takes precedence
2. `OPENALEX_API_KEY` (single key) — backward compatible fallback
3. `OPENALEX_EMAIL` — polite pool when all keys exhausted

## Architecture

### New: `OpenAlexKeyManager` class

**Location**: `src/core/openalex_keys.py`

```python
class OpenAlexKeyManager:
    """Manages a pool of OpenAlex API keys with round-robin rotation and per-key cooldown."""

    def __init__(self, keys: list[str], email: str | None = None, cooldown: float = 300):
        self._keys: list[str]              # Ordered list of API keys
        self._email: str | None            # Fallback email for polite pool
        self._cooldown: float              # Per-key cooldown (default 5 min)
        self._exhausted: dict[str, float]  # key -> exhaustion timestamp
        self._index: int                   # Round-robin counter

    @classmethod
    def from_env(cls) -> "OpenAlexKeyManager":
        """Factory: reads OPENALEX_API_KEYS or OPENALEX_API_KEY, plus OPENALEX_EMAIL."""

    def get_next_params(self) -> dict[str, str]:
        """Round-robin next available key as {"api_key": key}, or {"mailto": email} if all exhausted."""

    def mark_exhausted(self, key: str) -> None:
        """Mark a key as exhausted with current timestamp."""

    def _recover_keys(self) -> None:
        """Check cooldowns, restore any keys whose cooldown has elapsed."""

    @property
    def has_available_keys(self) -> bool:
        """True if at least one non-exhausted key exists."""

    @property
    def active_key_count(self) -> int:
        """Number of non-exhausted keys."""

    @property
    def total_key_count(self) -> int:
        """Total number of keys in pool."""
```

### Integration: `OpenAlexMixin` (Enrichment Pipeline)

**File**: `src/core/enrichment/base.py`

Replace single-key fields (`api_key`, `_api_key_exhausted`, `_api_key_exhausted_at`, `_api_key_cooldown`) with a `_key_manager: OpenAlexKeyManager` reference.

- `_init_openalex()` accepts optional `key_manager` param, or creates one from env
- `_get_openalex_params()` delegates to `key_manager.get_next_params()`
- `_handle_api_key_exhaustion()` marks the specific used key as exhausted
- `fetch_openalex_work()` tracks which key was used per request, passes it on 429
- Concurrency: original when any key available, reduced to 1 when ALL exhausted, restored when any key recovers

### Integration: `CoreCorpusCollector` (Collection Pipeline)

**File**: `src/core/crawler/openalex.py`

Replace `self.api_key`/`self.email` with `self._key_manager`.

- `__init__()` accepts optional `key_manager` param
- `_build_url()` uses `key_manager.get_next_params()` instead of single key
- Backward compatible: `api_key`/`email` constructor args still accepted, wrapped into a key manager

Both pipelines share the same `OpenAlexKeyManager` instance when used together.

## Rotation Strategy

**Round-robin**: Keys are cycled evenly across requests to distribute credit usage.

- `get_next_params()` increments an index modulo the number of available (non-exhausted) keys
- Exhausted keys are skipped automatically
- When a key's cooldown (5 min) elapses, it re-enters the rotation

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `OPENALEX_API_KEYS` empty/whitespace | Email-only mode |
| Duplicate keys in list | Deduplicate silently, warn in log |
| Both `OPENALEX_API_KEYS` and `OPENALEX_API_KEY` set | `OPENALEX_API_KEYS` takes precedence |
| Single key in `OPENALEX_API_KEYS` | Identical to current single-key behavior |
| All keys exhausted + no email | Anonymous access (empty params), logs WARNING |
| Key recovers mid-batch | Next request picks it up via round-robin |
| Regular 429 (not "Insufficient credits") | Existing 60s backoff retry, key NOT marked exhausted |

## Logging

| Event | Level | Example |
|-------|-------|---------|
| Initialization | INFO | `"OpenAlex key manager: 3 API keys loaded, email=yes"` |
| Key exhausted | WARNING | `"OpenAlex key 1/3 exhausted. 2 keys remaining."` |
| All keys exhausted | WARNING | `"All 3 OpenAlex API keys exhausted. Falling back to email polite pool."` |
| Key recovered | INFO | `"OpenAlex key 1/3 recovered after cooldown. 2/3 keys available."` |
| Round-robin pick | DEBUG | `"Using OpenAlex key 2/3"` |

## Files Changed

| File | Change |
|------|--------|
| `src/core/openalex_keys.py` | **NEW** — `OpenAlexKeyManager` class |
| `src/core/constants.py` | Add `OPENALEX_API_KEYS_ENV`, `get_openalex_api_keys()` |
| `src/core/enrichment/base.py` | Replace single-key fields with `_key_manager` |
| `src/core/crawler/openalex.py` | Replace `api_key`/`email` with `_key_manager` |
| `docs/guides/crawling.md` | Document `OPENALEX_API_KEYS` env var |
