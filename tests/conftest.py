"""Pytest fixtures for collector tests."""

import pytest


@pytest.fixture
def openalex_work_response():
    """Sample OpenAlex work response."""
    return {
        "id": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.18653/v1/2023.acl-long.1",
        "title": "KULLM: Korean Large Language Model",
        "display_name": "KULLM: Korean Large Language Model",
        "publication_year": 2023,
        "type": "article",
        "cited_by_count": 42,
        "abstract_inverted_index": {
            "We": [0],
            "present": [1],
            "KULLM,": [2],
            "a": [3],
            "Korean": [4],
            "instruction-tuned": [5],
            "large": [6],
            "language": [7],
            "model.": [8],
        },
        "authorships": [
            {
                "author": {
                    "id": "https://openalex.org/A123456",
                    "display_name": "Seungjun Lee",
                    "orcid": "https://orcid.org/0000-0001-2345-6789",
                },
                "institutions": [{"display_name": "KAIST"}],
            },
            {
                "author": {
                    "id": "https://openalex.org/A234567",
                    "display_name": "Jihyun Kim",
                    "orcid": None,
                },
                "institutions": [{"display_name": "Seoul National University"}],
            },
        ],
        "primary_location": {
            "source": {
                "display_name": "ACL 2023",
                "type": "conference",
            },
            "pdf_url": "https://aclanthology.org/2023.acl-long.1.pdf",
        },
        "concepts": [
            {"display_name": "Natural Language Processing"},
            {"display_name": "Large Language Model"},
        ],
    }


@pytest.fixture
def openalex_search_response(openalex_work_response):
    """Sample OpenAlex search response."""
    return {
        "meta": {
            "count": 1,
            "db_response_time_ms": 50,
            "page": 1,
            "per_page": 200,
            "next_cursor": None,
        },
        "results": [openalex_work_response],
    }


@pytest.fixture
def arxiv_entry_response():
    """Sample arXiv API response (Atom feed as parsed by feedparser)."""
    return {
        "id": "http://arxiv.org/abs/2304.12345v2",
        "title": "KULLM: Korean Large Language Model\n  for Instruction Following",
        "summary": "We present KULLM, a Korean instruction-tuned large language model. "
        "Our model demonstrates strong performance on Korean NLP tasks.",
        "authors": [
            {"name": "Seungjun Lee"},
            {"name": "Jihyun Kim"},
        ],
        "published": "2023-04-15T00:00:00Z",
        "updated": "2023-04-20T00:00:00Z",
        "links": [
            {"href": "http://arxiv.org/abs/2304.12345v2", "rel": "alternate", "type": "text/html"},
            {
                "href": "http://arxiv.org/pdf/2304.12345v2",
                "rel": "related",
                "type": "application/pdf",
            },
        ],
        "arxiv_primary_category": {"term": "cs.CL"},
        "tags": [
            {"term": "cs.CL"},
            {"term": "cs.AI"},
        ],
    }


@pytest.fixture
def s2_paper_response():
    """Sample Semantic Scholar paper response."""
    return {
        "paperId": "abc123def456",
        "title": "Efficient Methods for Natural Language Understanding",
        "abstract": "We propose efficient methods for NLP tasks.",
        "year": 2023,
        "venue": "ACL",
        "publicationDate": "2023-07-01",
        "citationCount": 25,
        "externalIds": {
            "DOI": "10.18653/v1/2023.acl-long.100",
            "ACL": "2023.acl-long.100",
            "ArXiv": "2305.54321",
        },
        "url": "https://www.semanticscholar.org/paper/abc123def456",
        "authors": [
            {"authorId": "12345", "name": "Jane Doe"},
            {"authorId": "67890", "name": "John Smith"},
        ],
        "publicationTypes": ["Conference"],
    }


@pytest.fixture
def s2_search_response(s2_paper_response):
    """Sample Semantic Scholar search response."""
    return {
        "total": 1,
        "offset": 0,
        "next": None,
        "data": [s2_paper_response],
    }
