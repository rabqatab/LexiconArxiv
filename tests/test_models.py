"""Tests for data models."""

import pytest
from src.models.paper import Author, PaperType, RawPaper, SourceType


class TestAuthor:
    def test_create_author(self):
        author = Author(name="John Doe", affiliation="MIT")
        assert author.name == "John Doe"
        assert author.affiliation == "MIT"
        assert author.orcid is None

    def test_author_str(self):
        author = Author(name="Jane Smith")
        assert str(author) == "Jane Smith"


class TestRawPaper:
    def test_create_minimal_paper(self):
        paper = RawPaper(
            source=SourceType.ARXIV,
            source_id="2304.12345",
            title="Test Paper",
        )
        assert paper.source == SourceType.ARXIV
        assert paper.source_id == "2304.12345"
        assert paper.title == "Test Paper"
        assert paper.abstract is None
        assert paper.authors == []

    def test_create_full_paper(self):
        paper = RawPaper(
            source=SourceType.OPENALEX,
            source_id="W123456",
            title="Full Paper",
            abstract="This is an abstract.",
            authors=[Author(name="Author 1"), Author(name="Author 2")],
            year=2023,
            doi="10.1234/test",
            arxiv_id="2304.12345",
            venue="ACL 2023",
            paper_type=PaperType.METHOD,
            citation_count=10,
        )
        assert paper.year == 2023
        assert len(paper.authors) == 2
        assert paper.citation_count == 10

    def test_primary_id_doi(self):
        paper = RawPaper(
            source=SourceType.OPENALEX,
            source_id="W123",
            title="Test",
            doi="10.1234/test",
            arxiv_id="2304.12345",
        )
        assert paper.primary_id == "10.1234/test"

    def test_primary_id_arxiv(self):
        paper = RawPaper(
            source=SourceType.ARXIV,
            source_id="2304.12345",
            title="Test",
            arxiv_id="2304.12345",
        )
        assert paper.primary_id == "2304.12345"

    def test_primary_id_fallback(self):
        paper = RawPaper(
            source=SourceType.ACL,
            source_id="custom-id",
            title="Test",
        )
        assert paper.primary_id == "custom-id"

    def test_title_normalized(self):
        paper = RawPaper(
            source=SourceType.ARXIV,
            source_id="test",
            title="KULLM: Korean Large Language Model!",
        )
        assert paper.title_normalized == "kullm korean large language model"

    def test_title_normalized_whitespace(self):
        paper = RawPaper(
            source=SourceType.ARXIV,
            source_id="test",
            title="  Multiple   Spaces  Here  ",
        )
        assert paper.title_normalized == "multiple spaces here"

    def test_paper_str(self):
        paper = RawPaper(
            source=SourceType.ARXIV,
            source_id="test",
            title="Test Paper",
            year=2023,
        )
        assert str(paper) == "Test Paper (2023)"


class TestEnums:
    def test_source_types(self):
        assert SourceType.OPENALEX.value == "openalex"
        assert SourceType.ARXIV.value == "arxiv"
        assert SourceType.ACL.value == "acl"

    def test_paper_types(self):
        assert PaperType.METHOD.value == "method"
        assert PaperType.DATASET.value == "dataset"
        assert PaperType.SURVEY.value == "survey"
