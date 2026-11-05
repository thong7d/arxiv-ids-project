"""Durable CPU benchmark sessions; elapsed time includes delays and retries."""

import json
import os
import platform
import subprocess
import threading
import time
import uuid
from pathlib import Path

import psutil

from .storage import atomic_json, utc_now


class BenchmarkSession:
    def __init__(self, directory: Path, interval=1.0, campaign=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session_id = uuid.uuid4().hex
        self.path = self.directory / f"session-{self.session_id}.json"
        self.interval = interval
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.last_sample = self.started
        self.ram_integral = self.sample_seconds = 0.0
        self.peak_ram = self.peak_disk_used = 0
        self.attempts = self.errors = 0
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            commit = "unknown"
        self.record = {
            "session_id": self.session_id,
            "campaign_id": campaign,
            "started_at": utc_now(),
            "state": "running",
            "environment": "colab"
            if os.path.isdir("/content") and os.getenv("COLAB_RELEASE_TAG")
            else "local",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "commit": commit,
            "source_bundle_sha256": os.getenv("IDS_SOURCE_SHA256", "unknown"),
        }

    def event(self, value):
        with self.lock:
            with (self.directory / f"requests-{self.session_id}.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps({"session_id": self.session_id, **value}) + "\n")
            self.attempts += int(value.get("kind", "http") == "http")
            self.errors += int(bool(value.get("error")) or value.get("http_status", 200) >= 400)

    def sample(self):
        now = time.monotonic()
        process = psutil.Process()
        processes = [process] + process.children(recursive=True)
        rss = 0
        for child in processes:
            try:
                rss += child.memory_info().rss
            except psutil.Error:
                pass
        dt = now - self.last_sample
        self.ram_integral += rss * dt
        self.sample_seconds += dt
        self.last_sample = now
        self.peak_ram = max(self.peak_ram, rss)
        self.peak_disk_used = max(
            self.peak_disk_used, psutil.disk_usage(self.directory.resolve().anchor).used
        )
        self.record.update(
            elapsed_seconds=now - self.started,
            heartbeat_at=utc_now(),
            peak_process_tree_rss_bytes=self.peak_ram,
            ram_byte_seconds=self.ram_integral,
            sample_seconds=self.sample_seconds,
            average_process_tree_rss_bytes=self.ram_integral / max(self.sample_seconds, 1e-9),
            peak_volume_used_bytes=self.peak_disk_used,
            http_attempts=self.attempts,
            http_errors=self.errors,
        )
        atomic_json(self.path, self.record)

    def __enter__(self):
        self.sample()

        def monitor():
            while not self.stop.wait(self.interval):
                self.sample()

        self.thread = threading.Thread(target=monitor, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stop.set()
        self.thread.join()
        self.record.update(
            state="completed" if exc_type is None else "interrupted", ended_at=utc_now()
        )
        self.sample()


def summarize_sessions(directory: Path):
    sessions = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(Path(directory).glob("session-*.json"))
    ]
    if not sessions:
        raise ValueError("No measured sessions exist")
    duration = sum(s["elapsed_seconds"] for s in sessions)
    weight = sum(s["sample_seconds"] for s in sessions)
    return {
        "session_count": len(sessions),
        "measured_runtime_seconds": duration,
        "average_process_tree_rss_bytes": sum(s["ram_byte_seconds"] for s in sessions)
        / max(weight, 1e-9),
        "peak_process_tree_rss_bytes": max(s["peak_process_tree_rss_bytes"] for s in sessions),
        "peak_volume_used_bytes": max(s["peak_volume_used_bytes"] for s in sessions),
        "http_attempts": sum(s["http_attempts"] for s in sessions),
        "http_errors": sum(s["http_errors"] for s in sessions),
        "sessions": sessions,
    }
