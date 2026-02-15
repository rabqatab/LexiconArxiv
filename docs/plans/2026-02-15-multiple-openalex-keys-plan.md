# Multiple OpenAlex API Keys — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Support multiple OpenAlex API keys with round-robin rotation and per-key cooldown, so large enrichment/collection runs can distribute load across keys before falling back to email.

**Architecture:** A new `OpenAlexKeyManager` class in `src/core/openalex_keys.py` owns key rotation, exhaustion tracking, and cooldown recovery. Both `OpenAlexMixin` (enrichment) and `CoreCorpusCollector` (collection) delegate to it via a shared instance. Backward compatible with single `OPENALEX_API_KEY`.

**Tech Stack:** Python 3.12+, pytest, pytest-asyncio, no new dependencies.

**Design doc:** `docs/plans/2026-02-15-multiple-openalex-keys-design.md`

---

### Task 1: Add `get_openalex_api_keys()` to constants

**Files:**
- Modify: `src/core/constants.py:61-68`
- Test: `tests/test_openalex_key_manager.py` (new file)

**Step 1: Write the failing test**

Create `tests/test_openalex_key_manager.py`:

```python
"""Tests for OpenAlex multi-key support."""

import pytest


class TestGetOpenAlexApiKeys:
    """Tests for get_openalex_api_keys() in constants.py."""

    def test_reads_comma_separated_keys(self, monkeypatch):
        monkeypatch.setenv("OPENALEX_API_KEYS", "key1,key2,key3")
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        from src.core.constants import get_openalex_api_keys
        assert get_openalex_api_keys() == ["key1", "key2", "key3"]

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("OPENALEX_API_KEYS", " key1 , key2 , key3 ")
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        from src.core.constants import get_openalex_api_keys
        assert get_openalex_api_keys() == ["key1", "key2", "key3"]

    def test_falls_back_to_single_key(self, monkeypatch):
        monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
        monkeypatch.setenv("OPENALEX_API_KEY", "single_key")
        from src.core.constants import get_openalex_api_keys
        assert get_openalex_api_keys() == ["single_key"]

    def test_multi_key_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("OPENALEX_API_KEYS", "key1,key2")
        monkeypatch.setenv("OPENALEX_API_KEY", "old_single")
        from src.core.constants import get_openalex_api_keys
        assert get_openalex_api_keys() == ["key1", "key2"]

    def test_empty_env_returns_empty_list(self, monkeypatch):
        monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        from src.core.constants import get_openalex_api_keys
        assert get_openalex_api_keys() == []

    def test_whitespace_only_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("OPENALEX_API_KEYS", "  ,  ,  ")
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        from src.core.constants import get_openalex_api_keys
        assert get_openalex_api_keys() == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_openalex_key_manager.py::TestGetOpenAlexApiKeys -v`
Expected: FAIL — `ImportError: cannot import name 'get_openalex_api_keys'`

**Step 3: Write minimal implementation**

In `src/core/constants.py`, add after the existing `OPENALEX_API_KEY_ENV` line:

```python
OPENALEX_API_KEYS_ENV = "OPENALEX_API_KEYS"
```

Add after the existing `get_openalex_api_key()` function:

```python
def get_openalex_api_keys() -> list[str]:
    """Get OpenAlex API keys from environment.

    Reads OPENALEX_API_KEYS (comma-separated) first, falls back to
    OPENALEX_API_KEY (single key wrapped in list).

    Returns:
        List of API key strings (may be empty).
    """
    multi = os.getenv(OPENALEX_API_KEYS_ENV)
    if multi:
        keys = [k.strip() for k in multi.split(",") if k.strip()]
        if keys:
            return keys
    single = os.getenv(OPENALEX_API_KEY_ENV)
    if single and single.strip():
        return [single.strip()]
    return []
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_openalex_key_manager.py::TestGetOpenAlexApiKeys -v`
Expected: all 6 PASS

**Step 5: Commit**

```bash
git add src/core/constants.py tests/test_openalex_key_manager.py
git commit -m "Feat: Add get_openalex_api_keys() for multi-key env var support"
```

---

### Task 2: Create `OpenAlexKeyManager` class

