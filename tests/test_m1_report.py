from copy import deepcopy

import pytest

from ids_arxiv.m1_report import (
    audit_statistics,
    benchmark_statistics,
    load_snapshot,
    make_snapshot,
    marker_statistics,
)
from ids_arxiv.storage import atomic_json


def audited():
    return {"student_id": "23120364", "protocol_version": 4,
            "discovery_manifest_sha256": "real-manifest", "counts": {"full_success": 1, "references_unavailable": 1},
            "records": [{"arxiv_id": "2508.17872", "classification": "full_success", "data_download_success": True,
                         "withdrawn_versions": [], "reasons": []},
                        {"arxiv_id": "2508.17873", "classification": "references_unavailable", "data_download_success": False,
                         "withdrawn_versions": [], "reasons": []}]}


def test_missing_audit_is_not_zero_success_rate_or_legacy_success():
    value = make_snapshot({"23120364": ["2508.17872", "2508.17873"]}, "real-manifest",
                          {"23120364": {"legacy_crawl": {"success_count": 2}}})
    row = value["owners"]["23120364"]
    assert row["success_rate"] is None and row["unassessed_count"] == 2
    assert row["counts"] == {} and row["crawl_snapshot"]["is_legacy"]
    assert not value["final_report"]
    assert row["benchmark"]["completed_sessions"] is None and row["benchmark"]["coverage_count"] is None


def test_s2_exception_does_not_increase_download_rate():
    row = audit_statistics("23120364", ["2508.17872", "2508.17873"], "real-manifest", audited())
    assert row["success_rate"] == .5 and row["academic_exception_approval_pending"]
    assert row["operational_closed"]


@pytest.mark.parametrize("kind", ["owner", "ids", "counter", "fake_success", "protocol"])
def test_report_rejects_unproven_audit(kind):
    audit = deepcopy(audited())
    if kind == "owner":
        audit["student_id"] = "23120345"
    elif kind == "ids":
        audit["records"][1]["arxiv_id"] = "2508.17872"
    elif kind == "counter":
        audit["counts"]["full_success"] = 2
    elif kind == "protocol":
        audit["protocol_version"] = 3
    else:
        audit["records"][1]["data_download_success"] = True
    with pytest.raises(ValueError):
        audit_statistics("23120364", ["2508.17872", "2508.17873"], "real-manifest", audit)


def test_parallel_worker_sum_is_not_wall_time_or_complete_benchmark():
    def session(sid, start, end):
        return {"session_id": sid, "state": "completed", "started_at": f"2026-11-17T00:00:{start:02}+00:00",
                "ended_at": f"2026-11-17T00:00:{end:02}+00:00", "elapsed_seconds": 10,
                "sample_seconds": 10, "ram_byte_seconds": 1000, "peak_process_tree_rss_bytes": 150,
                "environment": "colab"}
    sessions = [session("a", 0, 10), session("b", 5, 15)]
    event = {"kind": "paper_attempt", "session_id": "a", "arxiv_id": "2508.17872", "elapsed_seconds": 2}
    row = benchmark_statistics(sessions, [event, event], ["2508.17872", "2508.17873"])
    assert row["measured_worker_seconds"] == 20 and row["completed_session_wall_union_seconds"] == 15
    assert row["average_process_tree_rss_bytes"] == 100 and row["paper_attempts"] == 1
    assert row["coverage_count"] == 1 and not row["coverage_complete"]
    assert row["end_to_end_seconds"] is None and not row["final_benchmark_verified"]


def test_snapshot_readback_rejects_bad_denominator(tmp_path):
    value = make_snapshot({"23120364": ["2508.17872", "2508.17873"]}, "real-manifest",
                          {"23120364": {"audit": audited()}})
    path = tmp_path / "snapshot.json"
    atomic_json(path, value)
    assert load_snapshot(path)["owners"]["23120364"]["counts"]["full_success"] == 1
    value["expected_count"] = 5000
    atomic_json(path, value)
    with pytest.raises(ValueError, match="denominator"):
        load_snapshot(path)


def test_snapshot_rejects_negative_counts_and_fabricated_unknown_rate(tmp_path):
    value = make_snapshot({"23120364": ["2508.17872"]}, "real-manifest", {})
    value["owners"]["23120364"]["success_rate"] = 0
    path = tmp_path / "snapshot.json"
    atomic_json(path, value)
    with pytest.raises(ValueError, match="success rate"):
        load_snapshot(path)


def test_report_io_only_reads_selected_owner_and_never_rewrites_raw(tmp_path):
    from ids_arxiv.m1_report_io import handle
    base = tmp_path / "m1-team-v4/23120364/main/full/23120364"
    audit = base / "audit-result.json"
    atomic_json(audit, audited())
    raw = base / "raw/crawl_summary-23120364.json"
    atomic_json(raw, {"success_count": 1})
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    row = handle({"root": str(tmp_path), "owner": "23120364"})
    assert row["audit"] == audited() and row["crawl"]["success_count"] == 1
    assert not row["benchmark_collected"] and not row["events_collected"]
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    with pytest.raises(ValueError, match="Unknown owner"):
        handle({"root": str(tmp_path), "owner": "../other-owner"})


def test_marker_statistics_match_size_cohorts_and_preserve_real_empty_references():
    records = {}
    for aid, state, before, after, refs in [("2508.17872", "downloaded", 1000, 100, 10),
                                           ("2508.17873", "pdf_only", 0, 0, 0)]:
        records[aid] = {"arxiv_id": aid, "schema_version": 4, "commit_state": "committed",
                        "source_success": True, "expected_versions": [1],
                        "versions": [{"version": 1, "success": True, "state": state,
                                      "initial_bytes": before, "stripped_bytes": after}],
                        "references_status": {"success": True, "dates_complete": True,
                                              "all_references_retained": True, "raw_count": refs},
                        "num_references_arxiv": refs}
    value = marker_statistics(list(records), records)
    assert value["paired_size_papers"] == 1 and value["mean_before_uncompressed_bytes"] == 1000
    assert value["mean_after_tex_bib_bytes"] == 100 and value["mean_all_references"] == 5
    assert value["all_reference_count_papers"] == 2 and value["reference_metadata_success_rate"] == 1
    records["2508.17873"] = None
    value = marker_statistics(list(records), records)
    assert value["reference_metadata_success_rate"] is None and value["missing_or_incompatible_markers"] == 1
