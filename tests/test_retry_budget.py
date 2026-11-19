import pytest

from ids_arxiv.retry_budget import bounded_result, had_http_activity


def partial():
    return {"success": False, "commit_state": "committed", "metadata_dates_complete": True,
            "metadata_versions_complete": True, "source_success": True,
            "references_status": {"state": "retryable_error", "http_status": 429}}


def test_deferred_wait_is_not_charged_and_budget_is_finite():
    row = partial()
    for _ in range(20):
        row, state = bounded_result(row, row, 3)
        assert state is None and row["bounded_network_passes"] == 0
    for number in range(1, 4):
        row, state = bounded_result(row, row, 3, http_activity=True)
        assert row["bounded_network_passes"] == number
    assert state == "quarantined" and not row["success"]
    assert row["automatic_stop_reason"] == "network_pass_budget_exhausted"


def test_upload_pending_is_never_hidden_and_404_is_not_faked_success():
    row = partial()
    row["commit_state"] = "upload_pending"
    assert bounded_result({"bounded_network_passes": 3}, row, 3)[1] is None
    row = partial()
    row["references_status"] = {"state": "not_indexed", "http_status": 404}
    result, state = bounded_result({}, row, 3, http_activity=True)
    assert state == "quarantined" and not result["success"]


def test_http_activity_excludes_utc_window_wait_and_partial_lines(tmp_path):
    path = tmp_path / "events"
    path.write_text('{"kind":"network_window_wait"}\nnot-json\n')
    assert not had_http_activity(path, 0)
    path.write_text('{"http_status":429}\n')
    assert had_http_activity(path, 0)
    with pytest.raises(ValueError):
        bounded_result({}, partial(), 0)


def test_source_and_references_404_go_to_audit_without_waiting_24_hours():
    row = partial()
    row.update(source_success=False, versions=[{"version": 1, "success": False, "error": "HTTP 404"}],
               references_status={"success": False, "state": "not_indexed", "http_status": 404},
               next_retry_epoch=86400)
    result, state = bounded_result({}, row, 3, http_activity=True)
    assert state == "quarantined" and result["automatic_stop_reason"] == "observed_404_needs_audit"
    assert result["success"] is False and result["next_retry_epoch"] == 86400
    row["metadata_versions_complete"] = False
    assert bounded_result({}, row, 3, http_activity=True)[1] is None  # Metadata can still be repaired.


def test_durable_budget_survives_missing_local_ledger_without_network(tmp_path, monkeypatch):
    import pandas as pd

    from ids_arxiv.checkpoint import PROTOCOL, commit_publication
    from ids_arxiv.crawler import runner
    from ids_arxiv.io_worker import handle

    manifest = tmp_path / "papers.parquet"
    pd.DataFrame([{"arxiv_id": "2509.01047", "owner_student_id": "23120358"}]).to_parquet(manifest)
    (tmp_path / "discovery").mkdir()
    (tmp_path / "discovery/metadata.json").write_text("{}")
    local = tmp_path / "original"
    local.mkdir()
    record = {**partial(), "schema_version": PROTOCOL, "arxiv_id": "2509.01047",
              "bounded_network_passes": 3, "versions": [], "checksums": {}}
    output = tmp_path / "corpus" / "raw"
    commit_publication(local, output / "2509-01047", record)
    monkeypatch.setattr(runner.tempfile, "gettempdir", lambda: str(tmp_path / "new-vm"))
    class Service:
        def __init__(self, module, *args, **kwargs):
            self.module = module
            self.process = None
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def call(self, request):
            assert self.module == "ids_arxiv.io_worker", "Exhausted paper must never contact a network worker"
            return handle(request)
    monkeypatch.setattr(runner, "IsolatedService", Service)
    result = runner.run_crawling_pipeline(manifest, output, student_id="23120358", max_network_passes=3, max_seconds=10)
    assert result["pending_count"] == 0 and result["quarantined_count"] == 1
    assert result["success_count"] == 0


def test_ledger_reports_upload_and_uncommitted_work_for_safe_wait_cutoff(tmp_path):
    from ids_arxiv.checkpoint import WorkIndex
    index = WorkIndex(tmp_path / "ledger.sqlite", "manifest", "owner")
    try:
        index.seed(["a", "b", "c"])
        index.update("a", {"arxiv_id": "a", "success": False, "commit_state": "committed"})
        index.update("b", {"arxiv_id": "b", "success": False, "commit_state": "upload_pending"}, state="upload_pending")
        stats = index.stats()
        assert stats["total_attempted"] == 2 and stats["upload_pending_count"] == 1
        assert stats["uncommitted_attempt_count"] == 1
        index.update("b", {"arxiv_id": "b", "success": False, "commit_state": "committed"})
        assert index.stats()["uncommitted_attempt_count"] == 0
    finally:
        index.close()