**Files:**
- Create: `src/core/openalex_keys.py`
- Test: `tests/test_openalex_key_manager.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_openalex_key_manager.py`:

```python
import time
from src.core.openalex_keys import OpenAlexKeyManager


class TestOpenAlexKeyManager:
    """Tests for OpenAlexKeyManager."""

    def test_init_with_keys(self):
        mgr = OpenAlexKeyManager(["k1", "k2"], email="test@example.com")
        assert mgr.total_key_count == 2
        assert mgr.active_key_count == 2
        assert mgr.has_available_keys is True

    def test_init_no_keys(self):
        mgr = OpenAlexKeyManager([], email="test@example.com")
        assert mgr.total_key_count == 0
        assert mgr.has_available_keys is False

    def test_init_deduplicates(self):
        mgr = OpenAlexKeyManager(["k1", "k2", "k1"])
        assert mgr.total_key_count == 2

    def test_round_robin_rotation(self):
        mgr = OpenAlexKeyManager(["k1", "k2", "k3"])
        keys_used = []
        for _ in range(6):
            params = mgr.get_next_params()
            keys_used.append(params["api_key"])
        assert keys_used == ["k1", "k2", "k3", "k1", "k2", "k3"]

    def test_exhausted_key_skipped(self):
        mgr = OpenAlexKeyManager(["k1", "k2", "k3"])
        mgr.mark_exhausted("k2")
        keys_used = []
        for _ in range(4):
            params = mgr.get_next_params()
            keys_used.append(params["api_key"])
        assert "k2" not in keys_used
        assert mgr.active_key_count == 2

    def test_all_exhausted_falls_back_to_email(self):
        mgr = OpenAlexKeyManager(["k1", "k2"], email="test@example.com")
        mgr.mark_exhausted("k1")
        mgr.mark_exhausted("k2")
        params = mgr.get_next_params()
        assert "api_key" not in params
        assert params["mailto"] == "test@example.com"
        assert mgr.has_available_keys is False

    def test_all_exhausted_no_email_returns_empty(self):
        mgr = OpenAlexKeyManager(["k1"], email=None)
        mgr.mark_exhausted("k1")
        params = mgr.get_next_params()
        assert params == {}

    def test_no_keys_uses_email(self):
        mgr = OpenAlexKeyManager([], email="test@example.com")
        params = mgr.get_next_params()
        assert params == {"mailto": "test@example.com"}

    def test_cooldown_recovery(self):
        mgr = OpenAlexKeyManager(["k1", "k2"], email="e@x.com", cooldown=0.1)
        mgr.mark_exhausted("k1")
        assert mgr.active_key_count == 1
        time.sleep(0.15)
        # Recovery happens lazily in get_next_params
        params = mgr.get_next_params()
        assert mgr.active_key_count == 2

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENALEX_API_KEYS", "k1,k2")
        monkeypatch.setenv("OPENALEX_EMAIL", "e@x.com")
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        mgr = OpenAlexKeyManager.from_env()
        assert mgr.total_key_count == 2
        params = mgr.get_next_params()
        assert params["api_key"] in ("k1", "k2")

    def test_from_env_single_key_fallback(self, monkeypatch):
        monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
        monkeypatch.setenv("OPENALEX_API_KEY", "single")
        monkeypatch.setenv("OPENALEX_EMAIL", "e@x.com")
        mgr = OpenAlexKeyManager.from_env()
        assert mgr.total_key_count == 1
        assert mgr.get_next_params() == {"api_key": "single"}

    def test_from_env_no_keys(self, monkeypatch):
        monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        monkeypatch.setenv("OPENALEX_EMAIL", "e@x.com")
        mgr = OpenAlexKeyManager.from_env()
        assert mgr.total_key_count == 0
        assert mgr.get_next_params() == {"mailto": "e@x.com"}

    def test_get_next_params_returns_used_key(self):
        """get_next_params returns the key it chose so callers can report exhaustion."""
        mgr = OpenAlexKeyManager(["k1", "k2"])
        params = mgr.get_next_params()
        assert "api_key" in params
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_openalex_key_manager.py::TestOpenAlexKeyManager -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.openalex_keys'`

**Step 3: Write minimal implementation**

