"""Collect sanitized audit/benchmark inputs without network crawling or raw edits."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ids_arxiv.isolation import IsolatedService
from ids_arxiv.m1_report import OWNERS, audit_statistics, load_snapshot, make_snapshot
from ids_arxiv.storage import atomic_json, sha256_file


def collect(root, include_benchmarks=False, include_events=False, include_marker_statistics=False):
    import pandas as pd
    root = Path(root)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("Select the mounted shared Drive root")
    manifest = root / "m1-final-v3/manifests/papers.parquet"
    environment = dict(os.environ)
    source = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
    with IsolatedService("ids_arxiv.io_worker", timeout=45, environment=environment) as io:
        provenance = io.call({"action": "read_json", "path": str(manifest.with_suffix(".json")), "default": {}})
        with tempfile.TemporaryDirectory(prefix="ids13-report-manifest-") as scratch:
            copied = Path(scratch) / "papers.parquet"
            io.call({"action": "copy", "source": str(manifest), "target": str(copied)})
            if not provenance.get("verified_discovery") or sha256_file(copied) != provenance.get("manifest_sha256"):
                raise ValueError("Report requires the verified discovery manifest")
            frame = pd.read_parquet(copied)
    ids = {owner: frame.loc[frame.owner_student_id.astype(str) == owner, "arxiv_id"].tolist() for owner in OWNERS}
    if any(len(values) != 5000 for values in ids.values()) or sum(map(len, ids.values())) != len(frame):
        raise ValueError("Need exactly three assigned 5000-ID owner ranges")
    bundles = {}
    # One short read-only service at a time; no crawler/audit is started or stopped.
    for owner in OWNERS:
        try:
            with IsolatedService("ids_arxiv.m1_report_io", timeout=60, environment=environment) as io:
                bundles[owner] = io.call({"root": str(root), "owner": owner})
                if include_benchmarks:
                    try:
                        measured = io.call({"root": str(root), "owner": owner,
                                            "include_benchmarks": True, "include_events": include_events})
                        bundles[owner].update(measured)
                    except (TimeoutError, RuntimeError, OSError) as error:
                        bundles[owner].setdefault("collection_errors", []).append(str(error))
                audit = bundles[owner].get("audit") or {}
                if include_marker_statistics and audit.get("operational_closed"):
                    audit_statistics(owner, ids[owner], provenance["manifest_sha256"], audit)
                    records = {}
                    for offset in range(0, len(audit["records"]), 50):
                        batch = audit["records"][offset:offset + 50]
                        try:
                            part = io.call({"action": "markers", "root": str(root), "owner": owner, "assessments": batch})
                            records.update(part["records"])
                            bundles[owner].setdefault("collection_errors", []).extend(part["errors"])
                        except (TimeoutError, RuntimeError, OSError) as error:
                            records.update({row["arxiv_id"]: None for row in batch})
                            bundles[owner].setdefault("collection_errors", []).append(str(error))
                    bundles[owner]["markers"] = records
        except (TimeoutError, RuntimeError, OSError) as error:
            bundles[owner] = {"collection_errors": [str(error)]}
    return make_snapshot(ids, provenance["manifest_sha256"], bundles)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--drive-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--include-benchmarks", action="store_true")
    parser.add_argument("--include-events", action="store_true")
    parser.add_argument("--include-marker-statistics", action="store_true", help="Read sizes/references from frozen, audited markers; no new raw integrity audit")
    args = parser.parse_args()
    if args.include_events and not args.include_benchmarks:
        parser.error("--include-events requires --include-benchmarks")
    snapshot = collect(args.drive_root, args.include_benchmarks, args.include_events, args.include_marker_statistics)
    atomic_json(Path(args.output), snapshot)
    load_snapshot(args.output)
    print(f"Snapshot saved: {args.output}; final_report=False (not an academic completion claim)")
