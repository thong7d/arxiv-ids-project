"""No upstream calls: validate the independent runner and revised data contract."""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from ids_arxiv.bounded_http import NetworkWindowClosed, scheduled_arxiv
from ids_arxiv.cache_migration import import_source_cache
from ids_arxiv.checkpoint import PROTOCOL, SOURCE_POLICY
from ids_arxiv.crawler.arxiv_client import ArxivCrawler
from ids_arxiv.crawler.s2_client import SemanticScholarClient
from ids_arxiv.network_schedule import RUNNERS, NetworkWindow
from ids_arxiv.storage import atomic_json, file_inventory, sha256_file
from ids_arxiv.team_run import output_root, validate_config


def make_tar(path, files):
    with tarfile.open(path, "w:gz") as archive:
        for name, body in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))


def test_only_tex_bib_extracted_and_original_figure_code_retained(tmp_path):
    tex = b"\\documentclass{article}\n\\begin{figure}\\includegraphics{a.png}\\end{figure}\n% latin1: \xe9"
    source = tmp_path / "source.gz"
    files = {"main.tex": tex, "refs.bib": b"@book{a}", "main.bbl": b"do not retain", "a.png": b"image", "x.sty": b"style"}
    make_tar(source, files)
    target = tmp_path / "text"
    target.mkdir()
    crawler = ArxivCrawler()
    assert crawler._safe_extract(source, target)
    assert {p.name for p in target.iterdir()} == {"main.tex", "refs.bib"}
    assert (target / "main.tex").read_bytes() == tex
    assert crawler.last_extraction_stats["initial_bytes"] == sum(map(len, files.values()))


def test_valid_word_container_is_an_explicit_empty_source(tmp_path, monkeypatch):
    archive = tmp_path / "word.docx"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("[Content_Types].xml", "types")
        zipped.writestr("word/document.xml", "document")
    crawler = ArxivCrawler()
    monkeypatch.setattr(crawler, "_download_source", lambda url, destination: (shutil.copyfile(archive, destination), 1)[1])
    target = tmp_path / "v1"
    status = crawler.download_and_extract_version("2508.17872", 1, target)
    assert status["success"] and status["state"] == "non_tex_source"
    assert target.is_dir() and not list(target.iterdir())


def test_all_s2_references_retained_but_published_pool_is_arxiv_only(monkeypatch):
    raw = [{"paperId": "a", "title": "ArXiv", "externalIds": {"ArXiv": "1706.03762"}},
           {"paperId": "b", "title": "Book", "externalIds": {"DOI": "10.1/book"}}, None]
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.json.return_value = {"data": [{"citedPaper": row} for row in raw]}
    monkeypatch.setattr("ids_arxiv.crawler.s2_client.get_response", Mock(return_value=response))
    client = SemanticScholarClient()
    refs = client.get_paper_references("2508.17872")
    assert list(refs) == ["1706-03762"]
    assert client.last_all_references == raw
    assert client.last_status["raw_count"] == 3 and client.last_status["all_references_retained"]


def test_legacy_cache_migration_never_modifies_original(tmp_path):
    source, target = tmp_path / "old", tmp_path / "new"
    (source / "v1").mkdir(parents=True)
    (source / "v1/main.tex").write_bytes(b"original")
    (source / "v1/main.bbl").write_bytes(b"excluded")
    atomic_json(source / "metadata.json", {"title": "Old"})
    atomic_json(source / "references.json", {})
    record = {"arxiv_id": "2508.17872", "schema_version": 3, "success": True,
              "versions": [{"version": 1, "success": True, "state": "downloaded", "source_sha256": "original-archive",
                            "files": file_inventory(source / "v1"), "initial_bytes": 16}],
              "references_status": {"success": True, "raw_count": 2},
              "checksums": {name: sha256_file(source / name) for name in ("metadata.json", "references.json")}}
    atomic_json(source / "crawl_status.json", record)
    original = (source / "crawl_status.json").read_bytes()
    imported = import_source_cache(source, target, "2508.17872")
    assert imported["imported"] and imported["record"]["schema_version"] == PROTOCOL
    assert not imported["record"]["references_status"]["success"]
    assert imported["record"]["versions"][0]["source_policy"] == SOURCE_POLICY
    assert (target / "v1/main.tex").read_bytes() == b"original"
    assert not (target / "v1/main.bbl").exists()
    assert (source / "v1/main.bbl").exists() and (source / "crawl_status.json").read_bytes() == original


