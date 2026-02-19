"""Tests for LLM-enhanced keyword extraction pipeline."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.core.keyword import ExtractedKeywords, JudgeResult, KeywordExtractor
from src.core.keyword.llm_base import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT,
    EXTRACTION_USER_PROMPT_TITLE_ONLY,
    JUDGE_SYSTEM_PROMPT,
    JUDGE_USER_PROMPT,
    BaseLLMExtractor,
    BaseLLMJudge,
)
from src.core.keyword.judge import KeywordJudge


# =============================================================================
# Pydantic Model Tests
# =============================================================================


class TestPydanticModels:
    """Tests for ExtractedKeywords and JudgeResult models."""

    def test_extracted_keywords_valid(self):
        result = ExtractedKeywords(
            task=["text classification"],
            method=["attention mechanism"],
            model=["BERT", "GPT"],
            domain=["NLP"],
            dataset=["GLUE"],
            contribution_type=["model"],
            modality=["text"],
        )
        assert result.task == ["text classification"]
        assert result.method == ["attention mechanism"]
        assert result.model == ["BERT", "GPT"]
        assert result.domain == ["NLP"]
        assert result.dataset == ["GLUE"]
        assert result.contribution_type == ["model"]
        assert result.modality == ["text"]

    def test_extracted_keywords_empty_lists(self):
        result = ExtractedKeywords(
            task=[], method=[], model=[], domain=[], dataset=[],
            contribution_type=[], modality=[],
        )
        assert result.task == []
        assert result.method == []
        assert result.model == []
        assert result.domain == []
        assert result.dataset == []
        assert result.contribution_type == []
        assert result.modality == []

    def test_extracted_keywords_from_json(self):
        json_str = (
            '{"task": ["QA"], "method": ["retrieval"], '
            '"model": ["RAG"], "domain": ["NLP"], "dataset": ["SQuAD"], '
            '"contribution_type": ["method"], "modality": ["text"]}'
        )
        result = ExtractedKeywords.model_validate_json(json_str)
        assert result.task == ["QA"]
        assert result.model == ["RAG"]
        assert result.contribution_type == ["method"]
        assert result.modality == ["text"]

    def test_extracted_keywords_missing_field(self):
        with pytest.raises(Exception):
            ExtractedKeywords.model_validate_json('{"task": ["QA"]}')

    def test_extracted_keywords_to_dict(self):
        result = ExtractedKeywords(
            task=["text classification"],
            method=["fine-tuning"],
            model=["BERT"],
            domain=["NLP"],
            dataset=["GLUE"],
            contribution_type=["model"],
            modality=["text"],
        )
        d = result.to_dict()
        assert d == {
            "task": ["text classification"],
            "method": ["fine-tuning"],
            "model": ["BERT"],
            "domain": ["NLP"],
            "dataset": ["GLUE"],
            "contribution_type": ["model"],
            "modality": ["text"],
        }

    def test_judge_result_valid(self):
        result = JudgeResult(
            relevant=["BERT", "NLP"],
            irrelevant=["model", "approach"],
        )
        assert result.relevant == ["BERT", "NLP"]
        assert result.irrelevant == ["model", "approach"]

    def test_judge_result_from_json(self):
        json_str = '{"relevant": ["BERT"], "irrelevant": ["paper"]}'
        result = JudgeResult.model_validate_json(json_str)
        assert result.relevant == ["BERT"]
        assert result.irrelevant == ["paper"]

    def test_judge_result_missing_field(self):
        with pytest.raises(Exception):
            JudgeResult.model_validate_json('{"relevant": ["BERT"]}')

    def test_extracted_keywords_schema(self):
        schema = ExtractedKeywords.model_json_schema()
        assert "task" in schema["properties"]
        assert "method" in schema["properties"]
        assert "model" in schema["properties"]
        assert "domain" in schema["properties"]
        assert "dataset" in schema["properties"]

    def test_judge_result_schema(self):
        schema = JudgeResult.model_json_schema()
        assert "relevant" in schema["properties"]
        assert "irrelevant" in schema["properties"]


# =============================================================================
# Prompt Template Tests
# =============================================================================


class TestPromptTemplates:
    """Tests for prompt template formatting."""

    def test_extraction_user_prompt_formatting(self):
        prompt = EXTRACTION_USER_PROMPT.format(
            title="BERT: A New Model",
            abstract="We introduce BERT.",
        )
        assert "BERT: A New Model" in prompt
        assert "We introduce BERT." in prompt

    def test_extraction_title_only_prompt_formatting(self):
        prompt = EXTRACTION_USER_PROMPT_TITLE_ONLY.format(
            title="BERT: A New Model",
        )
        assert "BERT: A New Model" in prompt
        assert "abstract" not in prompt.lower()

    def test_judge_user_prompt_formatting(self):
        prompt = JUDGE_USER_PROMPT.format(
            title="BERT: A New Model",
            abstract="We introduce BERT.",
            keywords="BERT, NLP",
        )
        assert "BERT: A New Model" in prompt
        assert "We introduce BERT." in prompt
        assert "BERT, NLP" in prompt

    def test_system_prompts_non_empty(self):
        assert len(EXTRACTION_SYSTEM_PROMPT) > 0
        assert len(JUDGE_SYSTEM_PROMPT) > 0

    def test_extraction_prompt_mentions_json(self):
        assert "JSON" in EXTRACTION_USER_PROMPT

    def test_extraction_prompt_mentions_categories(self):
        assert "task" in EXTRACTION_USER_PROMPT
        assert "method" in EXTRACTION_USER_PROMPT
        assert "model" in EXTRACTION_USER_PROMPT
        assert "domain" in EXTRACTION_USER_PROMPT
        assert "dataset" in EXTRACTION_USER_PROMPT

    def test_judge_prompt_mentions_relevant(self):
        assert "relevant" in JUDGE_SYSTEM_PROMPT.lower()


# =============================================================================
# Extractor Init Tests
# =============================================================================


class TestExtractorInit:
    """Tests that new params don't break KeywordExtractor construction."""

    def test_default_init(self):
        ext = KeywordExtractor(use_keybert=False)
        assert ext.use_llm is False
        assert ext.use_judge is False
        assert ext.embedding_model == "all-MiniLM-L6-v2"

    def test_init_with_llm_params(self):
        ext = KeywordExtractor(
            use_keybert=False,
            use_llm=True,
            llm_backend="gemini",
            gemini_model="gemini-3-flash",
        )
        assert ext.use_llm is True
        assert ext.llm_backend == "gemini"
        assert ext.gemini_model == "gemini-3-flash"

    def test_init_with_judge_params(self):
        ext = KeywordExtractor(
            use_keybert=False,
            use_judge=True,
            judge_backend="ollama",
            ollama_model="llama3.1:8b",
        )
        assert ext.use_judge is True
        assert ext.judge_backend == "ollama"
        assert ext.ollama_model == "llama3.1:8b"

    def test_judge_backend_defaults_to_llm_backend(self):
        ext = KeywordExtractor(
            use_keybert=False,
            llm_backend="ollama",
        )
        assert ext.judge_backend == "ollama"

    def test_judge_backend_explicit(self):
        ext = KeywordExtractor(
            use_keybert=False,
            llm_backend="ollama",
            judge_backend="gemini",
        )
        assert ext.judge_backend == "gemini"

    def test_existing_extract_still_works(self):
        ext = KeywordExtractor(
            use_keybert=False,
            use_llm=True,
            use_judge=True,
        )
        # Sync extract should still work (only regex)
        keywords = ext.extract(
            "BERT: Pre-training of Deep Bidirectional Transformers",
            "We introduce BERT, a language model.",
        )
        assert "BERT" in keywords


