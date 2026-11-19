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
