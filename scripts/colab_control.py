"""Local-only notebook controls. Never infer liveness from a remote PID."""

import argparse
import json
import os
import sys
from pathlib import Path

import psutil

from ids_arxiv.checkpoint import PROTOCOL
from ids_arxiv.runtime import current_worker_record, launch_detached, stop_owned_worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "launch", "stop"])
    parser.add_argument("--student-id", default="23120364")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--max-hours", type=float, default=9)
    parser.add_argument("--coordinated-network", action="store_true")
    parser.add_argument("--confirm-run-id", default="")
    args = parser.parse_args()
    if args.action == "launch" and PROTOCOL >= 4:
        raise SystemExit("Use the independent-team notebook / ids_arxiv.team_run for new launches; legacy status/stop remain read-only controls.")
    student = None if args.student_id in {"None", "group", ""} else args.student_id
    if student not in {None, "23120364", "23120358", "23120345"}:
        raise SystemExit("Unknown student ID")
    if args.action == "launch":
        if not args.coordinated_network or not args.root:
            raise SystemExit("Need --root and confirmed --coordinated-network; do not launch while teammates crawl.")
        for process in psutil.process_iter(["pid", "status", "cmdline"]):
            try:
                command = " ".join(process.info["cmdline"] or [])
                if process.info["status"] not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD} and any(
                    name in command for name in ("colab_autorun.py", "colab_campaign.py", "colab_install_and_run.py")
                ):
                    raise SystemExit(f"Existing local crawler PID {process.pid}; inspect before launching.")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        code = Path(__file__).resolve().parents[1]
        command = [sys.executable, str(code / "scripts/colab_autorun.py"),
                   "--root", str(args.root), "--max-hours", str(args.max_hours), "--coordinated-network"]
        if student:
            command += ["--student-id", student]
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(code / "src")
        process, record = launch_detached(command, code, student, environment)
        print(json.dumps({"launched": process.pid, "run_id": record["run_id"],
                          "local_log": record["local_log"]}))
        return
    record, health = current_worker_record(student)
    if args.action == "stop":
        if not record or args.confirm_run_id != record.get("run_id"):
            raise SystemExit("Copy the exact run_id from status into --confirm-run-id to explicitly stop this worker.")
        print(json.dumps(stop_owned_worker(record)))
        return
    print(json.dumps({"health": health, "record": record}, ensure_ascii=False))
    if record.get("local_log"):
        path = Path(record["local_log"])
        if path.is_file():
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - 12000))
                print(handle.read().decode("utf-8", errors="replace"))
    if not record:
        print("No v3 local launch. Legacy workers/other Colab runtimes are not declared stopped by this monitor.")


if __name__ == "__main__":
    main()
