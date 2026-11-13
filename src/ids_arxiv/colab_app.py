"""Thin notebook entrypoint: choose operator, Run all, inspect local telemetry."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .profiling import summarize_attempts
from .runtime import current_worker_record
from .team_run import environment, owner_summaries, validate_config


def default_config(student_id, drive_root, **overrides):
    return validate_config({"runner_id": str(student_id), "target_owner_ids": [str(student_id)],
                            "drive_root": str(drive_root), "network_mode": "independent_utc",
                            "one_runtime_per_runner_confirmed": True, "personal_s2_key_confirmed": True,
                            "compact_output": True, "max_hours": 9, "run_label": "main", "pilot_size": 5,
                            **overrides})


class ColabApp:
    def __init__(self, config):
        self.config = config

    def call(self, action, stage="auto", confirm_run_id=""):
        command = [sys.executable, "-m", "ids_arxiv.team_run", action,
                   "--config-json", json.dumps(self.config), "--stage", stage,
                   "--confirm-run-id", confirm_run_id]
        # CLI subprocesses are short-lived, detached from notebook Interrupt.
        # Long-lived crawler output goes to its local worker.log, never a PIPE.
        with tempfile.TemporaryFile(mode="w+b") as log:
            process = subprocess.Popen(command, env=environment(self.config), stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                exit_code = process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise TimeoutError("Control operation timed out; inspect worker before retrying") from None
            log.seek(0)
            lines = log.read().decode("utf-8", errors="replace").splitlines()
        if exit_code:
            raise RuntimeError("\n".join(lines[-12:]))
        return json.loads(lines[-1])

    def snapshot(self):
        record, health = current_worker_record(self.config["runner_id"])
        summaries = owner_summaries(self.config)
        legacy = record.get("summary", {})
        if legacy.get("student_id") in summaries and not summaries[legacy["student_id"]]["summary"]:
            summaries[legacy["student_id"]]["summary"] = legacy
        metrics = {}
        for owner, value in summaries.items():
            session = value["summary"].get("session_id")
            if session:
                directory = Path(tempfile.gettempdir()) / "ids13-benchmarks" / session
                rows = []
                # Bounded recent sample, not a full Drive walk or a cold benchmark.
                for file in sorted(directory.glob("requests-*.jsonl"))[-4:]:
                    with file.open("rb") as handle:
                        handle.seek(max(0, file.stat().st_size - 2_000_000))
                        if handle.tell():
                            handle.readline()
                        for line in handle:
                            try:
                                rows.append(json.loads(line))
                            except ValueError:
                                pass
                metrics[owner] = summarize_attempts(rows)
        return {"health": health, "record": record, "owners": summaries, "recent_metrics": metrics}

    def monitor(self, seconds=30, interval=10):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        previous = {}
        deadline = time.monotonic() + max(0, seconds)
        while True:
            value = self.snapshot()
            stamp = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%H:%M:%S")
            record = value["record"]
            print(f"[{stamp}] {value['health']['health']} | khâu: {record.get('stage', 'chưa chạy')} | "
                  f"paper: {record.get('current_paper', '—')}", flush=True)
            for owner, item in value["owners"].items():
                summary = item["summary"]
                success = summary.get("success_count", 0)
                print(f"  {owner}: đạt {success}/{summary.get('selected_publications', '—')} | "
                      f"source {summary.get('source_success_count', 0)} | refs {summary.get('reference_success_count', 0)}")
                if summary.get("protocol_version") not in (None, 4):
                    print("  Lưu ý: bộ đếm worker cũ, chưa xác nhận đạt hợp đồng protocol 4.")
                old = previous.get(owner)
                now = time.monotonic()
                if old:
                    print(f"  Tăng ròng: {(success-old[0])*3600/max(now-old[1],.001):.1f} bài/giờ trong cửa sổ quan sát; không phải cold benchmark.")
                previous[owner] = (success, now)
                metrics = value["recent_metrics"].get(owner, {})
                if metrics.get("attempts"):
                    latency = metrics["latency"]
                    print(f"  Độ trễ/lượt: mean {latency['mean_s']:.2f}s | p50 {latency['p50_s']:.2f}s | p95 {latency['p95_s']:.2f}s (n={latency['n']})")
                    print("  Khâu                             n    mean(s)    p95(s)")
                    for name, stat in metrics["stages"].items():
                        print(f"  {name:30} {stat['n']:4} {stat['mean_s']:10.3f} {stat['p95_s']:9.3f}")
            if time.monotonic() >= deadline or value["health"]["health"] in {"STOPPED", "UNKNOWN"}:
                break
            time.sleep(min(interval, max(0, deadline-time.monotonic())))
        print("Worker chạy nền độc lập. Chạy lại cell Monitor để xem tiếp; không cần giữ cell chạy vô hạn.")
        return value

    def stop(self, confirm_run_id):
        return self.call("stop", confirm_run_id=confirm_run_id)


def start(student_id, drive_root, **overrides):
    app = ColabApp(default_config(student_id, drive_root, **overrides))
    record, health = current_worker_record(app.config["runner_id"])
    if health["health"] in {"RUNNING", "WAITING", "STALLED"}:
        print(f"Gắn vào worker hiện có {record.get('run_id')}; không thay cấu hình/khởi chạy trùng.")
        return app
    code = Path(__file__).resolve().parents[2]
    # Test only once per immutable release, away from production quota/cache.
    receipt = code / ".offline-tests-passed"
    if not receipt.exists():
        with tempfile.TemporaryDirectory(prefix="ids13-offline-tests-") as directory:
            env = dict(os.environ)
            for secret in ("ARXIV_CONTACT_EMAIL", "SEMANTIC_SCHOLAR_API_KEY"):
                env.pop(secret, None)
            env.update(TMPDIR=directory, TMP=directory, TEMP=directory, IDS_NETWORK_MODE="legacy")
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                     "--basetemp", str(Path(directory) / "pytest")],
                                    cwd=code, env=env, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError(result.stdout[-5000:] + result.stderr[-1000:])
        receipt.touch()
    print("Tests: đạt. Preflight:", app.call("preflight"))
    print("Khởi chạy probe 5 bài → tự chuyển đủ dải khi probe đạt:", app.call("launch"))
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "monitor", "snapshot", "stop"])
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--drive-root", required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--confirm-run-id", default="")
    args = parser.parse_args()
    if args.action == "start":
        start(args.student_id, args.drive_root)
    else:
        app = ColabApp(default_config(args.student_id, args.drive_root))
        if args.action == "monitor":
            app.monitor(args.seconds)
        elif args.action == "snapshot":
            print(json.dumps(app.snapshot()))
        else:
            print(json.dumps(app.stop(args.confirm_run_id)))
