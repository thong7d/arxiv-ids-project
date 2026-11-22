"""One selected owner per runtime: bounded crawl, evidence, resumable audit."""

import argparse
import json
import os
import signal
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil

from .checkpoint import read_json
from .colab_app import default_config
from .crawler.arxiv_client import ArxivCrawler
from .crawler.runner import run_crawling_pipeline
from .crawler.withdrawals import verify_withdrawal
from .finalize import finalize
from .isolation import IsolatedService
from .network_schedule import RUNNERS, configured_window
from .runtime import (
    current_worker_record,
    launch_detached,
    local_lock,
    runtime_id,
    stop_owned_worker,
)
from .storage import atomic_json, utc_now
from .team_run import environment, output_root, validate_config


def workflow_config(owner, root, **overrides):
    config = default_config(owner, root, **overrides)
    return validate_workflow(config)


def validate_workflow(config):
    config = validate_config(config)
    if len(config["target_owner_ids"]) != 1:
        raise ValueError("Select exactly one owner for a workflow session")
    owner = config["target_owner_ids"][0]
    config.setdefault("max_network_passes", 3)
    config.setdefault("paper_seconds", 180)
    config.setdefault("max_future_retry_wait_seconds", 1800)
    config.setdefault("data_runner_id", owner)
    if config["data_runner_id"] not in RUNNERS:
        raise ValueError("Invalid corpus namespace")
    if not 1 <= int(config["max_network_passes"]) <= 10 or not 30 <= float(config["paper_seconds"]) <= 900:
        raise ValueError("Invalid finite work budget")
    if not 1800 <= float(config["max_future_retry_wait_seconds"]) <= 86400:
        raise ValueError("Future retry wait must preserve the UTC window (1800..86400 seconds)")
    config["max_future_retry_wait_seconds"] = float(config["max_future_retry_wait_seconds"])
    return config


def corpus_base(config):
    owner = config["target_owner_ids"][0]
    return output_root({**config, "runner_id": config.get("data_runner_id", owner)}, owner)


def audit_ready_after_budget(summary):
    """Require complete attempt coverage and no unsaved payload before audit."""
    counters = ("selected_publications", "total_attempted", "pending_count",
                "upload_pending_count", "uncommitted_attempt_count")
    return (all(type(summary.get(key)) is int for key in counters)
            and summary["selected_publications"] == 5000
            and summary["total_attempted"] == 5000
            and summary["pending_count"] > 0
            and summary["upload_pending_count"] == 0
            and summary["uncommitted_attempt_count"] == 0)


def future_retry_cutoff(summary, now, limit=1800):
    """Stop waiting, not retry early or declare failures permanently absent.

    Unknown counters fail closed. Every assigned ID must have a recorded attempt,
    and no uncommitted local payload may be left behind for an audit to skip.
    """
    counters = ("selected_publications", "total_attempted", "pending_count",
                "upload_pending_count", "uncommitted_attempt_count")
    if any(type(summary.get(key)) is not int for key in counters):
        return False
    selected = summary["selected_publications"]
    due = summary.get("next_retry_epoch")
    return bool(selected == 5000 and summary.get("total_attempted") == selected
                and summary.get("pending_count", 0) > 0
                and summary.get("upload_pending_count") == 0
                and summary.get("uncommitted_attempt_count") == 0
                and isinstance(due, (int, float)) and due - now > limit)