# =============================================================================
# Embedding Model Param Tests
# =============================================================================


class TestEmbeddingModelParam:
    """Tests that embedding_model param is passed through."""

    def test_default_embedding_model(self):
        ext = KeywordExtractor(use_keybert=False)
        assert ext.embedding_model == "all-MiniLM-L6-v2"

    def test_custom_embedding_model(self):
        ext = KeywordExtractor(
            use_keybert=False,
            embedding_model="all-mpnet-base-v2",
        )
        assert ext.embedding_model == "all-mpnet-base-v2"


# =============================================================================
# Flatten Extraction Tests
# =============================================================================


class TestFlattenExtraction:
    """Tests for _flatten_extraction helper."""

    def test_flatten_all_fields(self):
        result = ExtractedKeywords(
            task=["text classification"],
            method=["attention"],
            model=["BERT", "GPT"],
            domain=["NLP"],
            dataset=["GLUE"],
            contribution_type=["model"],
            modality=["text"],
        )
        flat = BaseLLMExtractor._flatten_extraction(result)
        assert flat == [
            "text classification", "attention", "BERT", "GPT",
            "NLP", "GLUE", "model", "text",
        ]

    def test_flatten_empty(self):
        result = ExtractedKeywords(
            task=[], method=[], model=[], domain=[], dataset=[],
            contribution_type=[], modality=[],
        )
        flat = BaseLLMExtractor._flatten_extraction(result)
        assert flat == []

    def test_flatten_single_field(self):
        result = ExtractedKeywords(
            task=[],
            method=[],
            model=["BERT"],
            domain=[],
            dataset=[],
            contribution_type=[],
            modality=[],
        )
        flat = BaseLLMExtractor._flatten_extraction(result)
        assert flat == ["BERT"]


