"""Tests for OpenAlex multi-key support."""

import time

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


import asyncio
import httpx
import respx
from httpx import Response

from src.core.enrichment.base import OpenAlexMixin, BaseEnricher
from src.core.enrichment.openalex import PaperEnricher


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
            request = route.calls[0].request
            assert "api_key" in str(request.url)

    @pytest.mark.asyncio
    @respx.mock
    async def test_exhaustion_rotates_to_next_key(self):
        mgr = OpenAlexKeyManager(["k1", "k2"], email="e@x.com")
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
            assert enricher._semaphore._value == 1

    def test_has_valid_api_key_delegates_to_manager(self):
        mgr = OpenAlexKeyManager(["k1"])
        enricher = ConcreteEnricher(key_manager=mgr)
        assert enricher.has_valid_api_key() is True
        mgr.mark_exhausted("k1")
        assert enricher.has_valid_api_key() is False

    def test_backward_compat_api_key_param(self):
        enricher = ConcreteEnricher()
        enricher._init_openalex(api_key="direct_key", email="e@x.com")
        assert enricher._key_manager.total_key_count == 1
        params = enricher._key_manager.get_next_params()
        assert params == {"api_key": "direct_key"}


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