def collect_source_evidence(config, io, summary, max_checks=50, max_seconds=2100):
    """One bounded official check per missing version; never fake a proof."""
    owner = config["target_owner_ids"][0]
    base = corpus_base(config)
    saved = io.call({"action": "read_json", "path": str(base / "closure-evidence.json"), "default": {}})
    proofs = dict(saved.get("records", {})) if str(saved.get("student_id")) == owner else {}
    legacy = io.call({"action": "read_json", "path": str(Path(config["drive_root"]) /
                     f"m1-final-v3/completion-{owner}/withdrawal-evidence.json"), "default": {}})
    proofs.update({k: v for k, v in legacy.get("records", {}).items() if k not in proofs})
    checks = 0
    deadline = time.monotonic() + max_seconds
    crawler = ArxivCrawler()
    try:
        for aid in summary.get("failed_ids", []):
            row = io.call({"action": "read_json", "path": str(base / "raw" / aid.replace(".", "-") / "crawl_status.json"), "default": {}})
            for version in row.get("versions", []):
                key = f"{aid}v{version['version']}"
                if version.get("error") != "HTTP 404" or key in proofs or checks >= max_checks:
                    continue
                window = configured_window()
                while window and not window.status()["allowed"] and time.monotonic() < deadline:
                    # Do not silently skip all verification merely because crawl
                    # ended during another owner's UTC turn. This is finite,
                    # visible in the worker log and covered by its heartbeat.
                    wait = min(window.status()["next_epoch"] - time.time(), deadline-time.monotonic())
                    print(json.dumps({"stage": "source_evidence_wait", "owner": owner,
                                      "seconds": max(0, wait), "checked": checks}), flush=True)
                    time.sleep(min(30, max(.05, wait)))
                if time.monotonic() >= deadline:
                    continue
                proof = verify_withdrawal(crawler.session, aid, version["version"])
                proof.update(source_failure_recorded="HTTP 404", source_url=f"https://export.arxiv.org/src/{key}")
                proofs[key] = proof
                checks += 1
        io.call({"action": "write_json", "path": str(base / "closure-evidence.json"),
                 "value": {"student_id": owner, "records": proofs}})
    finally:
        crawler.session.close()
    return checks


