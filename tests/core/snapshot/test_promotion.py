import pytest

from src.core.snapshot.promotion import Decision, evaluate


def test_evaluate_promote_when_title_and_abstract():
    stub = {"title": None, "year": None, "authors": []}
    fields = {"title": "X", "abstract": "..."}
    assert evaluate(stub, fields) is Decision.PROMOTE


def test_evaluate_promote_when_title_year_and_author():
    stub = {"title": None, "year": None, "authors": []}
    fields = {"title": "X", "year": 2024, "authors": [{"display_name": "A"}]}
    assert evaluate(stub, fields) is Decision.PROMOTE


def test_evaluate_enrich_keep_stub_when_partial():
    stub = {"title": None, "year": None, "authors": []}
    fields = {"year": 2024}   # title still missing
    assert evaluate(stub, fields) is Decision.ENRICH_KEEP_STUB


def test_evaluate_skip_when_nothing_gained():
    stub = {"title": "Existing", "year": 2024, "authors": [{"display_name": "X"}]}
    fields = {}    # extractor returned nothing
    assert evaluate(stub, fields) is Decision.SKIP


def test_evaluate_skip_when_only_fields_already_on_stub():
    stub = {"title": "Existing", "year": 2024, "authors": [{"display_name": "X"}]}
    fields = {"title": "Existing", "year": 2024}
    assert evaluate(stub, fields) is Decision.SKIP