Create `src/core/openalex_keys.py`:

```python
"""OpenAlex API key manager with round-robin rotation and per-key cooldown."""

from __future__ import annotations

import logging
import time

from src.core.constants import get_openalex_api_keys, get_openalex_email

logger = logging.getLogger(__name__)


class OpenAlexKeyManager:
    """Manages a pool of OpenAlex API keys with round-robin rotation and per-key cooldown.

    Keys are rotated evenly across requests. When a key is exhausted (HTTP 429
    with "Insufficient credits"), it enters a cooldown period. After cooldown,
    it re-enters the rotation automatically. When ALL keys are exhausted,
    falls back to email-based polite pool.
    """

    def __init__(
        self,
        keys: list[str],
        email: str | None = None,
        cooldown: float = 300,
    ) -> None:
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for k in keys:
            if k not in seen:
                seen.add(k)
                deduped.append(k)
            else:
                logger.warning(f"Duplicate OpenAlex API key removed: {k[:8]}...")
        self._keys = deduped
        self._email = email
        self._cooldown = cooldown
        self._exhausted: dict[str, float] = {}  # key -> exhaustion timestamp
        self._index = 0

        logger.info(
            f"OpenAlex key manager: {len(self._keys)} API key(s) loaded, "
            f"email={'yes' if self._email else 'no'}"
        )

    @classmethod
    def from_env(cls) -> OpenAlexKeyManager:
        """Create key manager from environment variables.

        Reads OPENALEX_API_KEYS (comma-separated) or OPENALEX_API_KEY (single),
        plus OPENALEX_EMAIL as fallback.
        """
        keys = get_openalex_api_keys()
        email = get_openalex_email()
        return cls(keys=keys, email=email)

    def get_next_params(self) -> dict[str, str]:
        """Get query parameters for the next OpenAlex API call.

        Round-robins through available (non-exhausted) keys.
        Falls back to email if all keys exhausted, or empty dict if no email.
        """
        self._recover_keys()

        available = [k for k in self._keys if k not in self._exhausted]
        if available:
            key = available[self._index % len(available)]
            self._index += 1
            logger.debug(
                f"Using OpenAlex key {self._keys.index(key) + 1}/{len(self._keys)}"
            )
            return {"api_key": key}

        if self._email:
            return {"mailto": self._email}
        return {}

    def mark_exhausted(self, key: str) -> None:
        """Mark an API key as exhausted.

        Args:
            key: The API key string that received 429.
        """
        if key not in self._exhausted:
            self._exhausted[key] = time.monotonic()
            key_idx = self._keys.index(key) + 1 if key in self._keys else "?"
            remaining = self.active_key_count
            logger.warning(
                f"OpenAlex key {key_idx}/{len(self._keys)} exhausted. "
                f"{remaining} key(s) remaining."
            )
            if remaining == 0:
                if self._email:
                    logger.warning(
                        f"All {len(self._keys)} OpenAlex API key(s) exhausted. "
                        "Falling back to email polite pool."
                    )
                else:
                    logger.warning(
                        f"All {len(self._keys)} OpenAlex API key(s) exhausted. "
                        "No email configured — using anonymous access."
                    )

    def _recover_keys(self) -> None:
        """Check cooldowns and restore any keys whose cooldown has elapsed."""
        now = time.monotonic()
        recovered = [
            k for k, t in self._exhausted.items() if now - t > self._cooldown
        ]
        for k in recovered:
            del self._exhausted[k]
            key_idx = self._keys.index(k) + 1 if k in self._keys else "?"
            logger.info(
                f"OpenAlex key {key_idx}/{len(self._keys)} recovered after cooldown. "
                f"{self.active_key_count}/{len(self._keys)} key(s) available."
            )

    @property
    def has_available_keys(self) -> bool:
        """True if at least one non-exhausted key exists."""
        self._recover_keys()
        return any(k not in self._exhausted for k in self._keys)

    @property
    def active_key_count(self) -> int:
        """Number of non-exhausted keys."""
        return sum(1 for k in self._keys if k not in self._exhausted)

    @property
    def total_key_count(self) -> int:
        """Total number of keys in pool."""
        return len(self._keys)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_openalex_key_manager.py -v`
