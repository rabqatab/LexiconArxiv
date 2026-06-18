"""Tests for abstract sentence labeling pipeline."""

import asyncio

import pytest

from src.core.labeling import AbstractLabeler, AbstractStructure
from src.core.labeling.llm_base import (
    LABELING_SYSTEM_PROMPT,
    LABELING_USER_PROMPT,
    ROLES,
    BaseAbstractLabeler,
    SentenceLabel,
    SentenceLabels,
    build_abstract_structure,
    format_numbered_sentences,
)


# =============================================================================
# Mock Backend
# =============================================================================


class _MockAbstractLabeler(BaseAbstractLabeler):
    """Mock abstract labeler for testing."""

    def __init__(self, result: SentenceLabels | None):
        self._result = result

    async def label_sentences(
        self, title: str, abstract: str, numbered_sentences: str, num_sentences: int
    ) -> SentenceLabels | None:
        return self._result

    async def close(self) -> None:
        pass


# =============================================================================
# Pydantic Model Tests
# =============================================================================


class TestAbstractStructure:
    """Tests for the AbstractStructure Pydantic model."""

    def test_construction(self):
        s = AbstractStructure(
            task=["We address text classification."],
            domain=["NLP"],
            background=["Prior methods struggle."],
            approach=["We propose a novel architecture."],
            method=["Our model uses self-attention."],
            result=["We achieve 95% accuracy."],
            contribution=["We contribute a new model."],
        )
        assert s.task == ["We address text classification."]
        assert s.domain == ["NLP"]
        assert s.background == ["Prior methods struggle."]
        assert s.approach == ["We propose a novel architecture."]
        assert s.method == ["Our model uses self-attention."]
        assert s.result == ["We achieve 95% accuracy."]
        assert s.contribution == ["We contribute a new model."]

    def test_empty_lists(self):
        s = AbstractStructure(
            task=[], domain=[], background=[], approach=[],
            method=[], result=[], contribution=[],
        )
        assert s.task == []
        assert s.domain == []
        assert s.result == []

    def test_from_json(self):
        json_str = (
            '{"task": ["Sentence 1."], "domain": [], "background": [], '
            '"approach": [], "method": [], "result": ["Sentence 2."], '
            '"contribution": []}'
        )
        s = AbstractStructure.model_validate_json(json_str)
        assert s.task == ["Sentence 1."]
        assert s.result == ["Sentence 2."]

    def test_missing_field_error(self):
        with pytest.raises(Exception):
            AbstractStructure.model_validate_json('{"task": ["sentence"]}')

    def test_to_dict(self):
        s = AbstractStructure(
            task=["A."], domain=["B."], background=["C."],
            approach=["D."], method=["E."], result=["F."],
            contribution=["G."],
        )
        d = s.to_dict()
        assert d == {
            "task": ["A."],
            "domain": ["B."],
            "background": ["C."],
            "approach": ["D."],
            "method": ["E."],
            "result": ["F."],
            "contribution": ["G."],
        }

    def test_schema_has_all_roles(self):
        schema = AbstractStructure.model_json_schema()
        for role in ROLES:
            assert role in schema["properties"]

    def test_multi_label(self):
        """A sentence can appear in multiple roles."""
        sentence = "We propose and evaluate a new architecture."
        s = AbstractStructure(
            task=[], domain=[], background=[],
            approach=[sentence], method=[sentence],
            result=[], contribution=[],
        )
        assert sentence in s.approach
        assert sentence in s.method


# =============================================================================
# SentenceLabels Model Tests
# =============================================================================


