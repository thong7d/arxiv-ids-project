"""Prevent regression to API offsets beyond the practical result limit."""

from unittest.mock import Mock

from ids_arxiv.discovery import MemberRange, discover_publications


def atom(ids, total, offset=0):
    entries = "".join(
        f"<entry><id>https://arxiv.org/abs/{aid}v1</id><title>T</title>"
        "<published>2025-09-01T00:00:00Z</published></entry>"
        for aid in ids
    )
    return (
        f'<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:o="http://a9.com/-/spec/opensearch/1.1/">'
        f"<o:totalResults>{total}</o:totalResults><o:startIndex>{offset}</o:startIndex>"
        f"{entries}</feed>"
    ).encode()


def test_dense_ranges_split_without_deep_offsets_and_resume(tmp_path, monkeypatch):
    requests = []

    def get(*args, params, **kwargs):
        requests.append(params.copy())
        assert params["start"] < 8000
        query = params["search_query"]
        # Force the initial week to split; every smaller range fits one page.
        from datetime import datetime

        lower, upper = query.split("[", 1)[1].rstrip("]").split(" TO ")
        span = datetime.strptime(upper, "%Y%m%d%H%M") - datetime.strptime(lower, "%Y%m%d%H%M")
        total = 10001 if span.days >= 6 else 2
        response = Mock()
        response.content = atom(["2509.01047", "2509.01048"], total)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    monkeypatch.setattr("ids_arxiv.crawler.http.get_response", get)
    member = MemberRange("x", "X", "2509.01047", "2509.01048", "2509", "2509")
    result = discover_publications([member], tmp_path)
    assert result.arxiv_id.tolist() == ["2509.01047", "2509.01048"]
    assert len(requests) > 1
    count = len(requests)
    resumed = discover_publications([member], tmp_path)
    assert len(requests) == count
    assert resumed.equals(result)
