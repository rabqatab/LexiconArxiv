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