class TestSentenceLabels:
    """Tests for the index-based label response model."""

    def test_construction(self):
        labels = SentenceLabels(labels=[
            SentenceLabel(index=0, labels=["task", "background"]),
            SentenceLabel(index=1, labels=["method"]),
        ])
        assert len(labels.labels) == 2
        assert labels.labels[0].index == 0
        assert labels.labels[0].labels == ["task", "background"]

    def test_from_json(self):
        json_str = '{"labels": [{"index": 0, "labels": ["task"]}, {"index": 1, "labels": ["result"]}]}'
        labels = SentenceLabels.model_validate_json(json_str)
        assert len(labels.labels) == 2
        assert labels.labels[1].labels == ["result"]

    def test_empty_labels_list(self):
        labels = SentenceLabels(labels=[])
        assert labels.labels == []

    def test_multi_label_sentence(self):
        labels = SentenceLabels(labels=[
            SentenceLabel(index=0, labels=["task", "domain", "background"]),
        ])
        assert len(labels.labels[0].labels) == 3


# =============================================================================
# Format & Build Tests
# =============================================================================


class TestFormatAndBuild:
    """Tests for format_numbered_sentences and build_abstract_structure."""

    def test_format_numbered_sentences(self):
        sentences = ["First sentence.", "Second sentence.", "Third."]
        result = format_numbered_sentences(sentences)
        assert "[0] First sentence." in result
        assert "[1] Second sentence." in result
        assert "[2] Third." in result

    def test_format_strips_whitespace(self):
        sentences = ["Sentence with trailing space. ", " Leading space."]
        result = format_numbered_sentences(sentences)
        assert "[0] Sentence with trailing space." in result
        assert "[1] Leading space." in result

    def test_build_abstract_structure(self):
        sentences = ["We study NER.", "We use a CRF.", "We achieve 92 F1."]
        labels = SentenceLabels(labels=[
            SentenceLabel(index=0, labels=["task"]),
            SentenceLabel(index=1, labels=["method"]),
            SentenceLabel(index=2, labels=["result", "contribution"]),
        ])
        structure = build_abstract_structure(sentences, labels)
        assert structure.task == ["We study NER."]
        assert structure.method == ["We use a CRF."]
        assert structure.result == ["We achieve 92 F1."]
        assert structure.contribution == ["We achieve 92 F1."]
        assert structure.domain == []

    def test_build_ignores_out_of_range_index(self):
        sentences = ["Only one sentence."]
        labels = SentenceLabels(labels=[
            SentenceLabel(index=0, labels=["task"]),
            SentenceLabel(index=5, labels=["method"]),  # out of range
        ])
        structure = build_abstract_structure(sentences, labels)
        assert structure.task == ["Only one sentence."]
        assert structure.method == []

    def test_build_ignores_invalid_role(self):
        sentences = ["A sentence."]
        labels = SentenceLabels(labels=[
            SentenceLabel(index=0, labels=["task", "invalid_role"]),
        ])
        structure = build_abstract_structure(sentences, labels)
        assert structure.task == ["A sentence."]

    def test_build_multi_label(self):
        sentences = ["We propose and evaluate X."]
        labels = SentenceLabels(labels=[
            SentenceLabel(index=0, labels=["approach", "method", "result"]),
        ])
        structure = build_abstract_structure(sentences, labels)
        assert "We propose and evaluate X." in structure.approach
        assert "We propose and evaluate X." in structure.method
        assert "We propose and evaluate X." in structure.result

    def test_build_empty_labels(self):
        sentences = ["A sentence."]
        labels = SentenceLabels(labels=[])
        structure = build_abstract_structure(sentences, labels)
        for role in ROLES:
            assert getattr(structure, role) == []


# =============================================================================
# Prompt Template Tests
# =============================================================================


