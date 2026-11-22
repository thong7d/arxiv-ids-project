import json
import sys

from ids_arxiv import team_run
from ids_arxiv.checkpoint import PROTOCOL
from ids_arxiv.colab_app import default_config


def test_run_all_does_not_reopen_frozen_corpus(monkeypatch, tmp_path, capsys):
    config = default_config("23120364", tmp_path)
    class IO:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def call(self, request):
            assert request["action"] == "read_json" and request["path"].endswith("closure.json")
            return {"operational_closed": True, "protocol_version": PROTOCOL,
                    "counts": {"full_success": 4959, "verified_exception": 37, "references_unavailable": 4},
                    "collection_closed": False}
    monkeypatch.setattr(team_run, "IsolatedService", IO)
    monkeypatch.setattr(team_run, "current_worker_record", lambda owner: ({}, {"health": "STOPPED"}))
    def forbidden(*a, **kw):
        raise AssertionError("Frozen corpus must not launch another crawler")
    monkeypatch.setattr(team_run, "launch_detached", forbidden)
    monkeypatch.setattr(sys, "argv", ["team_run", "launch", "--config-json", json.dumps(config), "--stage", "auto"])
    team_run.main()
    output = json.loads(capsys.readouterr().out)
    assert output["not_launched"] and not output["collection_closed"]


def test_finalize_freeze_s2_rate_limited_closes_operationally(monkeypatch, tmp_path):
    import pandas as pd
    from pathlib import Path
    from ids_arxiv import audit_service, finalize as fin
    from ids_arxiv.checkpoint import SOURCE_POLICY
    from ids_arxiv.storage import atomic_json, file_inventory, sha256_file

    aid = "2509.06047"
    ids = [aid] + [f"2509.{10000 + i}" for i in range(4999)]
    drive_root = tmp_path / "drive"
    manifest_dir = drive_root / "m1-final-v3" / "manifests"
    manifest_dir.mkdir(parents=True)
    parquet_path = manifest_dir / "papers.parquet"
    pd.DataFrame({"arxiv_id": ids, "owner_student_id": ["23120345"] * 5000}).to_parquet(parquet_path)
    atomic_json(parquet_path.with_suffix(".json"), {
        "verified_discovery": True, "manifest_sha256": sha256_file(parquet_path),
    })

    base = drive_root / "m1-team-v4" / "23120345" / "main" / "full" / "23120345"
    paper_dir = base / "raw" / "2509-06047"
    (paper_dir / "v1").mkdir(parents=True)
    (paper_dir / "v1" / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
    atomic_json(paper_dir / "metadata.json", {
        "title": "Test", "submission_date": "2025-09-01T00:00:00Z", "metadata_quality_version": 3,
        "metadata_dates_complete": True, "version_dates": {"1": "2025-09-01T00:00:00Z"},
        "version_date_sources": {"1": "arxiv_atom_published"},
        "version_metadata_complete": True, "version_metadata": {"1": {"title": "Test"}},
    })
    atomic_json(paper_dir / "references.json", {})
    atomic_json(paper_dir / "references_all.json", [])
    record = {
        "schema_version": PROTOCOL, "arxiv_id": aid, "commit_state": "committed", "commit_id": "test",
        "success": False, "source_success": True, "metadata_dates_complete": True, "attempt_count": 17,
        "expected_versions": [1],
        "versions": [{"version": 1, "success": True, "state": "downloaded",
                      "source_policy": SOURCE_POLICY, "files": file_inventory(paper_dir / "v1")}],
        "references_status": {"state": "deferred", "success": False, "http_status": None},
        "checksums": {name: sha256_file(paper_dir / name)
                      for name in ("metadata.json", "references.json", "references_all.json")},
    }
    atomic_json(paper_dir / "crawl_status.json", record)

    config = default_config("23120345", drive_root)
    config["code_root"] = str(tmp_path)

    class IO:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def call(self, req):
            act = req["action"]
            if act == "read_json":
                rp = Path(req["path"])
                return json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else req.get("default")
            if act == "write_json":
                atomic_json(Path(req["path"]), req["value"])
                return {"ok": True}
            if act == "copy":
                Path(req["target"]).write_bytes(Path(req["source"]).read_bytes())
                return {"ok": True}
            return {}

    init_calls = []

    class Audit:
        def __init__(self, *a, **kw):
            self.process = None
        def close(self): pass
        def call(self, req):
            if req.get("action") == "init":
                audit_service.context.clear()
                init_calls.append(req)
                self.process = type("P", (), {"poll": lambda s: None})()
                return audit_service.handle(req)
            if req.get("arxiv_id") == aid:
                return audit_service.handle(req)
            return {"arxiv_id": req["arxiv_id"], "classification": "references_unavailable",
                    "reasons": [], "withdrawn_versions": [], "data_download_success": False,
                    "commit_marker_sha256": "synthetic"}

    monkeypatch.setattr(fin, "IsolatedService", lambda module, *a, **kw: IO() if "io_worker" in module else Audit())
    monkeypatch.setattr(fin, "current_worker_record", lambda owner: ({}, {"health": "STOPPED"}))
    monkeypatch.setattr(fin, "validate_config", lambda cfg: cfg)

    report = fin.finalize(config, freeze_s2_404=True, freeze_s2_rate_limited=True, resume=False)
    assert init_calls and init_calls[0]["allow_s2_rate_limited"] is True
    assert report["operational_closed"] is True
    assert report["collection_closed"] is False
    assert report["counts"] == {"references_unavailable": 5000}
    assert report["s2_rate_limited_freeze_authorized"] is True
