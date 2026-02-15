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