# =============================================================================
# Source Tracking Tests (with mock backends)
# =============================================================================


class _MockLLMExtractor(BaseLLMExtractor):
    """Mock LLM extractor for testing."""

    def __init__(self, result: ExtractedKeywords | None):
        self._result = result

    async def extract_keywords(
        self, title: str, abstract: str | None = None
    ) -> ExtractedKeywords | None:
        return self._result

    async def close(self) -> None:
        pass


class _MockLLMJudge(BaseLLMJudge):
    """Mock LLM judge for testing."""

    def __init__(self, relevant: list[str]):
        self._relevant = relevant

    async def judge_keywords(
        self, title: str, abstract: str, keywords: list[str]
    ) -> list[str]:
        return self._relevant

    async def close(self) -> None:
        pass


class TestSourceTracking:
    """Tests for pipe-delimited source tracking in extract_pipeline_with_source."""

    def test_regex_only_source(self):
        ext = KeywordExtractor(use_keybert=False)
        keywords, source, structured = asyncio.get_event_loop().run_until_complete(
            ext.extract_pipeline_with_source(
                "BERT: A Model", "We introduce BERT."
            )
        )
        assert "BERT" in keywords
        assert source == "regex"
        assert structured is None

    def test_no_keywords_source(self):
        ext = KeywordExtractor(use_keybert=False)
        keywords, source, structured = asyncio.get_event_loop().run_until_complete(
            ext.extract_pipeline_with_source(
                "A study of methods", "We analyze various approaches."
            )
        )
        assert source == "none" or source == "regex"
        assert structured is None

    def test_llm_source_tracking(self):
        """When LLM succeeds, it should be primary — regex should NOT run (no fallback)."""
        ext = KeywordExtractor(use_keybert=False, use_llm=True, llm_backend="gemini")
        # Inject mock returning ExtractedKeywords
        ext._llm_extractor = _MockLLMExtractor(
            ExtractedKeywords(
                task=[],
                method=["transformer", "attention"],
                model=[],
                domain=[],
                dataset=[],
                contribution_type=["model"],
                modality=["text"],
            )
        )

        keywords, source, structured = asyncio.get_event_loop().run_until_complete(
            ext.extract_pipeline_with_source(
                "BERT: A Model", "We introduce BERT and transformers."
            )
        )
        # LLM is primary — regex fallback should NOT run when LLM succeeds
        assert "gemini" in source
        parts = source.split("|")
        assert "gemini" in parts
        assert "regex" not in parts
        assert structured is not None
        assert "method" in structured
        assert "attention" in structured["method"]
        assert "contribution_type" in structured
        assert "modality" in structured

    def test_judge_source_tracking(self):
        ext = KeywordExtractor(
            use_keybert=False,
            use_judge=True,
            judge_backend="gemini",
        )
        # Inject mock judge
        ext._judge = KeywordJudge(backend=_MockLLMJudge(["BERT"]))

        keywords, source, structured = asyncio.get_event_loop().run_until_complete(
            ext.extract_pipeline_with_source(
                "BERT: A Model", "We introduce BERT."
            )
        )
        assert "judge" in source

    def test_full_pipeline_source(self):
        """LLM + judge: when LLM succeeds, regex fallback should not run."""
        ext = KeywordExtractor(
            use_keybert=False,
            use_llm=True,
            llm_backend="ollama",
            use_judge=True,
            judge_backend="ollama",
        )
        ext._llm_extractor = _MockLLMExtractor(
            ExtractedKeywords(
                task=[],
                method=["attention"],
                model=[],
                domain=[],
                dataset=[],
                contribution_type=[],
                modality=[],
            )
        )
        ext._judge = KeywordJudge(backend=_MockLLMJudge(["BERT", "attention"]))

        keywords, source, structured = asyncio.get_event_loop().run_until_complete(
            ext.extract_pipeline_with_source(
                "BERT: A Model", "We introduce BERT with attention."
            )
        )
        parts = source.split("|")
        assert "regex" not in parts
        assert "ollama" in parts
        assert "judge" in parts
        assert structured is not None

    def test_fallback_when_llm_fails(self):
        """When LLM returns None, regex + keybert should kick in as fallback."""
        ext = KeywordExtractor(use_keybert=False, use_llm=True, llm_backend="gemini")
        # Inject mock that returns None (simulating LLM failure)
        ext._llm_extractor = _MockLLMExtractor(None)

        keywords, source, structured = asyncio.get_event_loop().run_until_complete(
            ext.extract_pipeline_with_source(
                "BERT: A Model", "We introduce BERT."
            )
        )
        assert "BERT" in keywords
        assert "regex" in source
        assert "gemini" not in source
        assert structured is None

    def test_llm_with_no_abstract(self):
        """LLM should be called even without abstract (title-only extraction)."""
        ext = KeywordExtractor(use_keybert=False, use_llm=True, llm_backend="gemini")
        ext._llm_extractor = _MockLLMExtractor(
            ExtractedKeywords(
                task=["text classification"],
                method=[],
                model=["BERT"],
                domain=["NLP"],
                dataset=[],
                contribution_type=["model"],
                modality=["text"],
            )
        )

        keywords, source, structured = asyncio.get_event_loop().run_until_complete(
            ext.extract_pipeline_with_source(
                "BERT for Text Classification", None
            )
        )
        assert "BERT" in keywords
        assert "gemini" in source
        assert structured is not None
        assert "text classification" in structured["task"]
        assert "model" in structured["contribution_type"]
        assert "text" in structured["modality"]


