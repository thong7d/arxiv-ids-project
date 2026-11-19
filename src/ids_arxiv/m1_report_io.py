"""Read-only report collection service, isolated from possibly blocked Drive I/O."""

import json
import re
from pathlib import Path

from ids_arxiv.isolation import serve
from ids_arxiv.m1_report import OWNERS
from ids_arxiv.storage import sha256_file


def optional(path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def handle(request):
    owner, root = request["owner"], Path(request["root"])
    if owner not in OWNERS:
        raise ValueError("Unknown owner")
    base = root / "m1-team-v4" / owner / "main/full" / owner
    if request.get("action") == "markers":
        closure = optional(base / "closure.json") or {}
        if not closure.get("operational_closed") or closure.get("audit_in_progress"):
            raise ValueError("Statistics require an operationally closed, frozen corpus")
        assessments = request.get("assessments", [])
        if not 1 <= len(assessments) <= 50:
            raise ValueError("Select 1..50 assessed IDs per read")
        records, errors = {}, []
        for assessment in assessments:
            aid = assessment["arxiv_id"]
            if not isinstance(aid, str) or not re.fullmatch(r"\d{4}\.\d{5}", aid):
                raise ValueError("Invalid assigned ID")
            marker = base / "raw" / aid.replace(".", "-") / "crawl_status.json"
            before = sha256_file(marker) if marker.is_file() else None
            expected = assessment.get("commit_marker_sha256")
            if expected and before != expected:
                records[aid] = None
                errors.append(f"{aid}: commit changed since audit")
                continue
            value = optional(marker)
            if before != (sha256_file(marker) if marker.is_file() else None):
                records[aid] = None
                errors.append(f"{aid}: commit changed while reading statistics")
            else:
                records[aid] = value
        return {"records": records, "errors": errors}
    result = {"audit": optional(base / "audit-result.json"),
              "crawl": optional(base / "raw" / f"crawl_summary-{owner}.json"),
              "legacy_crawl": optional(root / "m1-final-v3/raw" / f"crawl_summary-{owner}.json"),
              "sessions": [], "events": [], "benchmark_collected": bool(request.get("include_benchmarks")),
              "events_collected": bool(request.get("include_events"))}
    if not request.get("include_benchmarks"):
        return result
    sessions = {}
    directories = (base / "benchmark", base / "team-benchmark", root / "m1-final-v3/benchmark")
    for directory in directories:
        for path in sorted(directory.glob("session-*.json")):
            row = optional(path)
            if str(row.get("student_id")) != owner:
                continue
            sid = row.get("session_id")
            if sid in sessions and sessions[sid] != row:
                raise ValueError("Conflicting benchmark mirrors; select one authoritative campaign first")
            sessions[sid] = row
    result["sessions"] = list(sessions.values())
    if request.get("include_events"):
        for directory in directories:
            for path in sorted(directory.glob("requests-*.jsonl")):
                with path.open(encoding="utf-8") as stream:
                    for line in stream:
                        if not line.endswith("\n"):
                            continue  # A running journal's partial last line is not acknowledged evidence.
                        row = json.loads(line)
                        if row.get("kind") == "paper_attempt" and row.get("session_id") in sessions:
                            result["events"].append(row)
    return result


if __name__ == "__main__":
    serve(handle)
