import json
from types import SimpleNamespace

import pytest

from ids_arxiv import workflow


def fake_io(monkeypatch, receipt):
    class IO:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def call(self, request):
            assert request["action"] == "read_json"
            return receipt
    monkeypatch.setattr(workflow, "IsolatedService", IO)


def test_one_owner_and_stable_owner_namespace(tmp_path):
    owner = "23120358"
    direct = workflow.workflow_config(owner, tmp_path)
    helper = workflow.workflow_config("23120364", tmp_path, target_owner_ids=[owner])
    assert workflow.corpus_base(direct) == workflow.corpus_base(helper)
    assert direct["max_network_passes"] == 3
    with pytest.raises(ValueError, match="exactly one"):
        workflow.workflow_config("23120364", tmp_path, target_owner_ids=[owner, "23120345"])


@pytest.mark.parametrize("receipt", [{"operational_closed": True}, {"automatic_retry_suppressed": True}])
def test_closed_selection_does_not_stop_other_owner(tmp_path, monkeypatch, receipt):
    fake_io(monkeypatch, receipt)
    def forbidden(*args, **kwargs):
        raise AssertionError("Closed selection must not stop or launch work")
    monkeypatch.setattr(workflow, "active_local_jobs", forbidden)
    monkeypatch.setattr(workflow, "launch_detached", forbidden)
    assert workflow.start(workflow.workflow_config("23120364", tmp_path))["not_launched"]


def test_switch_stops_only_owned_local_workflow(tmp_path, monkeypatch):
    fake_io(monkeypatch, {})
    job = {"pid": 321, "create_time": 12.0, "owner": "23120364", "workflow": True}
    calls = []
    monkeypatch.setattr(workflow, "active_local_jobs", lambda: [job] if not calls else [])
    record = {**job, "runtime_id": workflow.runtime_id()}
    monkeypatch.setattr(workflow, "current_worker_record", lambda owner: (record, {}))
    monkeypatch.setattr(workflow, "stop_owned_worker", lambda value, **kw: calls.append(value))
    monkeypatch.setattr(workflow, "launch_detached", lambda *args: (SimpleNamespace(pid=444), {"run_id": "new"}))
    assert workflow.start(workflow.workflow_config("23120358", tmp_path))["launched"] == 444
    assert calls == [record]


def test_never_stop_remote_or_unowned_job(tmp_path, monkeypatch):
    fake_io(monkeypatch, {})
    monkeypatch.setattr(workflow, "active_local_jobs", lambda: [
        {"pid": 321, "create_time": 12.0, "owner": "23120364", "workflow": True}])
    monkeypatch.setattr(workflow, "current_worker_record", lambda owner: (
        {"pid": 321, "create_time": 12.0, "runtime_id": "different-machine"}, {}))
    def forbidden(*args, **kwargs):
        raise AssertionError("Must not signal a foreign runtime or launch duplicates")
    monkeypatch.setattr(workflow, "stop_owned_worker", forbidden)
    monkeypatch.setattr(workflow, "launch_detached", forbidden)
    assert workflow.start(workflow.workflow_config("23120358", tmp_path))["not_launched"]


def test_new_worker_receives_only_selected_owner(tmp_path, monkeypatch):
    fake_io(monkeypatch, {})
    monkeypatch.setattr(workflow, "active_local_jobs", lambda: [])
    captured = []
    def launch(command, code, owner, env):
        captured.append(json.loads(command[-1]))
        assert owner == "23120345"
        return SimpleNamespace(pid=123), {"run_id": "one"}
    monkeypatch.setattr(workflow, "launch_detached", launch)
    workflow.start(workflow.workflow_config("23120345", tmp_path))
    assert captured[0]["target_owner_ids"] == ["23120345"]