class TestPromptTemplates:
    """Tests for prompt template formatting."""

    def test_user_prompt_formatting(self):
        prompt = LABELING_USER_PROMPT.format(
            title="Attention Is All You Need",
            abstract="We propose a new architecture. It uses attention.",
            sentences="[0] We propose a new architecture.",
        )
        assert "Attention Is All You Need" in prompt
        assert "We propose a new architecture. It uses attention." in prompt
        assert "[0] We propose a new architecture." in prompt

    def test_system_prompt_mentions_all_roles(self):
        for role in ROLES:
            assert role in LABELING_SYSTEM_PROMPT

    def test_system_prompt_non_empty(self):
        assert len(LABELING_SYSTEM_PROMPT) > 0

    def test_user_prompt_mentions_json(self):
        assert "JSON" in LABELING_USER_PROMPT

    def test_system_prompt_mentions_index(self):
        assert "index" in LABELING_SYSTEM_PROMPT.lower()


# =============================================================================
# Labeler Init Tests
# =============================================================================


class TestLabelerInit:
    """Tests for AbstractLabeler construction."""

    def test_default_init(self):
        labeler = AbstractLabeler()
        assert labeler.llm_backend == "ollama"
        assert labeler.ollama_model == "qwen3.5:27b"
        assert labeler.ollama_timeout == 180.0

    def test_ollama_backend(self):
        labeler = AbstractLabeler(llm_backend="ollama")
        assert labeler.llm_backend == "ollama"

    def test_custom_models(self):
        labeler = AbstractLabeler(
            ollama_model="mistral:7b",
        )
        assert labeler.ollama_model == "mistral:7b"


# =============================================================================
# Source Tracking Tests
# =============================================================================


class TestSourceTracking:
    """Tests for labeling source tracking."""

    def test_successful_labeling_returns_dict_and_source(self):
        labeler = AbstractLabeler(llm_backend="ollama")
        labeler._llm_labeler = _MockAbstractLabeler(
            SentenceLabels(labels=[
                SentenceLabel(index=0, labels=["task"]),
                SentenceLabel(index=1, labels=["approach"]),
                SentenceLabel(index=2, labels=["result"]),
            ])
        )

        structure, source = asyncio.get_event_loop().run_until_complete(
            labeler.label_abstract(
                "NER with CRF",
                "We address NER. We propose a CRF layer. We achieve 92 F1."
            )
        )
        assert structure is not None
        assert source == "ollama"
        assert "We address NER." in structure["task"]
        assert "We propose a CRF layer." in structure["approach"]
        assert "We achieve 92 F1." in structure["result"]

    def test_failed_labeling_returns_none(self):
        labeler = AbstractLabeler(llm_backend="ollama")
        labeler._llm_labeler = _MockAbstractLabeler(None)

        structure, source = asyncio.get_event_loop().run_until_complete(
            labeler.label_abstract("Title", "Abstract text.")
        )
        assert structure is None
        assert source == "none"


# =============================================================================
# Close Tests
# =============================================================================


class TestClose:
    """Tests for labeler close() cleanup."""

    def test_close_with_no_resources(self):
        labeler = AbstractLabeler()
        asyncio.get_event_loop().run_until_complete(labeler.close())
        # Should not raise

    def test_close_cleans_up_llm_labeler(self):
        labeler = AbstractLabeler()
        labeler._llm_labeler = _MockAbstractLabeler(
            SentenceLabels(labels=[])
        )
        asyncio.get_event_loop().run_until_complete(labeler.close())
        assert labeler._llm_labeler is None


# =============================================================================
# Integration Tests (require API keys / running services)
# =============================================================================


@pytest.mark.integration
class TestOllamaLabeling:
    """Integration tests for Ollama labeling (requires running Ollama)."""

    def test_ollama_label_abstract(self):
        labeler = AbstractLabeler(llm_backend="ollama")

        structure, source = asyncio.get_event_loop().run_until_complete(
            labeler.label_abstract(
                "Attention Is All You Need",
                "The dominant sequence transduction models are based on complex "
                "recurrent or convolutional neural networks. We propose a new "
                "simple network architecture, the Transformer, based solely on "
                "attention mechanisms.",
            )
        )
        assert structure is not None
        assert source == "ollama"
        assert any(len(v) > 0 for v in structure.values())
