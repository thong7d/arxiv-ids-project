"""Offline fault-injection tests: no production corpus, secrets or API calls."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import psutil
import pytest

from ids_arxiv.benchmark import BenchmarkSession
from ids_arxiv.checkpoint import (
    PROTOCOL,
    SOURCE_POLICY,
    WorkIndex,
    commit_publication,
    read_json,
    verified_record,
)
from ids_arxiv.crawler.arxiv_client import ArxivCrawler
from ids_arxiv.crawler.http import RequestFailure, get_response
from ids_arxiv.crawler.reference_dates import ReferenceDates
from ids_arxiv.crawler.runner import run_crawling_pipeline
from ids_arxiv.crawler.s2_client import SemanticScholarClient
from ids_arxiv.crawler.shared_quota import SharedQuota
from ids_arxiv.crawler.withdrawals import classify_withdrawal
from ids_arxiv.io_worker import handle
from ids_arxiv.isolation import IsolatedService, TaskTimeout
from ids_arxiv.runtime import launch_detached, process_identity, stop_owned_worker, worker_health
from ids_arxiv.storage import atomic_json, file_inventory, sha256_file


def publication(root):
    root.mkdir(parents=True)
    (root / "v1").mkdir()
    (root / "v1/main.tex").write_text("source", encoding="utf-8")
    atomic_json(root / "metadata.json", {
        "title": "Test", "authors": [], "submission_date": "2025-09-01T00:00:00Z",
        "metadata_quality_version": 3, "metadata_dates_complete": True,
        "version_metadata_complete": True, "version_metadata": {"1": {"title": "Test"}},
        "version_dates": {"1": "2025-09-01T00:00:00Z"},
        "version_date_sources": {"1": "arxiv_atom_published"},
    })
    atomic_json(root / "references.json", {})
    atomic_json(root / "references_all.json", [])
    record = {"schema_version": PROTOCOL, "arxiv_id": "2509.01047", "success": True,
              "source_success": True, "metadata_dates_complete": True,
              "references_status": {"success": True, "dates_complete": True, "all_references_retained": True, "raw_count": 0},
              "expected_versions": [1], "commit_state": "staged",
              "versions": [{"version": 1, "success": True, "state": "downloaded",
                            "files": file_inventory(root / "v1"), "source_policy": SOURCE_POLICY}],
              "checksums": {name: sha256_file(root / name) for name in ("metadata.json", "references.json", "references_all.json")}}
    atomic_json(root / "crawl_status.json", record)
    return record


def test_atomic_replace_failure_preserves_old_checkpoint(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    atomic_json(path, {"old": True})
    monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("FUSE stuck")))
    with pytest.raises(OSError):
        atomic_json(path, {"old": False})
    assert read_json(path) == {"old": True}
    assert not list(tmp_path.glob(".*.tmp"))  # old checkpoint survives; scratch is not a checkpoint


def test_health_detects_zombie_pid_reuse_runtime_and_stall(monkeypatch):
    base = {"pid": 42, "create_time": 10, "runtime_id": "here", "heartbeat_epoch": 100}
    monkeypatch.setattr("ids_arxiv.runtime.runtime_id", lambda: "here")
    identity = {**base, "process_status": psutil.STATUS_RUNNING}
    monkeypatch.setattr("ids_arxiv.runtime.process_identity", lambda pid: identity)
    assert worker_health(base, now=110)["health"] == "RUNNING"
    assert worker_health({**base, "runtime_id": "elsewhere"}, now=110)["health"] == "UNKNOWN"
    identity["process_status"] = psutil.STATUS_ZOMBIE
    assert worker_health(base, now=110)["health"] == "STOPPED"
    identity.update(process_status=psutil.STATUS_RUNNING, create_time=20)
    assert worker_health(base, now=110)["reason"] == "pid_reused"
    identity["create_time"] = 10
    assert worker_health(base, now=200)["health"] == "STALLED"
    assert worker_health({**base, "stage": "retry_wait", "next_retry_epoch": 120}, now=110)["health"] == "WAITING"
    assert worker_health({**base, "stage_deadline_epoch": 105}, now=110)["health"] == "STALLED"


def test_stop_refuses_remote_pid_and_current_kernel():
    assert stop_owned_worker({"runtime_id": "not-this-vm", "pid": os.getpid()})["health"] == "UNKNOWN"
    record = {**process_identity(os.getpid()), "heartbeat_epoch": time.time()}
    with pytest.raises(RuntimeError, match="kernel"):
        stop_owned_worker(record)


def test_detached_launch_prevents_duplicates_and_uses_local_log(tmp_path, monkeypatch):
    monkeypatch.setattr("ids_arxiv.runtime.tempfile.gettempdir", lambda: str(tmp_path))
    process, record = launch_detached([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, "test")
    try:
        assert Path(record["local_log"]).is_relative_to(tmp_path)
        if hasattr(os, "getpgid"):
            assert os.getpgid(process.pid) != os.getpgrp()
        with pytest.raises(RuntimeError, match="duplicate"):
            launch_detached([sys.executable, "-c", "pass"], tmp_path, "test")
    finally:
        stop_owned_worker(record, grace_seconds=1)
        process.wait(timeout=5)


@pytest.mark.skipif(os.name == "nt", reason="Colab/POSIX process groups")
def test_notebook_group_interrupt_does_not_kill_detached_worker(tmp_path):
    # An isolated synthetic parent group, never this test runner or a live kernel.
    script = """