@pytest.mark.parametrize("has_prior_audit,cutoff", [(False, False), (True, False), (False, True)])
def test_crawl_then_audit_stops_for_review_without_reopening(tmp_path, monkeypatch, has_prior_audit, cutoff):
    import time
    from pathlib import Path

    original_is_dir = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda self: True if str(self).replace("\\", "/") == "/content" else original_is_dir(self))
    monkeypatch.setenv("COLAB_RELEASE_TAG", "test")
    monkeypatch.setenv("COLAB_GPU", "0")
    monkeypatch.setenv("IDS_LOCAL_STATE_DIR", str(tmp_path / "control"))
    writes, phases = {}, []
    class IO:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def call(self, request):
            if request["action"] == "read_json":
                if request["path"].endswith("audit-result.json") and has_prior_audit:
                    return {"records": ["prior"]}
                return {}
            if request["action"] == "cache_catalog":
                return []
            if request["action"] == "write_json":
                writes[request["path"]] = request["value"]
                return True
            raise AssertionError(request)
    monkeypatch.setattr(workflow, "IsolatedService", IO)
    def crawl(manifest, destination, **kwargs):
        assert kwargs["student_id"] == "23120345" and kwargs["max_network_passes"] == 3
        phases.append("crawl")
        return {"pending_count": int(cutoff), "failed_ids": ["2509.06047"],
                "selected_publications": 5000, "total_attempted": 5000,
                "upload_pending_count": 0, "uncommitted_attempt_count": 0,
                "next_retry_epoch": time.time() + 86400}
    monkeypatch.setattr(workflow, "run_crawling_pipeline", crawl)
    monkeypatch.setattr(workflow, "collect_source_evidence", lambda *args: phases.append("evidence"))
    def audit(config, **kwargs):
        assert kwargs["repair_pending"] == has_prior_audit
        phases.append("audit")
        return {"operational_closed": False, "counts": {"pending": 1},
                "records": [{"arxiv_id": "2509.06047", "classification": "pending", "reasons": ["HTTP 429"]}]}
    monkeypatch.setattr(workflow, "finalize", audit)
    report = workflow.execute(workflow.workflow_config("23120345", tmp_path))
    assert phases == (["audit"] if has_prior_audit else ["crawl", "evidence", "audit"])
    receipt = next(value for key, value in writes.items() if key.endswith("closure.json"))
    assert receipt["automatic_retry_suppressed"] and receipt["workflow_finished"]
    assert not report["operational_closed"]
    if cutoff:
        assert report["crawl_stop"]["reason"] == "next_retry_beyond_wait_budget"
        assert any(path.endswith("crawl-stop.json") for path in writes)
        assert receipt["crawl_stop"]["pending_count"] == 1


def test_monitor_distinguishes_import_progress_from_full_success(tmp_path, monkeypatch, capsys):
    from ids_arxiv.colab_app import ColabApp, default_config
    app = ColabApp(default_config("23120345", tmp_path, workflow_mode="bounded"))
    monkeypatch.setattr(app, "snapshot", lambda: {
        "selected_owner": "23120345", "local_health": {"health": "RUNNING"}, "owners": {},
        "local_record": {"stage": "crawl", "run_id": "one", "crawl": {
            "stage": "check_cache", "current_paper": "2509.06376", "summary": {
                "total_attempted": 329, "selected_publications": 5000,
                "source_success_count": 328, "reference_success_count": 72}}}})
    app.monitor(seconds=0)
    output = capsys.readouterr().out
    assert "329/5000" in output and "source: 328" in output and "references: 72" in output
    assert "check_cache" in output and "2509.06376" in output


def test_future_retry_cutoff_never_skips_unseen_or_uncommitted_data():
    summary = {"selected_publications": 5000, "total_attempted": 5000, "pending_count": 12,
               "upload_pending_count": 0, "uncommitted_attempt_count": 0, "next_retry_epoch": 90000}
    assert workflow.future_retry_cutoff(summary, now=100)
    assert not workflow.future_retry_cutoff({**summary, "total_attempted": 4999}, now=100)
    assert not workflow.future_retry_cutoff({**summary, "upload_pending_count": 1}, now=100)
    assert not workflow.future_retry_cutoff({**summary, "uncommitted_attempt_count": 1}, now=100)
    assert not workflow.future_retry_cutoff({**summary, "next_retry_epoch": 1900}, now=100)  # Exactly 30 min: wait.
    assert not workflow.future_retry_cutoff({**summary, "next_retry_epoch": 1300}, now=100)  # Normal UTC turn.
    unknown = {k: v for k, v in summary.items() if k != "uncommitted_attempt_count"}
    assert not workflow.future_retry_cutoff(unknown, now=100)
    assert not workflow.future_retry_cutoff({**summary, "pending_count": None}, now=100)
