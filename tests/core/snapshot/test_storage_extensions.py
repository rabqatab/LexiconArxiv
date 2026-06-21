import pytest


@pytest.mark.integration
def test_build_openalex_id_to_point_id_map(storage):
    m = storage.build_openalex_id_to_point_id_map()
    assert isinstance(m, dict)
    # values are point_id strings
    for v in m.values():
        assert isinstance(v, str)
        break


@pytest.mark.integration
def test_batch_extend_external_cited_by_empty(storage):
    n = storage.batch_extend_external_cited_by({})
    assert n == 0