Expected: all tests in TestGetOpenAlexApiKeys + TestOpenAlexKeyManager PASS

**Step 5: Commit**

```bash
git add src/core/openalex_keys.py tests/test_openalex_key_manager.py
git commit -m "Feat: Add OpenAlexKeyManager with round-robin rotation and per-key cooldown"
```

---

### Task 3: Integrate `OpenAlexKeyManager` into `OpenAlexMixin`

**Files:**
- Modify: `src/core/enrichment/base.py:107-288`
- Test: `tests/test_openalex_key_manager.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_openalex_key_manager.py`:

```python
import asyncio
import httpx
import respx
from httpx import Response

from src.core.enrichment.base import OpenAlexMixin, BaseEnricher
from src.core.openalex_keys import OpenAlexKeyManager


class ConcreteEnricher(BaseEnricher, OpenAlexMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, key_manager=None, **kwargs):
        self._init_openalex(key_manager=key_manager)
        super().__init__(**kwargs)
        self._original_max_concurrent = self.max_concurrent

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=10)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()


class TestOpenAlexMixinKeyManager:
    """Tests for OpenAlexMixin with key manager integration."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_uses_key_manager_for_params(self):
        mgr = OpenAlexKeyManager(["k1", "k2"])
        enricher = ConcreteEnricher(key_manager=mgr, max_concurrent=1)
        async with enricher:
            route = respx.get("https://api.openalex.org/works/https://doi.org/10.1234/test").mock(
                return_value=Response(200, json={"id": "W1", "title": "Test"})
            )
            await enricher.fetch_openalex_work("10.1234/test", "doi")
            # Verify an api_key param was sent
            request = route.calls[0].request
            assert "api_key" in str(request.url)

    @pytest.mark.asyncio
    @respx.mock
    async def test_exhaustion_rotates_to_next_key(self):
        mgr = OpenAlexKeyManager(["k1", "k2"], email="e@x.com")
        enricher = ConcreteEnricher(key_manager=mgr, max_concurrent=2)

        async with enricher:
            # First call: 429 with "Insufficient credits" for k1
            respx.get("https://api.openalex.org/works/https://doi.org/10.1234/a").mock(
                side_effect=[
                    Response(429, json={"message": "Insufficient credits"}),
                    Response(200, json={"id": "W1", "title": "Test"}),
                ]
            )
            result = await enricher.fetch_openalex_work("10.1234/a", "doi")
            assert result is not None
            # k1 should be exhausted, k2 still available
            assert mgr.active_key_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_keys_exhausted_falls_back_to_email(self):
        mgr = OpenAlexKeyManager(["k1"], email="e@x.com")
        enricher = ConcreteEnricher(key_manager=mgr, max_concurrent=2)

        async with enricher:
            respx.get("https://api.openalex.org/works/https://doi.org/10.1234/a").mock(
                side_effect=[
                    Response(429, json={"message": "Insufficient credits"}),
                    Response(200, json={"id": "W1", "title": "Test"}),
                ]
            )
            result = await enricher.fetch_openalex_work("10.1234/a", "doi")
            assert result is not None
            # All exhausted, should have reduced concurrency
            assert enricher._semaphore._value == 1

    def test_has_valid_api_key_delegates_to_manager(self):
        mgr = OpenAlexKeyManager(["k1"])
        enricher = ConcreteEnricher(key_manager=mgr)
        assert enricher.has_valid_api_key() is True
        mgr.mark_exhausted("k1")
        assert enricher.has_valid_api_key() is False

    def test_backward_compat_api_key_param(self):
        """Passing api_key= directly still works."""
        enricher = ConcreteEnricher()
        enricher._init_openalex(api_key="direct_key", email="e@x.com")
        assert enricher._key_manager.total_key_count == 1
        params = enricher._key_manager.get_next_params()
        assert params == {"api_key": "direct_key"}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_openalex_key_manager.py::TestOpenAlexMixinKeyManager -v`
Expected: FAIL — `OpenAlexMixin` still uses old single-key `api_key` field

**Step 3: Modify `OpenAlexMixin`**

In `src/core/enrichment/base.py`, replace the class-level fields and methods:

**Class-level fields** — replace:
```python
    email: str | None = None
    api_key: str | None = None
    _api_key_exhausted: bool = False
    _api_key_exhausted_at: float = 0
    _api_key_cooldown: float = 300
    _original_max_concurrent: int = 1
```
with:
```python
    _key_manager: OpenAlexKeyManager | None = None
    _original_max_concurrent: int = 1
```

Add import at top of file:
```python
from src.core.openalex_keys import OpenAlexKeyManager
```

**`_init_openalex()`** — replace entire method:
```python
    def _init_openalex(
        self,
        email: str | None = None,
        api_key: str | None = None,
        key_manager: OpenAlexKeyManager | None = None,
    ) -> None:
        """Initialize OpenAlex credentials.

        Args:
            email: Email for polite pool (backward compat).
            api_key: Single API key (backward compat).
            key_manager: Pre-configured key manager. Takes precedence.
        """
        if key_manager:
            self._key_manager = key_manager
        elif api_key:
            self._key_manager = OpenAlexKeyManager(
                [api_key], email or get_openalex_email()
            )
        else:
            self._key_manager = OpenAlexKeyManager.from_env()
            if email:
                self._key_manager._email = email
```

**`_get_openalex_params()`** — replace entire method:
```python
    def _get_openalex_params(self) -> dict[str, str]:
        """Get query parameters for OpenAlex API calls.

        Delegates to key manager for round-robin key selection.
        """
        return self._key_manager.get_next_params()
```

**`_handle_api_key_exhaustion()`** — replace entire method:
```python
    def _handle_api_key_exhaustion(
        self, response: "httpx.Response", used_key: str | None = None
    ) -> bool:
        """Check if response indicates API key credit exhaustion.

        If exhausted, marks the specific key and adjusts concurrency
        if ALL keys are now exhausted.

        Args:
            response: HTTP response to check.
            used_key: The API key used for this request.

        Returns:
            True if credits exhausted and should retry, False otherwise.
        """
        if response.status_code != 429 or not used_key:
            return False
        try:
            data = response.json()
            if "Insufficient credits" not in data.get("message", ""):
                return False
        except Exception:
            return False

        self._key_manager.mark_exhausted(used_key)

        # Reduce concurrency only when ALL keys are exhausted
        if not self._key_manager.has_available_keys:
            if hasattr(self, "_semaphore") and self._semaphore is not None:
                self._original_max_concurrent = max(
                    self._original_max_concurrent, self._semaphore._value
                )
                self._semaphore = asyncio.Semaphore(1)
        return True
```

**`has_valid_api_key()`** — replace:
```python
    def has_valid_api_key(self) -> bool:
        """Check if a valid (non-exhausted) API key is available."""
        return self._key_manager.has_available_keys
```

**`fetch_openalex_work()`** — modify the method to track `used_key` and pass it to exhaustion handler. The key changes are:

1. After `params = self._get_openalex_params()`, extract `used_key = params.get("api_key")`
2. In the 429 handler, pass `used_key` to `_handle_api_key_exhaustion(response, used_key)`
3. On exhaustion recovery, restore concurrency if keys become available again

Replace the full method body (lines 212-288) with:

```python
    async def fetch_openalex_work(
        self,
        identifier: str,
        identifier_type: str = "doi",
        _retry_count: int = 0,
    ) -> dict[str, Any] | None:
        """Fetch paper metadata from OpenAlex.

        Args:
            identifier: The identifier value.
            identifier_type: Type of identifier ('doi', 'arxiv', 'openalex').
            _retry_count: Internal retry counter (do not set manually).

        Returns:
            Metadata dict or None if not found.
        """
        max_retries = 3

        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # Build URL based on identifier type
        if identifier_type == "doi":
            url = f"{OPENALEX_BASE_URL}/works/https://doi.org/{identifier}"
        elif identifier_type == "arxiv":
            url = f"{OPENALEX_BASE_URL}/works/arXiv:{identifier}"
        elif identifier_type == "openalex":
            work_id = identifier if identifier.startswith("W") else f"W{identifier}"
            url = f"{OPENALEX_BASE_URL}/works/{work_id}"
        else:
            raise ValueError(f"Unknown identifier type: {identifier_type}")

        params = self._get_openalex_params()
        used_key = params.get("api_key")

        try:
            async with self._semaphore:
                response = await self._client.get(url, params=params)
                await asyncio.sleep(self.delay)

            if response.status_code == 404:
                return None

            if response.status_code == 429:
                # Check if API key credits exhausted - if so, mark key and retry
                if self._handle_api_key_exhaustion(response, used_key):
                    # Restore concurrency if another key is available
                    if self._key_manager.has_available_keys:
                        if hasattr(self, "_semaphore") and self._semaphore is not None:
                            self._semaphore = asyncio.Semaphore(
                                self._original_max_concurrent
                            )
                    return await self.fetch_openalex_work(
                        identifier, identifier_type, _retry_count=0
                    )
                # Regular rate limiting - wait and retry (with max retries)
                if _retry_count >= max_retries:
                    logger.warning(
                        f"OpenAlex rate limit: max retries ({max_retries}) reached "
                        f"for {identifier_type}:{identifier}, skipping."
                    )
                    raise APIRateLimitError(
                        f"Max retries ({max_retries}) for {identifier_type}:{identifier}"
                    )
                logger.warning(
                    f"Rate limited by OpenAlex, waiting 60s... "
                    f"(retry {_retry_count + 1}/{max_retries})"
                )
                await asyncio.sleep(60)
                return await self.fetch_openalex_work(
                    identifier, identifier_type, _retry_count=_retry_count + 1
                )

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.debug(f"OpenAlex HTTP error: {e}")
            return None
        except Exception as e:
            logger.debug(f"OpenAlex fetch error: {e}")
            return None
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_openalex_key_manager.py -v`
Expected: all tests PASS

Also run existing tests to check backward compat:
Run: `uv run pytest tests/test_openalex.py -v`
Expected: all tests PASS (legacy collector is not affected)

**Step 5: Commit**

```bash
git add src/core/enrichment/base.py tests/test_openalex_key_manager.py
git commit -m "Feat: Integrate OpenAlexKeyManager into OpenAlexMixin"
```

---

### Task 4: Update `PaperEnricher` concurrency logic

**Files:**
- Modify: `src/core/enrichment/openalex.py:58-99`

**Step 1: Write the failing test**

Append to `tests/test_openalex_key_manager.py`:

```python
from src.core.enrichment.openalex import PaperEnricher


class TestPaperEnricherKeyManager:
    """Tests for PaperEnricher using key manager."""

    def test_default_concurrency_with_keys(self, monkeypatch):
        monkeypatch.setenv("OPENALEX_API_KEYS", "k1,k2")
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        monkeypatch.setenv("OPENALEX_EMAIL", "e@x.com")
        enricher = PaperEnricher(storage=None)
        assert enricher.max_concurrent == PaperEnricher.DEFAULT_CONCURRENT_API_KEY
        assert enricher._key_manager.total_key_count == 2

    def test_default_concurrency_email_only(self, monkeypatch):
        monkeypatch.delenv("OPENALEX_API_KEYS", raising=False)
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        monkeypatch.setenv("OPENALEX_EMAIL", "e@x.com")
        enricher = PaperEnricher(storage=None)
        assert enricher.max_concurrent == PaperEnricher.DEFAULT_CONCURRENT_EMAIL

    def test_accepts_key_manager_param(self):
        mgr = OpenAlexKeyManager(["k1", "k2"])
        enricher = PaperEnricher(storage=None, key_manager=mgr)
        assert enricher._key_manager is mgr
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_openalex_key_manager.py::TestPaperEnricherKeyManager -v`
Expected: FAIL — `PaperEnricher.__init__()` doesn't accept `key_manager`

**Step 3: Update `PaperEnricher.__init__()`**

In `src/core/enrichment/openalex.py`, modify the `__init__` method:

- Add `key_manager: OpenAlexKeyManager | None = None` parameter
- Pass it to `_init_openalex(key_manager=key_manager)`
- Change concurrency check from `self.api_key` to `self._key_manager.has_available_keys`

