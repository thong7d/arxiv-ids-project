"""Colab worker: verified discovery -> pilot -> gated full crawl and recovery.

Runs as a notebook-launched child so an MCP tool timeout cannot kill a long
benchmark. Logs/checkpoints remain in Drive. It never suppresses a failed gate.

When --student-id is provided, skip the shared discovery/pilot stages and jump
straight to the full crawl for that member's range only.  This mode is used by
Thành and Quang when running their own Colab sessions in parallel with Thông's.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from ids_arxiv.benchmark import BenchmarkSession
from ids_arxiv.storage import atomic_json, utc_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--max-hours", type=float, default=9)
    parser.add_argument(
        "--student-id",
        default=None,
        help="If set, skip discovery/pilot and run only the full crawl "
             "filtered to this student's assigned range.",
    )
    parser.add_argument(
        "--log-suffix",
        default=None,
        help="Suffix for the automation-status JSON file so concurrent "
             "workers don't overwrite each other's state.",
    )
    args = parser.parse_args()

    suffix = f"-{args.log_suffix}" if args.log_suffix else ""
    status_path = args.root / f"m1-automation-status{suffix}.json"
    start = time.monotonic()
    state = {
        "started_at": utc_now(),
        "stage": "full" if args.student_id else "discovery",
        "state": "running",
        "student_id": args.student_id,
    }

    def stage(name, extra_args=()):
        state.update(stage=name, updated_at=utc_now())
        atomic_json(status_path, state)
        cmd = [
            sys.executable,
            "scripts/colab_campaign.py",
            name,
            "--root", str(args.root),
            "--max-hours",
            str(max(0.1, args.max_hours - (time.monotonic() - start) / 3600)),
        ]
        if args.student_id:
            cmd += ["--student-id", args.student_id]
        cmd += list(extra_args)
        subprocess.run(cmd, check=True)

    try:
        if args.student_id:
            # --- PARALLEL MODE: member runs only their own full range ---
            # Discovery and pilot were already completed by Thông's worker.
            # This worker trusts the shared manifest already on Drive and runs
            # only the full benchmark for the specified student_id range.
            for recovery in range(4):
                if time.monotonic() - start >= args.max_hours * 3600:
                    state.update(state="session_budget_reached", recovery_pass=recovery)
                    break
                state["recovery_pass"] = recovery
                stage("full")
                summary_path = args.root / "m1-final-v3/raw/crawl_summary.json"
                if not summary_path.exists():
                    break
                summary = json.loads(summary_path.read_text())
                if summary["success_count"] == summary["selected_publications"]:
                    stage("validate")
                    state["state"] = "completed"
                    break
            else:
                state["state"] = "completed_with_documented_failures"
            stage("summary")
        else:
            # --- ORIGINAL SINGLE-WORKER MODE (Thông's session) ---
            stage("discover")
            for pilot_pass in range(3):
                state["pilot_pass"] = pilot_pass
                stage("pilot")
                gate = json.loads((args.root / "m1-pilot-v3/pilot_gate.json").read_text())
                if gate["passed"]:
                    break
                if pilot_pass < 2 and time.monotonic() - start < args.max_hours * 3600 - 60:
                    state.update(stage="pilot_recovery_wait", updated_at=utc_now())
                    atomic_json(status_path, state)
                    with BenchmarkSession(args.root / "m1-pilot-v3/benchmark", campaign="m1-pilot-v3"):
                        time.sleep(60)
                else:
                    raise RuntimeError("Pilot gate failed after recovery; inspect component statuses before full crawl")
            for recovery in range(4):
                if time.monotonic() - start >= args.max_hours * 3600:
                    state.update(state="session_budget_reached", recovery_pass=recovery)
                    break
                state["recovery_pass"] = recovery
                stage("full")
                summary = json.loads((args.root / "m1-final-v3/raw/crawl_summary.json").read_text())
                if summary["success_count"] == summary["selected_publications"]:
                    stage("validate")
                    state["state"] = "completed"
                    break
            else:
                state["state"] = "completed_with_documented_failures"
            stage("summary")
    except Exception as error:
        state.update(state="needs_attention", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        state.update(updated_at=utc_now(), elapsed_seconds=time.monotonic() - start)
        atomic_json(status_path, state)


if __name__ == "__main__":
    main()