import json, os, signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
try:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    os.killpg(os.getpgrp(), signal.SIGINT)
    time.sleep(0.1)
    print(json.dumps({'alive': child.poll() is None, 'different_group': os.getpgid(child.pid) != os.getpgrp()}))
finally:
    child.terminate(); child.wait()
"""
    result = subprocess.run([sys.executable, "-c", script], start_new_session=True,
                            capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(result.stdout) == {"alive": True, "different_group": True}


def test_isolated_hung_io_has_deadline_and_service_restarts(tmp_path):
    (tmp_path / "slow_service.py").write_text(
        "import time\nfrom ids_arxiv.isolation import serve\n"
        "def handle(r):\n time.sleep(r.get('delay',0)); return 'ok'\nserve(handle)\n", encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(tmp_path) + os.pathsep + str(Path(__file__).resolve().parents[1] / "src")
    beats = []
    with IsolatedService("slow_service", timeout=3, heartbeat=lambda: beats.append(1), environment=environment) as service:
        assert service.call({}) == "ok"
        started = time.monotonic()
        with pytest.raises(TaskTimeout):
            service.call({"delay": 30}, timeout=0.2)
        assert time.monotonic() - started < 8
        assert service.process is None
        assert service.call({}) == "ok"
    assert beats


def test_commit_verified_and_same_size_corruption_detected(tmp_path):
    local, remote = tmp_path / "local", tmp_path / "remote"
    record = publication(local)
    committed = commit_publication(local, remote, record)
    assert committed["commit_state"] == "committed" and verified_record(remote, committed)
    assert handle({"action": "stage", "remote": str(remote), "local": str(tmp_path / "resume")})["already_committed"]
    (remote / "v1/main.tex").write_text("CORRUP", encoding="utf-8")
    assert not verified_record(remote, committed)
    assert (local / "v1/main.tex").read_text() == "source"


def test_acknowledged_transaction_removes_own_backup_only(tmp_path):
    local, remote = tmp_path / "local", tmp_path / "remote"
    record = publication(local)
    commit_publication(local, remote, record)
    evidence = remote / ".previous-old-user-evidence"
    evidence.write_text("preserve")
    committed = commit_publication(local, remote, record)
    assert verified_record(remote, committed)
    assert list(remote.glob(".previous-*")) == [evidence]
    with pytest.raises(ValueError, match="incomplete"):
        commit_publication(local, remote, {**record, "success": False})
    assert verified_record(remote, read_json(remote / "crawl_status.json"))


def test_unchanged_partial_payload_is_not_uploaded_again(tmp_path, monkeypatch):
    local, remote = tmp_path / "local", tmp_path / "remote"
    record = {**publication(local), "success": False}
    commit_publication(local, remote, record)
    copy = Mock(side_effect=AssertionError("Unchanged payload should not be copied"))
    monkeypatch.setattr("ids_arxiv.checkpoint.shutil.copy2", copy)
    commit_publication(local, remote, record)
    assert not copy.called
    assert not list(remote.glob("*.upload")) and not list(remote.glob(".previous-*"))


def test_upload_failure_preserves_local_and_old_marker(tmp_path, monkeypatch):
    local, remote = tmp_path / "local", tmp_path / "remote"
    record = publication(local)
    first = commit_publication(local, remote, record)
    monkeypatch.setattr("ids_arxiv.checkpoint.shutil.copy2", Mock(side_effect=OSError("Drive failure")))
    with pytest.raises(OSError):
        commit_publication(local, remote, record)
    assert read_json(remote / "crawl_status.json") == first
    assert verified_record(remote, first)
    assert (local / "v1/main.tex").is_file()


def test_extra_uninventoried_file_is_rejected(tmp_path):
    local, remote = tmp_path / "local", tmp_path / "remote"
    record = publication(local)
    committed = commit_publication(local, remote, record)
    (remote / "v1/unexpected.pdf").write_bytes(b"%PDF-extra")
    assert not verified_record(remote, committed)


def test_corrupt_uploaded_version_never_gets_success_marker(tmp_path, monkeypatch):
    local, remote = tmp_path / "local", tmp_path / "remote"
    record = publication(local)
    import shutil
    copytree = shutil.copytree

    def corrupt(source, target):
        copytree(source, target)
        (target / "main.tex").write_text("CORRUP", encoding="utf-8")
    monkeypatch.setattr("ids_arxiv.checkpoint.shutil.copytree", corrupt)
    with pytest.raises(OSError, match="checksum"):
        commit_publication(local, remote, record)
    assert not (remote / "crawl_status.json").exists()
    assert (local / "v1/main.tex").read_text() == "source"


def test_ledger_restart_prioritizes_unseen_and_rejects_uncommitted(tmp_path):
    path = tmp_path / "work.sqlite"
    index = WorkIndex(path, "hash", "owner")
    index.seed(["a", "b", "c"], legacy_prefix=1)
    assert index.pending() == ["b", "c", "a"]
    with pytest.raises(ValueError, match="uncommitted"):
        index.update("b", {"success": True})
    index.update("b", {"success": True, "commit_state": "committed"})
    snapshot = index.snapshot()
    index.close()
    index = WorkIndex(path, "hash", "owner")
    assert index.pending() == ["c", "a"]
    index.close()
    other = WorkIndex(tmp_path / "other.sqlite", "hash", "other")
    with pytest.raises(ValueError, match="another"):
        other.restore(snapshot)
    other.close()


def test_publication_date_never_impersonates_submission(tmp_path, monkeypatch):
    client = SemanticScholarClient()
    refs = client._process_references([{"paperId": "s2", "title": "T", "publicationDate": "2020-02-01",
                                     "externalIds": {"ArXiv": "1912.00001"}}])
    resolver = ReferenceDates(tmp_path / "dates.json")
    monkeypatch.setattr("ids_arxiv.crawler.reference_dates.get_response", Mock(side_effect=RequestFailure("offline", 503)))
    assert not resolver.enrich(refs, Mock())
    assert refs["1912-00001"]["publication_date"] == "2020-02-01"
    assert refs["1912-00001"]["submission_date"] is None


def test_missing_intermediate_revision_date_is_never_synthesized(monkeypatch):
    crawler = ArxivCrawler(metadata_cache={"2509.01047": {"title": "T", "authors": [],
        "submission_date": "2025-09-01T00:00:00Z", "latest_updated": "2025-10-01T00:00:00Z", "latest_version": 3}})
    monkeypatch.setattr("ids_arxiv.crawler.arxiv_client.get_response", Mock(side_effect=RequestFailure("offline", 503)))
    metadata, versions = crawler.fetch_metadata("2509.01047")
    assert versions == [1, 2, 3]
    assert metadata["missing_version_dates"] == [2]
    assert "2" not in metadata["version_dates"] and not metadata["metadata_dates_complete"]


def test_deferred_429_does_not_sleep_full_retry_window():
    session, limiter = Mock(), Mock()
    session.get.return_value = Mock(status_code=429, headers={"Retry-After": "120"})
    with pytest.raises(RequestFailure) as failure:
        get_response(session, "https://example.invalid", limiter, defer_on_rate_limit=True)
    assert failure.value.retry_after >= 120
    assert session.get.call_count == 1
    assert limiter.wait.call_count == 1


def test_batch_truncation_is_not_cached_as_complete(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.json.return_value = [{"referenceCount": 2, "references": []}, {"referenceCount": 0, "references": []}]
    monkeypatch.setattr("ids_arxiv.crawler.s2_client.get_response", Mock(return_value=response))
    client = SemanticScholarClient()
    assert client.get_many_references(["2509.01047", "2509.01048"])
    assert "2509.01047" not in client.cache
    assert client.cache["2509.01048"][1]["success"]


def test_missing_references_page_is_not_empty_success(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.json.return_value = {"message": "unexpected provider response"}
    monkeypatch.setattr("ids_arxiv.crawler.s2_client.get_response", Mock(return_value=response))
    client = SemanticScholarClient()
    assert client.get_paper_references("2509.01047") == {}
    assert client.last_status["state"] == "invalid_response"
    assert not client.last_status["success"]


def test_failed_benchmark_mirror_retains_local_journal(tmp_path):
    measured = BenchmarkSession(tmp_path)
    measured.remote = True
    measured.remote_directory = tmp_path / "mock-remote"
    measured.event({"http_status": 429})
    io = Mock()
    io.call.side_effect = TaskTimeout("offline")
    assert not measured.mirror(io)
    assert list(tmp_path.glob("requests-*-*.jsonl"))
    io.call.side_effect = None
    assert measured.mirror(io)


def test_coordinator_resumes_from_index_without_reprocessing(tmp_path):
    import pandas as pd
    manifest = tmp_path / "manifests/papers.parquet"
    manifest.parent.mkdir()
    pd.DataFrame({"arxiv_id": ["2509.01047", "2509.01048"],
                  "dir_id": ["2509-01047", "2509-01048"],
                  "owner_student_id": ["23120358", "23120358"]}).to_parquet(manifest)
    output = tmp_path / "campaign/raw"
    for aid in ("2509-01047", "2509-01048"):
        local = tmp_path / "seed" / aid
        record = publication(local)
        record["arxiv_id"] = aid.replace("-", ".")
        commit_publication(local, output / aid, record)
    first = run_crawling_pipeline(manifest, output, max_seconds=20)
    assert first["success_count"] == 2 and first["cache_hits"] == 2
    probe = run_crawling_pipeline(manifest, output, limit=1, work_namespace="probe",
                                  campaign_mode="full", max_seconds=20)
    assert probe["selected_publications"] == probe["success_count"] == 1
    assert len(read_json(output.parent / "state-v3/index-group.json")["rows"]) == 2
    assert len(read_json(output.parent / "state-v3/index-group-probe.json")["rows"]) == 1
    second = run_crawling_pipeline(manifest, output, max_seconds=20)
    assert second["success_count"] == 2
    assert second["attempts_this_session"] == second["cache_hits"] == 0


def test_student_scope_never_stages_other_members(tmp_path, monkeypatch):
    import pandas as pd

    manifest = tmp_path / "manifests/papers.parquet"
    manifest.parent.mkdir()
    pd.DataFrame({"arxiv_id": ["2508.17872", "2509.01047", "2509.06047"],
                  "dir_id": ["2508-17872", "2509-01047", "2509-06047"],
                  "owner_student_id": ["23120364", "23120358", "23120345"]}).to_parquet(manifest)
    output = tmp_path / "campaign/raw"
    local = tmp_path / "seed/thong"
    record = publication(local)
    record["arxiv_id"] = "2508.17872"
    commit_publication(local, output / "2508-17872", record)
    sentinels = []
    for paper in ("2509-01047", "2509-06047"):
        path = output / paper / "untouched.txt"
        path.parent.mkdir()
        path.write_text("other member's data", encoding="utf-8")
        sentinels.append(path)

    class ScopedService(IsolatedService):
        def call(self, request, timeout=None):
            if request.get("action") in {"stage", "commit"}:
                assert Path(request["remote"]).name == "2508-17872"
            if request.get("action") in {"paper", "prefetch"}:
                pytest.fail("Committed test publication must not issue network work")
            return super().call(request, timeout)

    monkeypatch.setattr("ids_arxiv.crawler.runner.IsolatedService", ScopedService)
    summary = run_crawling_pipeline(manifest, output, student_id="23120364", max_seconds=20)
    assert summary["selected_publications"] == summary["success_count"] == 1
    snapshot = read_json(output.parent / "state-v3/index-23120364.json")
    assert snapshot["meta"]["owner"] == "23120364"
    assert [row[0] for row in snapshot["rows"]] == ["2508.17872"]
    assert not (output.parent / "state-v3/index-group.json").exists()
    for path in sentinels:
        assert path.read_text(encoding="utf-8") == "other member's data"
        assert set(path.parent.iterdir()) == {path}


def test_fair_batches_include_unseen_retry_and_legacy(tmp_path):
    index = WorkIndex(tmp_path / "fair.sqlite", "manifest", "23120364")
    index.seed([str(n) for n in range(100)], legacy_prefix=30)
    for aid in ("30", "31", "32"):
        index.update(aid, {"arxiv_id": aid, "success": False}, next_at=0)
    batch = index.batch(size=8)
    assert len(batch) == len(set(batch)) == 8
    assert any(int(aid) < 30 for aid in batch)
    assert any(aid in {"30", "31", "32"} for aid in batch)
    assert any(int(aid) > 32 for aid in batch)
    index.close()


def test_http_429_opens_shared_circuit_for_single_attempt():
    session, limiter = Mock(), Mock()
    session.get.return_value = Mock(status_code=429, headers={"Retry-After": "125"})
    with pytest.raises(RequestFailure):
        get_response(session, "https://example.invalid", limiter, attempts=1)
    assert limiter.defer.call_args.args[0] >= 125


def test_prefetch_missing_id_can_reach_paginated_fallback(monkeypatch):
    from concurrent.futures import Future
    client = SemanticScholarClient(deferred=True)
    client.limiter = Mock()
    client.limiter.ready_in.return_value = 0
    client.batch_attempted.add("2509.01047")
    completed = Future()
    completed.set_result(False)
    client.prefetch_future = completed
    assert not client.prefetch(["2509.01047"])
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.json.return_value = {"data": []}
    get = Mock(return_value=response)
    monkeypatch.setattr("ids_arxiv.crawler.s2_client.get_response", get)
    assert client.get_paper_references("2509.01047") == {}
    assert client.last_status["success"]
    assert get.call_args.args[1].endswith("/references")


def test_reference_date_backlog_is_batched_and_retains_unknowns(tmp_path, monkeypatch):
    resolver = ReferenceDates(tmp_path / "dates.json")
    refs = {"2001-00001": {"submission_date": None, "date_source": "unknown"}}
    resolver.enqueue({"2001-00002": {"submission_date": None}})
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.content = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2001.00001v1</id><title>T</title><published>2020-01-01T00:00:00Z</published></entry></feed>'
    get = Mock(return_value=response)
    monkeypatch.setattr("ids_arxiv.crawler.reference_dates.get_response", get)
    assert resolver.enrich(refs, Mock())
    assert set(get.call_args.kwargs["params"]["id_list"].split(",")) == {"2001.00001", "2001.00002"}
    assert get.call_count == 1
    assert "2001.00002" in resolver.pending
    assert refs["2001-00001"]["submission_date"] == "2020-01-01T00:00:00Z"


@pytest.mark.parametrize("version", [1, 2])
def test_recent_atom_provides_every_date_for_simple_versions(monkeypatch, version):
    client = ArxivCrawler(metadata_cache={"2509.01047": {
        "title": "T", "authors": [], "latest_version": version,
        "submission_date": "2025-09-01T00:00:00Z", "latest_updated": "2025-10-01T00:00:00Z",
        "atom_fetched_epoch": time.time(),
        "version_metadata": {"1": {"title": "T", "authors": [], "submission_date": "2025-09-01T00:00:00Z",
                                    "latest_updated": "2025-09-01T00:00:00Z", "latest_version": 1}},
    }})
    get = Mock(side_effect=AssertionError("Recent complete Atom must not query OAI"))
    monkeypatch.setattr("ids_arxiv.crawler.arxiv_client.get_response", get)
    metadata, versions = client.fetch_metadata("2509.01047")
    assert versions == list(range(1, version + 1)) and metadata["metadata_dates_complete"]
    assert metadata["metadata_source"] == "arxiv_atom_recent_batch"
    assert metadata["version_dates"]["1"].startswith("2025-09-01")
    if version == 2:
        assert metadata["version_dates"]["2"].startswith("2025-10-01")
    get.assert_not_called()


def test_metadata_batch_only_updates_requested_ids(monkeypatch):
    client = ArxivCrawler()
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.content = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2509.01047v2</id><title>T</title><published>2025-09-01T00:00:00Z</published><updated>2025-10-01T00:00:00Z</updated></entry><entry><id>http://arxiv.org/abs/2509.06047v1</id><title>Other</title><published>2025-09-01T00:00:00Z</published></entry></feed>'
    def returned(*args, **kwargs):
        if "v1" in kwargs.get("params", {}).get("id_list", ""):
            old = Mock()
            old.__enter__ = Mock(return_value=old)
            old.__exit__ = Mock(return_value=False)
            old.content = response.content.replace(b"2509.01047v2", b"2509.01047v1")
            return old
        return response
    get = Mock(side_effect=returned)
    monkeypatch.setattr("ids_arxiv.crawler.arxiv_client.get_response", get)
    result = client.prefetch_metadata(["2509.01047"])
    assert result["updated"] == 2
    assert "2509.06047" not in client.metadata_cache
    assert client.metadata_cache["2509.01047"]["latest_version"] == 2
    assert client.prefetch_metadata(["2509.01047"])["updated"] == 0
    assert get.call_count == 2


def test_withdrawal_evidence_requires_correct_version_and_no_pdf():
    html = '<p>This paper has been withdrawn by an author.</p><p>No PDF available</p><p>arXiv:2508.21423v3</p>'
    assert classify_withdrawal(html, "2508.21423", 3)["verified"]
    assert not classify_withdrawal(html, "2508.21423", 2)["verified"]
    assert not classify_withdrawal(html.replace('No PDF available', 'View PDF'), "2508.21423", 3)["verified"]


def test_withdrawal_evidence_does_not_trust_script_text():
    html = '<script>This paper has been withdrawn. No PDF available arXiv:2508.21423v3</script><p>Normal publication</p>'
    assert not classify_withdrawal(html, "2508.21423", 3)["verified"]


def test_s2_prefetch_is_opt_in_not_required_for_pagination(monkeypatch):
    monkeypatch.delenv("IDS_S2_BATCH_PREFETCH", raising=False)
    client = SemanticScholarClient(deferred=True)
    assert not client.prefetch(["2509.01047"])
    assert client.prefetch_pool is None and client.prefetch_future is None


def test_terminal_http_error_has_evidence_without_credentials():
    session, limiter = Mock(), Mock()
    response = Mock(status_code=404, headers={}, content=b'{"message":"paper not found"}')
    session.get.return_value = response
    with pytest.raises(RequestFailure) as failure:
        get_response(session, "https://example.invalid/paper/ARXIV:2509.01047", limiter, attempts=1)
    evidence = failure.value.evidence
    assert evidence["http_status"] == 404 and len(evidence["response_sha256"]) == 64
    assert set(evidence) == {"url", "http_status", "checked_at", "response_sha256"}


def test_shared_backoff_is_adaptive_and_never_ignores_retry_after(tmp_path, monkeypatch):
    quota = SharedQuota(3.05, "s2", "offline-test-key")
    quota.path, quota.lock = tmp_path / "quota.json", tmp_path / "quota.lock"
    clock = [100.0]
    monkeypatch.setattr("ids_arxiv.crawler.shared_quota.time.monotonic", lambda: clock[0])
    assert quota.rate_limited() == 5
    clock[0] += 6
    assert quota.rate_limited() == 10
    clock[0] += 11
    assert quota.rate_limited(300) == 300
    quota.reset_backoff()
    clock[0] += 301
    assert quota.rate_limited() == 5