```python
    def __init__(
        self,
        storage: "QdrantStorage | None" = None,
        email: str | None = None,
        api_key: str | None = None,
        key_manager: OpenAlexKeyManager | None = None,
        checkpoint_dir: Path | str | None = None,
        batch_size: int = 100,
        delay: float = 0.1,
        max_concurrent: int | None = None,
    ):
        """Initialize PaperEnricher.

        Args:
            storage: QdrantStorage instance. Created if not provided.
            email: OpenAlex email for polite pool (backward compat).
            api_key: Single OpenAlex API key (backward compat).
            key_manager: Pre-configured key manager. Takes precedence.
            checkpoint_dir: Directory for checkpoint files.
            batch_size: Number of papers to process per batch.
            delay: Delay between API calls in seconds.
            max_concurrent: Maximum concurrent API requests.
                If None, uses 3 for API key, 1 for email.
        """
        # Initialize OpenAlex first to determine if API keys are available
        self._init_openalex(email=email, api_key=api_key, key_manager=key_manager)

        # Set default concurrency based on auth method
        if max_concurrent is None:
            max_concurrent = (
                self.DEFAULT_CONCURRENT_API_KEY
                if self._key_manager.has_available_keys
                else self.DEFAULT_CONCURRENT_EMAIL
            )

        super().__init__(
            storage=storage,
            delay=delay,
            max_concurrent=max_concurrent,
        )
        self._original_max_concurrent = max_concurrent
        self.batch_size = batch_size

        # Checkpoint
        self.checkpoint_dir = Path(checkpoint_dir or "data/core/checkpoints")
```

Add import at top of `src/core/enrichment/openalex.py`:
```python
from src.core.openalex_keys import OpenAlexKeyManager
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_openalex_key_manager.py -v`
Expected: all tests PASS

**Step 5: Commit**

```bash
git add src/core/enrichment/openalex.py tests/test_openalex_key_manager.py
git commit -m "Feat: Update PaperEnricher to accept and use OpenAlexKeyManager"
```

---

### Task 5: Integrate `OpenAlexKeyManager` into `CoreCorpusCollector`

**Files:**
- Modify: `src/core/crawler/openalex.py:42-113`
- Test: `tests/test_openalex_key_manager.py` (append)

**Step 1: Write the failing test**

Append to `tests/test_openalex_key_manager.py`:

```python
from src.core.crawler.openalex import CoreCorpusCollector


class TestCoreCorpusCollectorKeyManager:
    """Tests for CoreCorpusCollector using key manager."""

    def test_accepts_key_manager_param(self):
        mgr = OpenAlexKeyManager(["k1", "k2"], email="e@x.com")
        collector = CoreCorpusCollector(storage=None, key_manager=mgr)
        assert collector._key_manager is mgr

    def test_backward_compat_api_key_param(self):
        collector = CoreCorpusCollector(storage=None, api_key="direct_key")
        assert collector._key_manager.total_key_count == 1
        params = collector._key_manager.get_next_params()
        assert params == {"api_key": "direct_key"}

    def test_build_url_uses_key_manager(self):
        mgr = OpenAlexKeyManager(["k1"])
        collector = CoreCorpusCollector(storage=None, key_manager=mgr)
        url = collector._build_url("works", {"filter": "test"})
        assert "api_key=k1" in url

    def test_build_url_round_robins(self):
        mgr = OpenAlexKeyManager(["k1", "k2"])
        collector = CoreCorpusCollector(storage=None, key_manager=mgr)
        url1 = collector._build_url("works", {})
        url2 = collector._build_url("works", {})
        assert "api_key=k1" in url1
        assert "api_key=k2" in url2

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENALEX_API_KEYS", "k1,k2,k3")
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        monkeypatch.setenv("OPENALEX_EMAIL", "e@x.com")
        collector = CoreCorpusCollector(storage=None)
        assert collector._key_manager.total_key_count == 3
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_openalex_key_manager.py::TestCoreCorpusCollectorKeyManager -v`
Expected: FAIL — `CoreCorpusCollector.__init__()` doesn't accept `key_manager`

**Step 3: Modify `CoreCorpusCollector`**

In `src/core/crawler/openalex.py`:

Add import at top:
```python
from src.core.openalex_keys import OpenAlexKeyManager
```

