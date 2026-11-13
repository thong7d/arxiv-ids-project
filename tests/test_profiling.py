from types import SimpleNamespace

import pytest

from ids_arxiv.colab_app import default_config
from ids_arxiv.crawler.reference_dates import ReferenceDates
from ids_arxiv.profiling import StageClock, distribution, profile_paper, summarize_attempts
from ids_arxiv.team_run import output_root


def test_exclusive_stage_clock():
    ticks = iter([0, 2, 5, 9])
    timer = StageClock(clock=lambda: next(ticks))
    timer.switch("network")
    timer.switch("commit")
    assert timer.finish() == {"overhead": 2, "network": 3, "commit": 4}


def test_one_selection_config_and_stable_output(tmp_path):
    config = default_config("23120364", tmp_path)
    assert config["target_owner_ids"] == ["23120364"]
    assert config["network_mode"] == "independent_utc"
    assert output_root(config, "23120364", runtime="one") == output_root(config, "23120364", runtime="two")
    helper = default_config("23120358", tmp_path, target_owner_ids=["23120364"])
    assert output_root(helper, "23120364") != output_root(config, "23120364")


def test_reference_date_recovery_uses_only_proven_valid_dates(tmp_path):
    resolver = ReferenceDates(tmp_path / "dates.json")
    resolver.remember({"2508-17872": {"submission_date": "2025-08-24T00:00:00Z", "date_source": "arxiv_atom_published"},
                       "2508-17873": {"submission_date": "2025-08-24", "date_source": "s2_publicationDate"},
                       "2508-17874": {"submission_date": "bad", "date_source": "arxiv_atom"}})
    assert set(resolver.values["dates"]) == {"2508.17872"}


def test_auto_probe_then_full_reuses_same_output(monkeypatch, tmp_path):
    from ids_arxiv import team_run
    monkeypatch.setenv("COLAB_RELEASE_TAG", "test")
    monkeypatch.setenv("COLAB_GPU", "0")
    monkeypatch.setenv("IDS_LOCAL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("IDS_SOURCE_SHA256", "test-sha")
    original_is_dir = type(tmp_path).is_dir
    monkeypatch.setattr(type(tmp_path), "is_dir", lambda self: True if str(self).replace("\\", "/") == "/content" else original_is_dir(self))
    calls, writes = [], {}
    class IO:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def call(self, request):
            if request["action"] == "read_json":
                if request["path"].endswith("papers.json"):
                    return {"verified_discovery": True, "manifest_sha256": "manifest-sha"}
                return writes.get(request["path"], request.get("default"))
            if request["action"] == "write_json":
                writes[request["path"]] = request["value"]
                return True
            if request["action"] == "cache_catalog":
                return []
            raise AssertionError(request)
    class Benchmark(IO):
        def __init__(self, *args, **kwargs):
            self.record = {}
        def mirror(self, io):
            pass
    def pipeline(manifest, destination, **kwargs):
        calls.append((str(destination), kwargs["limit"], kwargs["campaign_mode"], kwargs["work_namespace"]))
        n = kwargs["limit"] or 5000
        return {"success_count": n, "selected_publications": n}
    monkeypatch.setattr(team_run, "IsolatedService", IO)
    monkeypatch.setattr(team_run, "BenchmarkSession", Benchmark)
    monkeypatch.setattr(team_run, "run_crawling_pipeline", pipeline)
    config = default_config("23120364", tmp_path)
    team_run.worker(config, "auto")
    assert [call[1] for call in calls] == [5, None]
    assert calls[0][0] == calls[1][0] and all(call[2] == "full" for call in calls)
    assert calls[0][3] == "probe" and calls[1][3] is None
    assert "/pilot/" not in str(writes)


def test_profile_restores_progress_even_on_error():
    called = []
    def progress(stage, **kw):
        called.append(stage)
    crawler = SimpleNamespace(progress=progress)
    @profile_paper
    def work(aid, output, crawler, s2):
        crawler.progress("download_source")
        raise ValueError("bad")
    with pytest.raises(ValueError):
        work("x", "x", crawler, None)
    assert crawler.progress is progress and called == ["download_source"]


def test_profile_and_summary_separate_cache_and_worker_breakdown():
    @profile_paper
    def work(aid, output, crawler, s2):
        crawler.progress("metadata")
        return {"success": True}
    crawler = SimpleNamespace()
    result = work("x", "x", crawler, None)
    assert "metadata" in result["paper_stage_seconds"] and not hasattr(crawler, "progress")
    report = summarize_attempts([
        {"kind": "paper_attempt", "elapsed_seconds": 10, "cache_hit": False, "success": True,
         "stage_seconds": {"paper_worker": 8}, "paper_stage_seconds": {"source": 6}},
        {"kind": "paper_attempt", "elapsed_seconds": 2, "cache_hit": True, "paper_stage_seconds": {"source": 999}},
        {"http_status": 200, "request_seconds": 1000},
    ])
    assert report["attempts"] == 2 and report["latency"]["mean_s"] == 6
    assert report["cache_latency"]["mean_s"] == 2 and report["work_latency"]["mean_s"] == 10
    assert report["stages"]["worker/source"]["total_s"] == 6
    assert distribution([])["p50_s"] is None
