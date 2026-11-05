"""Regression cases found during the November 2026 crawling audit."""

import tarfile
from unittest.mock import Mock

import pytest

from ids_arxiv.benchmark import BenchmarkSession, summarize_sessions
from ids_arxiv.crawler.arxiv_client import ArxivCrawler
from ids_arxiv.crawler.http import RequestFailure, get_response
from ids_arxiv.crawler.rate_limiter import PoliteRateLimiter, retry_after_seconds
from ids_arxiv.crawler.runner import crawl_paper
from ids_arxiv.crawler.s2_client import SemanticScholarClient
from ids_arxiv.discovery import MemberRange, build_manifest, parse_atom, to_arxiv_id
from ids_arxiv.storage import file_inventory


def test_cross_month_manifest_refuses_fake_subset():
    member = MemberRange("x", "Test", "2508.17872", "2509.01046", "2508", "2509")
    with pytest.raises(ValueError, match="real discovery"):
        build_manifest([member])
    manifest = build_manifest([member], ["2508.17872", "2508.23000", "2509.01046", "2509.01047"])
    assert manifest.arxiv_id.tolist() == ["2508.17872", "2508.23000", "2509.01046"]


def test_old_arxiv_id_roundtrip():
    assert to_arxiv_id("hep-th/9901001v2") == "hep-th/9901001"
    assert to_arxiv_id("solv-int/9901001v1") == "solv-int/9901001"


def test_atom_version_and_total():
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:o="http://a9.com/-/spec/opensearch/1.1/">
    <o:totalResults>10</o:totalResults><entry><id>http://arxiv.org/abs/2509.01047v3</id>
    <title>A paper</title><published>2025-09-01T00:00:00Z</published>
    <author><name>Alice</name></author></entry></feed>"""
    rows, total = parse_atom(xml)
    assert total == 10 and rows[0]["latest_version"] == 3


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "traversal", "sibling"])
def test_tar_escape_rejected(tmp_path, kind):
    archive = tmp_path / "input.tar"
    with tarfile.open(archive, "w") as tar:
        item = tarfile.TarInfo("safe.tex")
        if kind == "symlink":
            item.type, item.linkname = tarfile.SYMTYPE, "../outside"
        elif kind == "hardlink":
            item.type, item.linkname = tarfile.LNKTYPE, "../outside"
        else:
            item.name = "../outside" if kind == "traversal" else "../dest-evil/file"
        tar.addfile(item)
    dest = tmp_path / "dest"
    dest.mkdir()
    assert not ArxivCrawler()._safe_extract(archive, dest)
    assert not (tmp_path / "outside").exists()


def test_s2_unknown_date_is_not_january_first():
    refs = SemanticScholarClient()._process_references(
        [{"paperId": "x", "title": "A", "year": 2020, "externalIds": {"ArXiv": "2001.00001"}}]
    )
    assert refs["2001-00001"]["submission_date"] is None


def test_s2_rate_limit_not_empty_success(monkeypatch):
    def denied(*args, **kwargs):
        raise RequestFailure("HTTP 429", 429)

    monkeypatch.setattr("ids_arxiv.crawler.s2_client.get_response", denied)
    client = SemanticScholarClient()
    assert client.get_paper_references("2509.01047") == {}
    assert client.last_status["state"] == "retryable_error"
    assert not client.last_status["success"]


def test_http_retry_after_and_failure_record():
    session, limiter = Mock(), Mock()
    busy = Mock(status_code=429, headers={"Retry-After": "11"})
    okay = Mock(status_code=200)
    session.get.side_effect = [busy, okay]
    events = []
    assert get_response(session, "https://example.invalid", limiter, events=events.append) is okay
    assert limiter.wait.call_args.kwargs["extra_delay"] >= 11
    assert [event["http_status"] for event in events] == [429, 200]
    assert retry_after_seconds("nonsense") == 0


def test_rolling_window_and_full_backoff(monkeypatch):
    clock = [100.0]
    waits = []
    monkeypatch.setattr("ids_arxiv.crawler.rate_limiter.time.monotonic", lambda: clock[0])

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr("ids_arxiv.crawler.rate_limiter.time.sleep", sleep)
    limiter = PoliteRateLimiter(1, max_requests=2, window_seconds=10)
    limiter.wait()
    limiter.wait()
    limiter.wait()
    assert waits == [1, 9]
    clock[0] += 5
    limiter.wait(extra_delay=7)
    assert waits[-1] == 7


class FakeCrawler:
    events = None
    last_error = None

    def __init__(self):
        self.calls = []
        self.fail_second = True

    def fetch_metadata(self, paper):
        return {
            "title": "Test",
            "authors": [],
            "submission_date": "2025-09-01T00:00:00Z",
            "revised_dates": ["2025-09-01T00:00:00Z"],
        }, [1, 2]

    def download_and_extract_version(self, paper, version, directory):
        self.calls.append(version)
        directory.mkdir(exist_ok=True)
        if version == 2 and self.fail_second:
            return {"version": version, "success": False, "state": "retryable_error"}
        (directory / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
        return {
            "version": version,
            "success": True,
            "state": "downloaded",
            "files": file_inventory(directory),
        }


class FakeS2:
    last_status = {"success": True, "state": "empty"}

    def get_paper_references(self, paper):
        return {}


def test_partial_versions_resume_only_missing_and_detect_corruption(tmp_path):
    crawler = FakeCrawler()
    first = crawl_paper("2509.01047", tmp_path, crawler, FakeS2())
    assert not first["success"] and not first["source_success"]
    assert crawler.calls == [1, 2]
    crawler.fail_second = False
    second = crawl_paper("2509.01047", tmp_path, crawler, FakeS2())
    assert second["success"] and crawler.calls == [1, 2, 2]
    third = crawl_paper("2509.01047", tmp_path, crawler, FakeS2())
    assert third["cache_hit"] and crawler.calls == [1, 2, 2]
    (tmp_path / "2509-01047" / "v1" / "main.tex").unlink()
    repaired = crawl_paper("2509.01047", tmp_path, crawler, FakeS2())
    assert repaired["success"] and crawler.calls == [1, 2, 2, 1]


def test_benchmark_elapsed_includes_waits_and_aggregate(tmp_path):
    import time

    with BenchmarkSession(tmp_path, interval=0.01) as measured:
        time.sleep(0.04)
        measured.event({"http_status": 429, "wait_seconds": 0.02})
    with BenchmarkSession(tmp_path, interval=0.01):
        time.sleep(0.02)
    result = summarize_sessions(tmp_path)
    assert result["session_count"] == 2
    assert result["measured_runtime_seconds"] >= 0.06
    assert result["http_errors"] == 1
    assert result["peak_process_tree_rss_bytes"] == max(
        s["peak_process_tree_rss_bytes"] for s in result["sessions"]
    )
    assert all(s["state"] == "completed" for s in result["sessions"])