Replace `__init__()`:
```python
    def __init__(
        self,
        storage: QdrantStorage | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        deduplicator: Deduplicator | None = None,
        email: str | None = None,
        api_key: str | None = None,
        key_manager: OpenAlexKeyManager | None = None,
        timeout: float = 30.0,
    ):
        """Initialize the collector.

        Args:
            storage: Qdrant storage instance. Created if not provided.
            checkpoint_manager: Checkpoint manager. Created if not provided.
            deduplicator: Deduplicator instance. Created if not provided.
            email: Contact email for OpenAlex polite pool (backward compat).
            api_key: Single OpenAlex API key (backward compat).
            key_manager: Pre-configured key manager. Takes precedence.
            timeout: HTTP request timeout in seconds.
        """
        self.storage = storage
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()

        # Initialize key manager
        if key_manager:
            self._key_manager = key_manager
        elif api_key:
            self._key_manager = OpenAlexKeyManager(
                [api_key], email or get_openalex_email()
            )
        else:
            self._key_manager = OpenAlexKeyManager.from_env()

        self.timeout = timeout
        self.deduplicator = deduplicator or Deduplicator()
        self._client: httpx.AsyncClient | None = None
```

Replace `_build_url()`:
```python
    def _build_url(self, endpoint: str, params: dict[str, Any]) -> str:
        """Build API URL with parameters."""
        params.update(self._key_manager.get_next_params())
        query_string = urlencode(params, doseq=True)
        return f"{OPENALEX_BASE_URL}/{endpoint}?{query_string}"
```

Also need to check if `self.api_key` or `self.email` is referenced elsewhere in the class. Search for them and update any references to use `self._key_manager`:

Search `src/core/crawler/openalex.py` for `self.api_key` and `self.email` — any hits outside `__init__` and `_build_url` need updating. The `_get_headers()` method references `self.email`:

Replace `_get_headers()` to use the key manager's email:
```python
    def _get_headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "Accept": "application/json",
            "User-Agent": f"LexiconArxiv/1.0 (mailto:{self._key_manager._email or 'unknown'})",
        }
        return headers
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_openalex_key_manager.py -v`
Expected: all tests PASS

Run: `uv run pytest tests/ -v`
Expected: no regressions

**Step 5: Commit**

```bash
git add src/core/crawler/openalex.py tests/test_openalex_key_manager.py
git commit -m "Feat: Integrate OpenAlexKeyManager into CoreCorpusCollector"
```

---

### Task 6: Update documentation

**Files:**
- Modify: `docs/guides/crawling.md`

**Step 1: Update crawling guide**

In `docs/guides/crawling.md`, find the section about `.env` configuration / OpenAlex API keys and add:

```markdown
### Multiple API Keys

To distribute load across multiple OpenAlex API keys, use comma-separated values:

```env
OPENALEX_API_KEYS=key1,key2,key3
OPENALEX_EMAIL=your-email@example.com
```

Keys are rotated round-robin across requests. When a key is exhausted (HTTP 429),
it enters a 5-minute cooldown while remaining keys continue serving requests.
When ALL keys are exhausted, the system falls back to the email-based polite pool.

| Configuration | Effective Daily Budget | Recommended Parallel |
|---|---|---|
| 1 API key | 100K credits | `--parallel 10` |
| 3 API keys | 300K credits | `--parallel 10` |
| Email only | ~10K/day | `--parallel 5` |

The legacy `OPENALEX_API_KEY` (single key) still works and is treated as a one-key pool.
```

**Step 2: Commit**

```bash
git add docs/guides/crawling.md
git commit -m "Docs: Document OPENALEX_API_KEYS multi-key configuration"
```

---

### Task 7: Final integration test & cleanup

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: all tests PASS, no regressions

**Step 2: Run linter**

Run: `uv run ruff check src/core/openalex_keys.py src/core/constants.py src/core/enrichment/base.py src/core/crawler/openalex.py`
Expected: no errors

Run: `uv run ruff format src/core/openalex_keys.py src/core/constants.py src/core/enrichment/base.py src/core/crawler/openalex.py`

**Step 3: Fix any issues, commit if needed**

```bash
git add -u
git commit -m "Chore: Lint and format multi-key changes"
```
