"""Notebook-launched worker; install/test before invoking the crawl campaign.

Accepts --student-id to scope the crawl to one member's range, and
--log-suffix to write separate launch-status/log files so multiple
members can run concurrently on different Colab accounts without
overwriting each other's state.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--student-id",
        default=None,
        help="Restrict crawl to papers owned by this student ID (MSSV). "
             "Omit to crawl all members (original single-worker mode).",
    )
    parser.add_argument(
        "--log-suffix",
        default=None,
        help="Suffix appended to launch-status filename, e.g. the student ID. "
             "Allows concurrent workers to write separate status files.",
    )
    args = parser.parse_args()
    code = Path(__file__).resolve().parents[1]

    suffix = f"-{args.log_suffix}" if args.log_suffix else ""
    state_path = args.root / f"m1-launch-status{suffix}.json"

    def state(stage, **extra):
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "stage": stage,
                    "pid": os.getpid(),
                    "student_id": args.student_id,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    **extra,
                }
            ),
            encoding="utf-8",
        )
        temporary.replace(state_path)

    autorun_cmd = [
        sys.executable,
        "scripts/colab_autorun.py",
        "--root", str(args.root),
    ]
    if args.student_id:
        autorun_cmd += ["--student-id", args.student_id]
    if args.log_suffix:
        autorun_cmd += ["--log-suffix", args.log_suffix]

    try:
        state("installing")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-e", str(code), "pytest"], check=True
        )
        state("testing")
        subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=code, check=True)
        state("crawling")
        subprocess.run(autorun_cmd, cwd=code, check=True)
        state("finished")
    except Exception as error:
        state("needs_attention", error=f"{type(error).__name__}: {error}")
        raise


if __name__ == "__main__":
    main()