def execute(config):
    config = validate_workflow(config)
    owner = config["target_owner_ids"][0]
    if not Path("/content").is_dir() or not os.environ.get("COLAB_RELEASE_TAG") or os.environ.get("COLAB_GPU", "0") not in {"", "0"}:
        raise ValueError("Run M1 workflow on Google Colab CPU")
    os.environ.update(environment(config))
    run_dir = Path(os.environ["IDS_LOCAL_STATE_DIR"])
    run_dir.mkdir(parents=True, exist_ok=True)
    crawl_control = run_dir / "crawl"
    state = {"state": "running", "stage": "prepare", "runtime_id": runtime_id(), "owner": owner}
    lock, stop = threading.Lock(), threading.Event()
    def pulse():
        while not stop.is_set():
            with lock:
                current = dict(state)
            current["heartbeat_epoch"] = time.time()
            if current["stage"] == "crawl":
                current["crawl"] = read_json(crawl_control / "progress.json", {})
            elif current["stage"] == "audit":
                current["audit"] = read_json(Path(tempfile.gettempdir()) / "ids13-finalize" / owner / "progress.json", {})
            atomic_json(run_dir / "progress.json", current)
            stop.wait(2)
    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    def stage(name, **extra):
        with lock:
            state.update(stage=name, **extra)
        print(json.dumps({"owner": owner, "stage": name, **extra}), flush=True)
    def interrupted(*args):
        raise KeyboardInterrupt("Explicit workflow stop")
    previous_signal = signal.signal(signal.SIGTERM, interrupted)
    base = corpus_base(config)
    try:
        with IsolatedService("ids_arxiv.io_worker", timeout=60) as io:
            receipt = io.call({"action": "read_json", "path": str(base / "closure.json"), "default": {}})
            if receipt.get("operational_closed"):
                stage("already_closed")
                state["state"] = "stopped_with_documented_exceptions"
                return receipt
            # A prior audit is repaired/resumed directly. Never silently reopen
            # thousands of completed crawl tasks just because audit had I/O errors.
            previous = io.call({"action": "read_json", "path": str(base / "audit-result.json"), "default": {}})
            summary, crawl_stop = {}, None
            if not previous and not receipt.get("audit_in_progress"):
                manifest = Path(config["drive_root"]) / "m1-final-v3/manifests/papers.parquet"
                provenance = io.call({"action": "read_json", "path": str(manifest.with_suffix(".json")), "default": {}})
                end = time.monotonic() + config["max_hours"] * 3600
                while time.monotonic() < end:
                    stage("crawl")
                    old_control = os.environ.get("IDS_LOCAL_STATE_DIR")
                    os.environ["IDS_LOCAL_STATE_DIR"] = str(crawl_control)
                    try:
                        caches = io.call({"action": "cache_catalog", "root": config["drive_root"], "owner": owner})
                        summary = run_crawling_pipeline(
                            manifest, base / "raw", student_id=owner,
                            members_config=Path(__file__).resolve().parents[2] / "configs/members.csv",
                            source_cache_dirs=[p for p in caches if Path(p) != base / "raw"] +
                                              [str(Path(config["drive_root"]) / "m1-final-v3/raw")],
                            expected_manifest_hash=provenance.get("manifest_sha256"),
                            max_network_passes=int(config["max_network_passes"]),
                            paper_seconds=float(config["paper_seconds"]),
                            max_seconds=min(600, max(1, end - time.monotonic())), campaign_mode="full")
                    finally:
                        if old_control is None:
                            os.environ.pop("IDS_LOCAL_STATE_DIR", None)
                        else:
                            os.environ["IDS_LOCAL_STATE_DIR"] = old_control
                    io.call({"action": "write_json", "path": str(Path(config["drive_root"]) / "m1-team-v4/catalog" /
                             f"{config['data_runner_id']}-{owner}-main.json"),
                             "value": {"owner_id": owner, "runner_id": config["data_runner_id"], "stage": "full",
                                       "raw_path": str(base / "raw"), "updated_at": utc_now()}})
                    if summary.get("pending_count") == 0:
                        break
                    observed = time.time()
                    if future_retry_cutoff(summary, observed, config["max_future_retry_wait_seconds"]):
                        crawl_stop = {"reason": "next_retry_beyond_wait_budget", "observed_at": utc_now(),
                                      "next_retry_epoch": summary["next_retry_epoch"],
                                      "wait_budget_seconds": config["max_future_retry_wait_seconds"],
                                      "selected_publications": summary["selected_publications"],
                                      "total_attempted": summary["total_attempted"],
                                      "pending_count": summary["pending_count"],
                                      "note": "No early HTTP retry and no success/absence inference; remaining IDs require audit/review."}
                        io.call({"action": "write_json", "path": str(base / "crawl-stop.json"), "value": crawl_stop})
                        stage("crawl_wait_cutoff", **crawl_stop)
                        break
                    due = summary.get("next_retry_epoch") or time.time() + 10
                    stage("retry_wait", next_retry_epoch=due)
                    while time.time() < due and time.monotonic() < end:
                        time.sleep(min(1, max(.05, due-time.time())))
                if summary.get("pending_count", 1) != 0 and not crawl_stop:
                    if not audit_ready_after_budget(summary):
                        state["state"] = "session_budget_reached"
                        stage("needs_resume", summary={k: v for k, v in summary.items() if k != "failed_ids"})
                        return summary
                    crawl_stop = {"reason": "session_budget_reached_after_full_coverage",
                                  "observed_at": utc_now(),
                                  "selected_publications": summary["selected_publications"],
                                  "total_attempted": summary["total_attempted"],
                                  "pending_count": summary["pending_count"],
                                  "note": "Finite session ended with durable full attempt coverage; remaining data requires audit/review, not success or verified absence."}
                    io.call({"action": "write_json", "path": str(base / "crawl-stop.json"), "value": crawl_stop})
                    stage("crawl_budget_cutoff", **crawl_stop)
                stage("source_evidence")
                collect_source_evidence(config, io, summary)
            stage("audit")
            report = finalize(config, freeze_s2_404=True, repair_pending=bool(previous))
            if crawl_stop:
                report["crawl_stop"] = crawl_stop
                io.call({"action": "write_json", "path": str(base / "audit-result.json"), "value": report})
            exceptions = [row for row in report["records"] if row["classification"] != "full_success"]
            io.call({"action": "write_json", "path": str(base / "exceptions.json"),
                     "value": {"owner": owner, "updated_at": utc_now(), "records": exceptions,
                               "note": "Budget exhaustion/unknown failures are review items, not verified absence or success."}})
            receipt = {k: v for k, v in report.items() if k != "records"}
            receipt.update(automatic_retry_suppressed=True, workflow_finished=True)
            io.call({"action": "write_json", "path": str(base / "closure.json"), "value": receipt})
            state["state"] = "stopped_with_documented_exceptions" if report["operational_closed"] else "stopped_for_review"
            stage("finished", counts=report["counts"], operational_closed=report["operational_closed"])
            return report
    except KeyboardInterrupt:
        state.update(state="interrupted", stage="interrupted")
        raise
    except BaseException as error:
        state.update(state="failed", stage="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        stop.set()
        thread.join(timeout=3)
        state["heartbeat_epoch"] = time.time()
        atomic_json(run_dir / "progress.json", state)
        signal.signal(signal.SIGTERM, previous_signal)


def active_local_jobs():
    result = []
    for process in psutil.process_iter(["pid", "cmdline", "create_time", "status"]):
        try:
            args = process.info["cmdline"] or []
            if process.pid == os.getpid() or process.info["status"] in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                continue
            modern = any(module in args for module in ("ids_arxiv.workflow", "ids_arxiv.team_run", "ids_arxiv.repair")) and "worker" in args
            if modern or "ids_arxiv.finalize" in args or any(Path(arg).name in {"colab_autorun.py", "colab_campaign.py"} for arg in args):
                owner = None
                if "--config-json" in args:
                    value = json.loads(args[args.index("--config-json") + 1])
                    targets = value.get("target_owner_ids", [])
                    owner = targets[0] if len(targets) == 1 else None
                result.append({"pid": process.pid, "create_time": process.info["create_time"],
                               "owner": owner, "workflow": any(m in args for m in ("ids_arxiv.workflow", "ids_arxiv.repair"))})
        except (psutil.Error, ValueError):
            continue
    return result


def start(config):
    config = validate_workflow(config)
    owner = config["target_owner_ids"][0]
    with local_lock(Path(tempfile.gettempdir()) / "ids13-workflow-launch.lock"):
        # Inspect the selected receipt before switching away from live work.
        # Selecting an already closed range must not interrupt another owner.
        with IsolatedService("ids_arxiv.io_worker", timeout=45) as io:
            receipt = io.call({"action": "read_json", "path": str(corpus_base(config) / "closure.json"), "default": {}})
            if receipt.get("operational_closed") or receipt.get("automatic_retry_suppressed"):
                return {"not_launched": True, "owner": owner, "receipt": receipt, "reason": "Already finalized; no automatic recrawl"}
        active = active_local_jobs()
        if len(active) == 1 and active[0]["workflow"] and active[0]["owner"] != owner:
            # Selecting a different MSSV explicitly switches this runtime's
            # workflow only. Never signal a different machine or an unowned PID.
            previous, _ = current_worker_record(active[0]["owner"])
            if (previous.get("pid") == active[0]["pid"] and previous.get("runtime_id") == runtime_id()
                    and abs(previous.get("create_time", -1) - active[0]["create_time"]) < .01):
                stop_owned_worker(previous, grace_seconds=20)
                active = active_local_jobs()
        if active:
            return {"not_launched": True, "active_local_jobs": active,
                    "reason": "One crawler/audit at a time in this runtime; stop the owned previous session explicitly before switching owner."}
        code = Path(__file__).resolve().parents[2]
        command = [sys.executable, "-u", "-m", "ids_arxiv.workflow", "worker", "--config-json", json.dumps(config)]
        process, record = launch_detached(command, code, owner, environment(config))
        return {"launched": process.pid, "owner": owner, "run_id": record["run_id"], "workflow": "crawl_then_audit"}


def status(config):
    owner = config["target_owner_ids"][0]
    record, health = current_worker_record(owner)
    def snapshot(selected):
        with IsolatedService("ids_arxiv.io_worker", timeout=60) as io:
            base = corpus_base({**config, "target_owner_ids": [selected], "data_runner_id": selected})
            try:
                return selected, io.call({"action": "owner_snapshot", "base": str(base), "owner": selected,
                                          "legacy_raw": str(Path(config["drive_root"]) / "m1-final-v3/raw")})
            except (OSError, RuntimeError, TimeoutError) as error:
                return selected, {"read_error": str(error)}
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = dict(pool.map(snapshot, RUNNERS))
    return {"selected_owner": owner, "local_health": health, "local_record": record,
            "owners": rows, "note": "Remote progress files are snapshots, not proof a remote process is alive."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "worker", "status", "stop"])
    parser.add_argument("--owner", choices=RUNNERS)
    parser.add_argument("--drive-root")
    parser.add_argument("--config-json")
    parser.add_argument("--confirm-run-id", default="")
    args = parser.parse_args()
    config = workflow_config(args.owner, args.drive_root) if not args.config_json else validate_workflow(json.loads(args.config_json))
    if args.action == "worker":
        execute(config)
    elif args.action == "start":
        print(json.dumps(start(config)))
    elif args.action == "status":
        print(json.dumps(status(config)))
    else:
        record, _ = current_worker_record(config["target_owner_ids"][0])
        if not record or record.get("run_id") != args.confirm_run_id:
            raise ValueError("Exact current run_id required")
        print(json.dumps(stop_owned_worker(record, grace_seconds=20)))
