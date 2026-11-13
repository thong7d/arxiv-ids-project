"""Final accounting is independent of worker state and never rewrites data."""

import json

import pytest

from ids_arxiv.checkpoint import PROTOCOL, SOURCE_POLICY
from ids_arxiv.completion import account_owner, assess_publication
from ids_arxiv.storage import atomic_json, file_inventory, sha256_file, utc_now

AID = "2508.17872"


def publication(root, withdrawn=False):
    root.mkdir()
    (root / "v1").mkdir()
    (root / "v1/main.tex").write_text("source", encoding="utf-8")
    dates = {"1": "2025-08-20T00:00:00Z"}
    sources = {"1": "arxiv_atom_published"}
    versions = [{"version": 1, "success": True, "state": "downloaded", "source_policy": SOURCE_POLICY,
                 "files": file_inventory(root / "v1")}]
    if withdrawn:
        dates["2"] = "2026-01-01T00:00:00Z"
        sources["2"] = "arxiv_atom_updated"
        versions.append({"version": 2, "success": False, "error": "HTTP 404"})
    atomic_json(root / "metadata.json", {
        "title": "Test", "submission_date": dates["1"], "metadata_quality_version": 3,
        "metadata_dates_complete": True, "version_dates": dates, "version_date_sources": sources,
        "version_metadata_complete": True, "version_metadata": {v: {"title": "Test"} for v in dates},
    })
    atomic_json(root / "references.json", {})
    atomic_json(root / "references_all.json", [])
    record = {"schema_version": PROTOCOL, "arxiv_id": AID, "commit_state": "committed", "commit_id": "test",
              "success": not withdrawn, "source_success": not withdrawn, "metadata_dates_complete": True,
              "expected_versions": list(range(1, len(versions) + 1)), "versions": versions,
              "references_status": {"success": True, "dates_complete": True, "raw_count": 0, "arxiv_count": 0,
                                    "all_references_retained": True},
              "checksums": {name: sha256_file(root / name) for name in ("metadata.json", "references.json", "references_all.json")}}
    atomic_json(root / "crawl_status.json", record)
    proof = {"arxiv_id": AID, "version": 2, "verified": True, "data_download_success": False,
             "http_status": 200, "url": f"https://arxiv.org/abs/{AID}v2", "checked_at": utc_now(),
             "withdrawn_banner": True, "no_pdf_available": True, "version_identity_confirmed": True,
             "response_sha256": "a" * 64}
    return record, proof


def test_full_success_requires_persisted_bytes(tmp_path):
    root = tmp_path / "paper"
    publication(root)
    assert assess_publication(root, AID)["classification"] == "full_success"
    (root / "v1/main.tex").write_text("corrupt", encoding="utf-8")
    assert assess_publication(root, AID)["classification"] == "pending"


def test_withdrawal_is_not_a_downloaded_success_and_never_mutates(tmp_path):
    root = tmp_path / "paper"
    _, proof = publication(root, withdrawn=True)
    before = (root / "crawl_status.json").read_bytes()
    outcome = assess_publication(root, AID, {AID + "v2": proof})
    assert outcome["classification"] == "verified_exception"
    assert outcome["withdrawn_versions"] == [2]
    assert outcome["data_download_success"] is False
    assert (root / "crawl_status.json").read_bytes() == before


@pytest.mark.parametrize("change", [
    {"http_status": 429}, {"arxiv_id": "2509.01047"}, {"version": 3},
    {"url": "https://example.com/abs/2508.17872v2"}, {"response_sha256": ""},
    {"data_download_success": True}, {"no_pdf_available": False}, {"checked_at": "2026-01-01"},
])
def test_weak_or_mismatched_evidence_does_not_close(tmp_path, change):
    root = tmp_path / "paper"
    _, proof = publication(root, withdrawn=True)
    assert assess_publication(root, AID, {AID + "v2": {**proof, **change}})["classification"] == "pending"


def test_withdrawal_does_not_waive_reference_error_or_available_source_checks(tmp_path):
    root = tmp_path / "paper"
    record, proof = publication(root, withdrawn=True)
    record["references_status"] = {"success": False, "http_status": 429}
    atomic_json(root / "crawl_status.json", record)
    assert assess_publication(root, AID, {AID + "v2": proof})["classification"] == "pending"
    record["references_status"] = {"success": True, "dates_complete": True}
    atomic_json(root / "crawl_status.json", record)
    (root / "v1/main.tex").write_text("corrupt", encoding="utf-8")
    assert assess_publication(root, AID, {AID + "v2": proof})["classification"] == "pending"


def test_false_success_and_temporary_source_failure_cannot_be_exceptions(tmp_path):
    root = tmp_path / "paper"
    record, proof = publication(root, withdrawn=True)
    record["success"] = True
    atomic_json(root / "crawl_status.json", record)
    assert assess_publication(root, AID, {AID + "v2": proof})["classification"] == "pending"
    record["success"] = False
    record["versions"][1]["error"] = "HTTP 429"
    atomic_json(root / "crawl_status.json", record)
    assert assess_publication(root, AID, {AID + "v2": proof})["classification"] == "pending"


def test_owner_manifest_must_be_exact_and_all_outcomes_consistent():
    full = {"arxiv_id": AID, "classification": "full_success", "data_download_success": True,
            "reasons": [], "withdrawn_versions": []}
    other = "2508.17873"
    exception = {"arxiv_id": other, "classification": "verified_exception", "data_download_success": False,
                 "reasons": [], "withdrawn_versions": [2]}
    report = account_owner("23120364", [AID, other], [full, exception])
    assert report["collection_closed"]
    assert report["state"] == "complete_with_verified_exceptions"
    for rows in ([full], [full, full], [full, {**exception, "arxiv_id": "2509.01047"}],
                 [full, {**exception, "classification": "pending"}],
                 [full, {**exception, "data_download_success": True}]):
        assert not account_owner("23120364", [AID, other], rows)["collection_closed"]
    with pytest.raises(ValueError):
        account_owner("23120364", [AID, AID], [full])
    with pytest.raises(ValueError):
        account_owner("23120364", [], [])
    json.dumps(report)  # portable report, no non-JSON timestamp objects
