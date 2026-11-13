"""Durable CPU benchmark sessions; elapsed time includes delays and retries."""

import json
import os
import platform
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import psutil

from .storage import atomic_json, utc_now


class BenchmarkSession:
    def __init__(self, directory: Path, interval=1.0, campaign=None):
        self.session_id = uuid.uuid4().hex
        self.remote_directory = Path(directory)
        self.remote = str(directory).replace("\\", "/").startswith("/content/drive/")
        self.directory = (Path(tempfile.gettempdir()) / "ids13-benchmarks" / self.session_id
                          if self.remote else self.remote_directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / f"session-{self.session_id}.json"
        self.interval = interval
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.last_sample = self.started
        self.ram_integral = self.sample_seconds = 0.0
        self.peak_ram = self.peak_disk_used = 0
        self.attempts = self.errors = 0
        self.event_sequence = 0
        self.events_path = self.directory / f"requests-{self.session_id}.jsonl"
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
            "measurement_protocol": 3,
            "journal_location": "local",
        }

    def event(self, value):
        with self.lock:
            with self.events_path.open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps({"session_id": self.session_id, **value}) + "\n")
            self.attempts += int(value.get("kind", "http") == "http")
            self.errors += int(value.get("kind") != "network_window_wait" and (
                bool(value.get("error")) or value.get("http_status", 200) >= 400))

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

    def mirror(self, io):
        """Buffered, bounded remote I/O; immutable request chunks avoid FUSE appends.

        Failure never discards the local journal. The caller may retry safely.
        """
        if not self.remote:
            return True
        try:
            with self.lock:
                if self.events_path.exists() and self.events_path.stat().st_size:
                    chunk = self.directory / f"requests-{self.session_id}-{self.event_sequence:06d}.jsonl"
                    self.events_path.replace(chunk)
                    self.event_sequence += 1
                chunks = list(self.directory.glob(f"requests-{self.session_id}-*.jsonl"))
            # Remember acknowledged chunks locally; do not reread remote hashes
            # for the entire history at every mirror.
            sent = getattr(self, "sent_chunks", set())
            for chunk in chunks:
                if chunk.name not in sent:
                    io.call({"action": "copy", "source": str(chunk),
                             "target": str(self.remote_directory / chunk.name)})
                    sent.add(chunk.name)
            self.sent_chunks = sent
            io.call({"action": "write_json", "path": str(self.remote_directory / self.path.name),
                     "value": dict(self.record)})
            self.record.pop("mirror_error", None)
            return True
        except (OSError, RuntimeError, TimeoutError) as error:
            self.record["mirror_error"] = f"{type(error).__name__}: {error}"
            atomic_json(self.path, self.record)
            return False

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
        if self.remote:
            from .isolation import IsolatedService
            with IsolatedService("ids_arxiv.io_worker", timeout=30) as io:
                self.mirror(io)


def summarize_sessions(directory: Path):
    sessions = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(Path(directory).glob("session-*.json"))
    ]
    if not sessions:
        raise ValueError("No measured sessions exist")
    duration = sum(s["elapsed_seconds"] for s in sessions)
    weight = sum(s["sample_seconds"] for s in sessions)
    intervals = []
    for session in sessions:
        try:
            start = datetime.fromisoformat(session["started_at"]).timestamp()
            end = datetime.fromisoformat(session["ended_at"]).timestamp()
            intervals.append((start, end))
        except (KeyError, ValueError):
            pass
    wall = 0.0
    boundary = float("-inf")
    for start, end in sorted(intervals):
        wall += max(0, end - max(start, boundary))
        boundary = max(boundary, end)
    return {
        "session_count": len(sessions),
        "measured_runtime_seconds": duration,
        "measured_worker_seconds": duration,
        "completed_session_wall_clock_union_seconds": wall,
        "runtime_note": "measured_runtime_seconds sums worker time, not parallel wall time; union excludes gaps and unfinished sessions",
        "protocol_counts": {str(p): sum(s.get("measurement_protocol", "legacy") == p for s in sessions)
                            for p in {s.get("measurement_protocol", "legacy") for s in sessions}},
        "average_process_tree_rss_bytes": sum(s["ram_byte_seconds"] for s in sessions)
        / max(weight, 1e-9),
        "peak_process_tree_rss_bytes": max(s["peak_process_tree_rss_bytes"] for s in sessions),
        "peak_volume_used_bytes": max(s["peak_volume_used_bytes"] for s in sessions),
        "http_attempts": sum(s["http_attempts"] for s in sessions),
        "http_errors": sum(s["http_errors"] for s in sessions),
        "sessions": sessions,
    }
