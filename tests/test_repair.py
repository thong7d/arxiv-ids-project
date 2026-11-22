import copy

import pytest

from ids_arxiv.repair import build_plan, validate_plan


def audit_fixture():
    rows = [{"arxiv_id": f"2509.{n:05d}", "classification": "full_success", "reasons": []}
            for n in range(6047, 11047)]
    rows[0].update(classification="pending", reasons=["References/date retrieval incomplete"])
    rows[1].update(classification="pending", reasons=["Version dates not verified"])
    rows[2].update(classification="pending", reasons=["ids_arxiv.audit_service: task exceeded deadline"])
    rows[3].update(classification="verified_exception")
    return {"student_id": "23120345", "protocol_version": 4,
            "discovery_manifest_sha256": "manifest", "records": rows,
            "missing_ids": [], "outside_ids": [], "duplicate_ids": []}


def test_pending_only_metadata_first_one_finite_pass():
    audit = audit_fixture()
    plan = build_plan(audit, "23120345", "manifest")
    assert [r["arxiv_id"] for r in plan["targets"]] == ["2509.06048", "2509.06047", "2509.06049"]
    assert plan["additional_network_passes"] == 1 and plan["max_seconds"] == 32400
    assert plan["targets"][-1]["audit_only"]
    assert validate_plan(plan, audit, [r["arxiv_id"] for r in audit["records"]]) == plan


def test_stale_tampered_or_wrong_owner_is_rejected():
    audit = audit_fixture()
    plan = build_plan(audit, "23120345", "manifest")
    ids = [r["arxiv_id"] for r in audit["records"]]
    changed = copy.deepcopy(audit)
    changed["records"][0]["classification"] = "full_success"
    with pytest.raises(ValueError, match="Audit changed"):
        validate_plan(plan, changed, ids)
    with pytest.raises(ValueError, match="checksum"):
        validate_plan({**plan, "max_seconds": 600}, audit, ids)
    with pytest.raises(ValueError):
        build_plan(audit, "23120358", "manifest")
    with pytest.raises(ValueError):
        build_plan(audit, "23120345", "other-manifest")
    with pytest.raises(ValueError):
        validate_plan(plan, audit, ids[:-1])
    with pytest.raises(ValueError):
        build_plan(audit, "23120345", "manifest", max_seconds=36000)


def test_prepare_changes_only_staged_copy(tmp_path):
    import json
    from ids_arxiv.repair import prepare_local
    local = tmp_path/"local"
    remote = tmp_path/"remote"
    local.mkdir()
    remote.mkdir()
    for directory in (local, remote):
        (directory/"crawl_status.json").write_text(json.dumps({"success": True, "commit_state": "committed"}))
        (directory/"metadata.json").write_text(json.dumps({"metadata_dates_complete": True, "title": "retained"}))
    prepare_local(local, metadata_refresh=True)
    assert json.loads((remote/"crawl_status.json").read_text())["success"]
    assert json.loads((remote/"metadata.json").read_text())["metadata_dates_complete"]
    assert not json.loads((local/"metadata.json").read_text())["metadata_dates_complete"]
    assert json.loads((local/"metadata.json").read_text())["title"] == "retained"


def test_repair_reserves_before_network_commits_then_audits(tmp_path, monkeypatch):
    import json
    import pandas as pd
    from ids_arxiv import repair, isolation, finalize, network_schedule
    from ids_arxiv.storage import sha256_file
    from ids_arxiv.workflow import workflow_config, corpus_base
    owner = "23120345"
    config = workflow_config(owner, tmp_path)
    base = corpus_base(config)
    manifest = tmp_path/"m1-final-v3/manifests/papers.parquet"
    manifest.parent.mkdir(parents=True)
    audit = audit_fixture()
    for row in audit["records"]:
        row["commit_marker_sha256"] = "marker"
    pd.DataFrame({"arxiv_id": [r["arxiv_id"] for r in audit["records"]], "owner_student_id": owner}).to_parquet(manifest)
    audit["discovery_manifest_sha256"] = sha256_file(manifest)
    saved = {str(base/"audit-result.json"): audit,
             str(manifest.with_suffix(".json")): {"verified_discovery": True, "manifest_sha256": sha256_file(manifest)}}
    events = []
    class Service:
        def __init__(self, module, **kwargs):
            self.module, self.process = module, None
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def call(self, req, **kwargs):
            action = req["action"]
            if action == "read_json":
                if req["path"].endswith("crawl_status.json"):
                    return {"bounded_network_passes": 3}
                return saved.get(req["path"], {})
            if action == "write_json":
                saved[req["path"]] = json.loads(json.dumps(req["value"]))
                return True
            if action == "copy":
                import shutil
                shutil.copyfile(req["source"], req["target"])
                return True
            if action == "marker_hash":
                return "marker"
            if action == "stage":
                from pathlib import Path
                local = Path(req["local"])
                local.mkdir(parents=True, exist_ok=True)
                (local/"crawl_status.json").write_text(json.dumps({"success": False}))
                (local/"metadata.json").write_text(json.dumps({"metadata_dates_complete": True}))
                return {}
            if action == "init":
                return {}
            if action == "paper":
                aid = req["arxiv_id"]
                assert saved[str(base/"repair-progress.json")]["attempted"][aid]["state"] == "attempt_reserved"
                events.append(("paper", aid))
                return {"success": False, "arxiv_id": aid}
            if action == "commit":
                events.append(("commit", req["record"]["arxiv_id"]))
                return {}
            raise AssertionError(action)
    def audit_again(*args, **kwargs):
        assert kwargs["repair_pending"]
        events.append(("audit", None))
        return {**audit, "operational_closed": False, "counts": {"pending": 3}}
    run = tmp_path/"run"
    run.mkdir()
    monkeypatch.setenv("IDS_LOCAL_STATE_DIR", str(run))
    monkeypatch.setattr(isolation, "IsolatedService", Service)
    monkeypatch.setattr(finalize, "finalize", audit_again)
    monkeypatch.setattr(network_schedule, "configured_window", lambda: None)
    repair.execute(config)
    assert events == [("paper", "2509.06048"), ("commit", "2509.06048"),
                      ("paper", "2509.06047"), ("commit", "2509.06047"), ("audit", None)]
    assert saved[str(base/"repair-progress.json")]["finished"]
    assert saved[str(base/"closure.json")]["automatic_retry_suppressed"]
    assert not saved[str(base/"closure.json")]["operational_closed"]


def test_s2_wait_cap_sleeps_short_cooldown_and_defers_long_cooldown(monkeypatch):
    from unittest.mock import Mock
    from ids_arxiv.crawler.s2_client import SemanticScholarClient

    slept = []
    monkeypatch.setattr("ids_arxiv.crawler.s2_client.time.sleep", slept.append)
    client = SemanticScholarClient(deferred=True)
    client.limiter = Mock()
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.json.return_value = {"data": []}
    monkeypatch.setattr("ids_arxiv.crawler.s2_client.get_response", Mock(return_value=response))

    monkeypatch.setenv("IDS_S2_WAIT_CAP_SECONDS", "65")
    client.limiter.ready_in.return_value = 5.0
    assert client.get_paper_references("2509.06047") == {}
    assert slept == [5.0] and client.last_status["success"]

    slept.clear()
    client.limiter.ready_in.return_value = 120.0
    assert client.get_paper_references("2509.06048") == {}
    assert slept == [] and client.last_status["state"] == "deferred"

