"""B: adaptive-RRF weighting + query-decomposition echo-drop (pure logic)."""
from src.core.search.query_analyzer import adaptive_rrf_weights


def test_adaptive_short_and_acronym_tilt_bm25():
    # short queries and acronym-heavy queries should favour lexical BM25
    for q in ("BERT", "BM25 RRF", '"exact phrase"', "GPT vs BERT"):
        dw, bw = adaptive_rrf_weights(q)
        assert bw > dw, q


def test_adaptive_long_nl_tilts_dense():
    q = ("a very long natural language query about transformer architectures "
         "for code generation tasks and their evaluation benchmarks")
    dw, bw = adaptive_rrf_weights(q)
    assert dw > bw


def test_adaptive_medium_query_balanced():
    dw, bw = adaptive_rrf_weights("what is retrieval augmented generation")
    assert dw == bw == 1.0


def test_adaptive_weights_positive():
    for q in ("x", "BERT", "some medium length query here now", "a " * 20):
        dw, bw = adaptive_rrf_weights(q)
        assert dw > 0 and bw > 0
