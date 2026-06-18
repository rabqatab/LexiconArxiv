from src.core.crawler.openalex import reconstruct_abstract


def test_reconstruct_abstract_from_inverted_index():
    inv = {"Hello": [0], "world": [1], "foo": [2]}
    assert reconstruct_abstract(inv) == "Hello world foo"


def test_reconstruct_abstract_none():
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None