def test_utc_windows_never_overlap_including_boundaries():
    windows = [NetworkWindow(runner) for runner in RUNNERS]
    for second in range(3601):
        assert sum(window.status(second)["allowed"] for window in windows) <= 1
    assert not any(window.status(600)["allowed"] for window in windows)
    assert windows[1].status(610)["allowed"]
    assert not windows[0].status(590)["allowed"]


def test_operator_and_data_owner_are_independent_and_outputs_do_not_conflict(tmp_path):
    common = {"drive_root": str(tmp_path), "personal_s2_key_confirmed": True,
              "one_runtime_per_runner_confirmed": True}
    first = validate_config({**common, "runner_id": RUNNERS[0], "target_owner_ids": [RUNNERS[1]]})
    second = validate_config({**common, "runner_id": RUNNERS[1], "target_owner_ids": [RUNNERS[1]]})
    assert output_root(first, RUNNERS[1], runtime="vm") != output_root(second, RUNNERS[1], runtime="vm")
    assert output_root(first, RUNNERS[1], runtime="vm1") != output_root(first, RUNNERS[1], runtime="vm2")
    with pytest.raises(ValueError):
        validate_config({**common, "runner_id": RUNNERS[0], "target_owner_ids": ["unknown"]})
    with pytest.raises(ValueError):
        validate_config({**common, "runner_id": RUNNERS[0], "run_label": "../../outside"})


def test_no_request_outside_utc_window(monkeypatch):
    monkeypatch.setenv("IDS_NETWORK_MODE", "independent_utc")
    monkeypatch.setenv("IDS_RUNNER_ID", RUNNERS[0])
    monkeypatch.setattr("ids_arxiv.network_schedule.time.time", lambda: 700)
    called = Mock()
    monkeypatch.setattr("ids_arxiv.bounded_http.subprocess.run", called)
    with pytest.raises(NetworkWindowClosed):
        scheduled_arxiv(requests.Session(), "https://export.arxiv.org/api/query", Mock())
    called.assert_not_called()


def test_buffered_response_preserves_body_and_releases_temporary_file(monkeypatch):
    monkeypatch.setattr("ids_arxiv.bounded_http.configured_window", lambda: None)
    def fake_child(command, **kwargs):
        value = json.loads(kwargs["input"])
        Path(value["body"]).write_bytes(b'{"ok":true}')
        atomic_json(Path(value["info"]), {"status": 200, "headers": {}, "url": value["url"]})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("ids_arxiv.bounded_http.subprocess.run", fake_child)
    with scheduled_arxiv(requests.Session(), "https://export.arxiv.org/api/query", Mock()) as response:
        path = Path(response.raw.name)
        assert response.json() == {"ok": True} and path.exists()
    assert not path.exists()


def test_metadata_partial_response_never_accepted_as_complete(monkeypatch):
    monkeypatch.setattr("ids_arxiv.bounded_http.configured_window", lambda: None)
    def interrupted(command, **kwargs):
        value = json.loads(kwargs["input"])
        Path(value["body"]).write_bytes(b'{"ok":true}')
        atomic_json(Path(value["info"]), {"status": 200, "headers": {}, "url": value["url"]})
        raise subprocess.TimeoutExpired(command, 1)
    monkeypatch.setattr("ids_arxiv.bounded_http.subprocess.run", interrupted)
    with pytest.raises(requests.Timeout):
        scheduled_arxiv(requests.Session(), "https://export.arxiv.org/api/query", Mock())


@pytest.mark.skipif(os.name == "nt", reason="Production HTTP watchdog is exercised on Colab/POSIX")
def test_http_child_self_terminates_at_deadline_even_if_supervisor_is_not_reading(tmp_path):
    script = "import requests,time,runpy\ndef hang(*a,**k): time.sleep(30)\nrequests.get=hang\nrunpy.run_module('ids_arxiv.bounded_http',run_name='__main__')"
    environment = dict(os.environ)
    environment.update(PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                       TMPDIR=str(tmp_path), IDS_NETWORK_MODE="exclusive")
    request = {"url": "https://export.arxiv.org/api/query", "params": {}, "headers": {},
               "timeout": [5, 5], "budget": 1, "deadline_epoch": time.time() + 1,
               "body": str(tmp_path / "body"), "info": str(tmp_path / "info")}
    started = time.monotonic()
    result = subprocess.run([sys.executable, "-c", script], input=json.dumps(request),
                            text=True, capture_output=True, env=environment, timeout=5)
    assert result.returncode == 124 and time.monotonic() - started < 4
