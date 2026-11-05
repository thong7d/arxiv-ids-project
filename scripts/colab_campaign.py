"""Run discovery, pilot, validation or a full benchmark in mounted Colab Drive."""

import argparse
import json
import os
from pathlib import Path

from ids_arxiv.benchmark import BenchmarkSession, summarize_sessions
from ids_arxiv.crawler.runner import run_crawling_pipeline
from ids_arxiv.discovery import discover_publications, load_members
from ids_arxiv.storage import atomic_json, sha256_file, utc_now
from ids_arxiv.validator import validate_raw_paper

DRIVE_FOLDER_ID = "1NnyZolqKw5dIl_NsIW7BFMztqIXdetGI"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["discover", "pilot", "full", "validate", "summary"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--max-hours", type=float, default=10)
    parser.add_argument("--campaign", default="m1-final-v3")
    parser.add_argument(
        "--student-id",
        default=None,
        help="Filter crawl pipeline to papers owned by this student ID only. "
             "Used in parallel-worker mode where each member runs their own Colab.",
    )
    args = parser.parse_args()
    if not (Path("/content").is_dir() and os.getenv("COLAB_RELEASE_TAG")):
        raise SystemExit(
            "This entrypoint is for Google Colab; local runs are not final benchmarks."
        )
    if not args.root.is_dir():
        raise SystemExit(
            "Drive folder not found. Mount Drive and verify the provided folder first."
        )
    if os.getenv("COLAB_GPU", "0") not in ("0", ""):
        raise SystemExit("Select CPU runtime for the course benchmark.")
    root = args.root / args.campaign
    root.mkdir(exist_ok=True)
    config = Path(__file__).resolve().parents[1] / "configs/members.csv"
    manifest = root / "manifests/papers.parquet"
    if args.stage == "discover":
        if manifest.exists():
            print(
                "Discovery already exists; validate provenance instead of overwriting a running campaign."
            )
            return
        with BenchmarkSession(root / "benchmark", campaign=args.campaign) as measured:
            frame = discover_publications(
                load_members(config), manifest.parent / "discovery", measured.event
            )
            manifest.parent.mkdir(parents=True, exist_ok=True)
            temporary = manifest.with_suffix(".tmp")
            frame.to_parquet(temporary, index=False)
            temporary.replace(manifest)
            atomic_json(
                manifest.with_suffix(".json"),
                {
                    "verified_discovery": True,
                    "manifest_sha256": sha256_file(manifest),
                    "count": len(frame),
                    "by_owner": {
                        str(k): int(v) for k, v in frame.groupby("owner_student_id").size().items()
                    },
                    "created_at": utc_now(),
                    "drive_folder_id": DRIVE_FOLDER_ID,
                },
            )
    elif args.stage in ("pilot", "full"):
        if not manifest.exists():
            raise SystemExit("Run discovery first")
        evidence = json.loads(manifest.with_suffix(".json").read_text())
        if not evidence.get("verified_discovery") or evidence["manifest_sha256"] != sha256_file(
            manifest
        ):
            raise SystemExit("Manifest checksum/provenance mismatch")
        output = root / "raw" if args.stage == "full" else args.root / "m1-pilot-v3/raw"
        if args.stage == "full":
            gate_path = args.root / "m1-pilot-v3" / "pilot_gate.json"
            if not gate_path.exists() or not json.loads(gate_path.read_text())["passed"]:
                raise SystemExit("Full benchmark requires a validated 30-publication pilot")
        result = run_crawling_pipeline(
            manifest,
            output,
            members_config=config,
            pilot_mode=args.stage == "pilot",
            max_seconds=args.max_hours * 3600,
            student_id=args.student_id if args.stage == "full" else None,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.stage == "pilot":
            passed = result["total_attempted"] == 30 and result["success_count"] == 30
            atomic_json(
                output.parent / "pilot_gate.json",
                {
                    "passed": passed,
                    "summary": result,
                    "note": "Audit terminal PDF-only/not-indexed cases before any manual gate override",
                },
            )
    elif args.stage == "validate":
        import pandas as pd

        frame = pd.read_parquet(manifest)
        failures = []
        for paper in frame.dir_id:
            directory = root / "raw" / paper
            if not directory.is_dir():
                failures.append({"paper": paper, "errors": ["Missing publication record"]})
                continue
            result = validate_raw_paper(directory)
            if not result["valid"]:
                failures.append(result)
        result = {"expected": len(frame), "failed_validation": len(failures), "failures": failures}
        atomic_json(root / "validation.json", result)
        print(json.dumps({k: v for k, v in result.items() if k != "failures"}, indent=2))
        if failures:
            raise SystemExit(1)
    else:
        result = summarize_sessions(root / "benchmark")
        atomic_json(root / "benchmark_summary.json", result)
        print(json.dumps({k: v for k, v in result.items() if k != "sessions"}, indent=2))


if __name__ == "__main__":
    main()