# =============================================================================
# Judge Edge Cases
# =============================================================================


class TestJudgeEdgeCases:
    """Tests for KeywordJudge edge cases."""

    def test_empty_keywords(self):
        judge = KeywordJudge(backend=_MockLLMJudge(relevant=[]))
        result = asyncio.get_event_loop().run_until_complete(
            judge.filter_keywords("Title", "Abstract", [])
        )
        assert result == []

    def test_missing_abstract(self):
        judge = KeywordJudge(backend=_MockLLMJudge(relevant=["BERT"]))
        result = asyncio.get_event_loop().run_until_complete(
            judge.filter_keywords("BERT: A Model", None, ["BERT", "NLP"])
        )
        # Should return all keywords when no abstract
        assert result == ["BERT", "NLP"]

    def test_judge_failure_returns_all(self):
        class _FailingJudge(BaseLLMJudge):
            async def judge_keywords(self, title, abstract, keywords):
                raise RuntimeError("API error")

            async def close(self):
                pass

        judge = KeywordJudge(backend=_FailingJudge())
        result = asyncio.get_event_loop().run_until_complete(
            judge.filter_keywords("Title", "Abstract", ["BERT", "NLP"])
        )
        assert result == ["BERT", "NLP"]


# =============================================================================
# Close Method Tests
# =============================================================================


