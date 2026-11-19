"""Local process identity and detached notebook workers; never infer life from PID alone."""

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import psutil

from .storage import atomic_json, utc_now

TERMINAL = {"finished", "completed", "interrupted", "failed", "stopped", "needs_attention",
            "needs_recovery", "session_budget_reached", "stopped_for_review",
            "stopped_with_documented_exceptions"}


def runtime_id():
    try:
        identity = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        identity = f"{psutil.boot_time()}:{os.environ.get('COMPUTERNAME', '')}"
    return hashlib.sha256(identity.encode()).hexdigest()[:20]


def process_identity(pid):
    process = psutil.Process(int(pid))
    value = {"pid": process.pid, "create_time": process.create_time(),
             "runtime_id": runtime_id(), "process_status": process.status()}
    if hasattr(os, "getpgid"):
        value.update(pgid=os.getpgid(process.pid), sid=os.getsid(process.pid))
    return value


def worker_health(record, now=None, stale_seconds=90):
    """A remote PID is UNKNOWN, a zombie is STOPPED, and stale work is not green."""
    now = time.time() if now is None else now
    if record.get("runtime_id") != runtime_id():
        return {"health": "UNKNOWN", "reason": "different_or_legacy_runtime"}
    try:
        identity = process_identity(record["pid"])
    except (psutil.Error, OSError, KeyError, ValueError):
        return {"health": "STOPPED", "reason": "process_missing"}
    if abs(identity["create_time"] - record.get("create_time", -1)) > 0.01:
        return {"health": "STOPPED", "reason": "pid_reused"}
    if identity["process_status"] in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
        return {"health": "STOPPED", "reason": identity["process_status"]}
    if record.get("state") in TERMINAL:
        return {"health": "STOPPED", "reason": record["state"]}
    heartbeat_age = now - record.get("heartbeat_epoch", 0)
    if heartbeat_age > stale_seconds:
        return {"health": "STALLED", "reason": "stale_heartbeat", "age_seconds": heartbeat_age}
    if record.get("stage") == "retry_wait" and record.get("next_retry_epoch", 0) > now:
        return {"health": "WAITING", "reason": "scheduled_retry",
                "wait_seconds": record["next_retry_epoch"] - now}
    if record.get("stage_deadline_epoch", float("inf")) < now:
        return {"health": "STALLED", "reason": "stage_deadline_exceeded"}
    return {"health": "RUNNING", "reason": "identity_and_heartbeat_verified"}


@contextlib.contextmanager
def local_lock(path, timeout=10):
    """An OS lock on LOCAL disk; explicitly not a distributed Drive lock."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        started = time.monotonic()
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - started >= timeout:
                    raise TimeoutError(f"Local lock timeout: {path.name}") from None
                time.sleep(0.02)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


def launch_detached(command, code_root, student_id, environment=None):
    scope = student_id or "group"
    state_dir = Path(tempfile.gettempdir()) / "ids13-control" / runtime_id() / scope
    state_dir.mkdir(parents=True, exist_ok=True)
    status_path = state_dir / "launch.json"
    with local_lock(state_dir / "launch.lock"):
        if status_path.exists():
            previous = json.loads(status_path.read_text(encoding="utf-8"))
            health = worker_health(previous)
            try:
                identity = process_identity(previous["pid"])
                same_live = (previous.get("runtime_id") == runtime_id()
                             and abs(identity["create_time"] - previous.get("create_time", -1)) < 0.01
                             and identity["process_status"] not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD})
            except (psutil.Error, OSError, KeyError, ValueError):
                same_live = False
            # A stale but still alive process must be inspected, not duplicated.
            if same_live or health["health"] in {"RUNNING", "WAITING", "STALLED"}:
                raise RuntimeError(f"Existing worker: {health}; do not launch a duplicate")
        run_id = uuid.uuid4().hex
        run_dir = state_dir / run_id
        run_dir.mkdir()
        environment = dict(os.environ if environment is None else environment)
        environment.update(IDS_RUN_ID=run_id, IDS_LOCAL_STATE_DIR=str(run_dir),
                           IDS_CONTROL_STATUS=str(status_path), IDS_RUNTIME_ID=runtime_id())
        with (run_dir / "worker.log").open("a", encoding="utf-8", buffering=1) as log:
            process = subprocess.Popen(command, cwd=code_root, env=environment,
                                       stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        record = {**process_identity(process.pid), "run_id": run_id,
                  "student_id": student_id, "state": "starting", "stage": "starting",
                  "heartbeat_epoch": time.time(), "started_at": utc_now(),
                  "local_state_dir": str(run_dir), "local_log": str(run_dir / "worker.log")}
        atomic_json(status_path, record)
    return process, record


def current_worker_record(student_id=None):
    path = Path(tempfile.gettempdir()) / "ids13-control" / runtime_id() / (student_id or "group") / "launch.json"
    try:
        launch = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {"health": "UNKNOWN", "reason": "no_local_launch_record"}
    progress_path = Path(launch["local_state_dir"]) / "progress.json"
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        progress = {}
    return {**launch, **progress}, worker_health({**launch, **progress})


def stop_owned_worker(record, grace_seconds=10):
    """Explicit stop only: validate runtime + birth time before touching any PID."""
    health = worker_health(record)
    if health["health"] in {"STOPPED", "UNKNOWN"}:
        return health
    parent = psutil.Process(record["pid"])
    if parent.pid == os.getpid():
        raise RuntimeError("Refusing to stop the current notebook/kernel process")
    children = parent.children(recursive=True)
    try:
        parent.send_signal(signal.SIGTERM)
    except psutil.NoSuchProcess:
        pass
    # Allow the coordinator to checkpoint and close its services first.
    psutil.wait_procs([parent], timeout=grace_seconds)
    try:
        children += parent.children(recursive=True)
    except psutil.NoSuchProcess:
        pass
    identities = {}
    for process in children:
        try:
            if process.is_running():
                identities[(process.pid, process.create_time())] = process
        except psutil.NoSuchProcess:
            pass
    children = list(identities.values())
    for process in reversed(children):
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, remaining = psutil.wait_procs(children + [parent], timeout=2)
    for process in remaining:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    return {"health": "STOPPED", "reason": "explicit_stop_requested"}
