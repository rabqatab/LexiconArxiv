from datetime import date
import respx
from httpx import Response

from src.core.snapshot.work_source import iter_live_works


@respx.mock
def test_iter_live_works_single_page():
    respx.get("https://api.openalex.org/works").mock(return_value=Response(200, json={
        "meta": {"next_cursor": None, "count": 2},
        "results": [
            {"id": "https://openalex.org/W1", "doi": "10.1/a", "title": "A"},
            {"id": "https://openalex.org/W2", "doi": "10.1/b", "title": "B"},
        ],
    }))
    out = list(iter_live_works(since=date(2026, 6, 22)))
    assert [w["id"] for w in out] == ["https://openalex.org/W1", "https://openalex.org/W2"]


@respx.mock
def test_iter_live_works_follows_cursor():
    page1 = Response(200, json={
        "meta": {"next_cursor": "CURSOR2"},
        "results": [{"id": "https://openalex.org/W1"}],
    })
    page2 = Response(200, json={
        "meta": {"next_cursor": None},
        "results": [{"id": "https://openalex.org/W2"}],
    })
    respx.get("https://api.openalex.org/works").mock(side_effect=[page1, page2])
    out = list(iter_live_works(since=date(2026, 6, 22)))
    assert [w["id"] for w in out] == ["https://openalex.org/W1", "https://openalex.org/W2"]


@respx.mock
def test_iter_live_works_sends_filter_and_cursor_params():
    captured = []

    def handler(request):
        captured.append(dict(request.url.params))
        return Response(200, json={"meta": {"next_cursor": None}, "results": []})

    respx.get("https://api.openalex.org/works").mock(side_effect=handler)
    list(iter_live_works(since=date(2026, 6, 22), per_page=50, mailto="me@x.org"))
    assert captured[0]["filter"] == "from_updated_date:2026-06-22"
    assert captured[0]["per-page"] == "50"
    assert captured[0]["cursor"] == "*"
    assert captured[0]["mailto"] == "me@x.org"


@respx.mock
def test_iter_live_works_empty_results():
    respx.get("https://api.openalex.org/works").mock(return_value=Response(200, json={
        "meta": {"next_cursor": None}, "results": [],
    }))
    assert list(iter_live_works(since=date(2026, 6, 22))) == []