class TestClose:
    """Tests for extractor close() cleanup."""

    def test_close_with_no_resources(self):
        ext = KeywordExtractor(use_keybert=False)
        asyncio.get_event_loop().run_until_complete(ext.close())
        # Should not raise

    def test_close_cleans_up_llm(self):
        ext = KeywordExtractor(use_keybert=False, use_llm=True)
        mock_extractor = _MockLLMExtractor(
            ExtractedKeywords(
                task=[], method=["test"], model=[], domain=[], dataset=[],
                contribution_type=[], modality=[],
            )
        )
        ext._llm_extractor = mock_extractor

        asyncio.get_event_loop().run_until_complete(ext.close())
        assert ext._llm_extractor is None

    def test_close_cleans_up_judge(self):
        ext = KeywordExtractor(use_keybert=False, use_judge=True)
        ext._judge = KeywordJudge(backend=_MockLLMJudge(["test"]))

        asyncio.get_event_loop().run_until_complete(ext.close())
        assert ext._judge is None


# =============================================================================
# Integration Tests (require API keys / running services)
# =============================================================================


@pytest.mark.integration
class TestGeminiExtraction:
    """Integration tests for Gemini extraction (requires GEMINI_API_KEY)."""

    def test_gemini_extract_keywords(self):
        from src.core.keyword.gemini import GeminiKeywordExtractor

        extractor = GeminiKeywordExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_keywords(
                "BERT: Pre-training of Deep Bidirectional Transformers",
                "We introduce BERT, a new language representation model.",
            )
        )
        assert isinstance(result, ExtractedKeywords)
        flat = BaseLLMExtractor._flatten_extraction(result)
        assert len(flat) > 0


@pytest.mark.integration
class TestOllamaExtraction:
    """Integration tests for Ollama extraction (requires running Ollama)."""

    def test_ollama_extract_keywords(self):
        from src.core.keyword.ollama import OllamaKeywordExtractor

        extractor = OllamaKeywordExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_keywords(
                "BERT: Pre-training of Deep Bidirectional Transformers",
                "We introduce BERT, a new language representation model.",
            )
        )
        assert isinstance(result, ExtractedKeywords)
        flat = BaseLLMExtractor._flatten_extraction(result)
        assert len(flat) > 0


@pytest.mark.integration
class TestFullPipeline:
    """Integration test for full pipeline."""

    def test_full_pipeline(self):
        ext = KeywordExtractor(
            use_keybert=False,
            use_llm=True,
            llm_backend="gemini",
            use_judge=True,
        )

        keywords, source, structured = asyncio.get_event_loop().run_until_complete(
            ext.extract_pipeline_with_source(
                "BERT: Pre-training of Deep Bidirectional Transformers",
                "We introduce BERT, a new language representation model.",
            )
        )

        assert isinstance(keywords, list)
        assert "gemini" in source
        assert "judge" in source
        assert structured is not None
        assert "task" in structured

        asyncio.get_event_loop().run_until_complete(ext.close())
