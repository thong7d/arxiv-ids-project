"""Explicit bounded repair plans; never reopen verified data automatically."""

import hashlib
import json
import os
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def build_plan(audit, owner, manifest_sha256, max_seconds=32400):
    """Freeze exactly one full audit and prioritize metadata before references."""
    owner = str(owner)
    rows = audit.get("records", [])
    ids = [row.get("arxiv_id") for row in rows]
    if (str(audit.get("student_id")) != owner
            or audit.get("discovery_manifest_sha256") != manifest_sha256
            or audit.get("protocol_version") != 4
            or len(rows) != 5000 or len(set(ids)) != 5000
            or any(not isinstance(aid, str) for aid in ids)
            or audit.get("missing_ids") or audit.get("outside_ids") or audit.get("duplicate_ids")):
        raise ValueError("Repair requires an exact full current-protocol owner audit")
    if not 60 <= max_seconds <= 32400:
        raise ValueError("Repair session must be bounded to 60..32400 seconds")
    targets = []
    for row in rows:
        if row.get("classification") != "pending":
            continue
        reasons = row.get("reasons", [])
        metadata = any("Version dates not verified" in reason or "version sequence" in reason
                       for reason in reasons)
        audit_only = bool(reasons) and all("task exceeded deadline" in reason for reason in reasons)
        targets.append({"arxiv_id": row["arxiv_id"],
                        "priority": 0 if metadata else (2 if audit_only else 1),
                        "metadata_refresh": metadata, "audit_only": audit_only,
                        "commit_marker_sha256": row.get("commit_marker_sha256")})
    targets.sort(key=lambda row: (row["priority"], row["arxiv_id"]))
    plan = {"owner": owner, "manifest_sha256": manifest_sha256,
            "audit_sha256": fingerprint(audit), "max_seconds": max_seconds,
            "additional_network_passes": 1, "targets": targets,
            "note": "Explicit pending-only repair; preserve cooldowns, complete data and evidence. Budget exhaustion is review, not absence."}
    return {**plan, "plan_sha256": fingerprint(plan)}


def validate_plan(plan, audit, assigned_ids):
    """Reject a stale audit, modified plan, or selection outside this owner."""
    unsigned = {k: v for k, v in plan.items() if k != "plan_sha256"}
    if fingerprint(unsigned) != plan.get("plan_sha256"):
        raise ValueError("Repair plan checksum mismatch")
    if fingerprint(audit) != plan.get("audit_sha256"):
        raise ValueError("Audit changed since repair was approved")
    if len(assigned_ids) != 5000 or set(assigned_ids) != {r["arxiv_id"] for r in audit["records"]}:
        raise ValueError("Repair audit does not match assigned owner IDs")
    rebuilt = build_plan(audit, plan["owner"], plan["manifest_sha256"], plan["max_seconds"])
    if rebuilt != plan:
        raise ValueError("Repair plan must select exactly the audited pending records")
    return plan


def prepare_local(directory, metadata_refresh=False, allow_missing=False):
    """Only invalidate the staged copy; original Drive bytes stay intact."""
    from .checkpoint import read_json
    from .storage import atomic_json
    directory = Path(directory)
    status = read_json(directory / "crawl_status.json", {})
    if status:
        status.update(success=False, commit_state="staged")
        atomic_json(directory / "crawl_status.json", status)
    elif not allow_missing:
        raise ValueError("Repair requires the audited existing publication")
    if metadata_refresh and (status or (directory / "metadata.json").is_file()):
        metadata = read_json(directory / "metadata.json", {})
        metadata["metadata_dates_complete"] = False
        atomic_json(directory / "metadata.json", metadata)


def execute(config):
    """One extra paper pass per planned ID, checkpointed BEFORE network work."""
    from .checkpoint import read_json
    from .discovery import to_dir_id
    from .finalize import finalize
    from .isolation import IsolatedService
    from .network_schedule import configured_window
    from .runtime import runtime_id
    from .storage import atomic_json, sha256_file, utc_now
    from .team_run import environment
    from .workflow import collect_source_evidence, corpus_base

    owner = config["target_owner_ids"][0]
    base = corpus_base(config)
    run_dir = Path(os.environ["IDS_LOCAL_STATE_DIR"])
    state = {"state": "running", "stage": "repair", "owner": owner, "started_at": utc_now()}
    stop = threading.Event()
    def pulse():
        while not stop.is_set():
            state.update(heartbeat_epoch=time.time(), heartbeat_at=utc_now())
            if state.get("stage") == "audit":
                state["audit"] = read_json(Path(tempfile.gettempdir())/"ids13-finalize"/owner/"progress.json", {})
            atomic_json(run_dir/"progress.json", dict(state))
            stop.wait(2)
    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    def interrupted(*args):
        raise KeyboardInterrupt("Repair explicitly stopped")
    old_signal = signal.signal(signal.SIGTERM, interrupted)
    try:
        with IsolatedService("ids_arxiv.io_worker", timeout=180) as io:
            def read(path):
                return io.call({"action": "read_json", "path": str(path), "default": {}})
            def write(path, value):
                return io.call({"action": "write_json", "path": str(path), "value": value})
            audit = read(base/"audit-result.json")
            manifest = Path(config["drive_root"])/"m1-final-v3/manifests/papers.parquet"
            provenance = read(manifest.with_suffix(".json"))
            with tempfile.TemporaryDirectory(prefix="ids13-repair-manifest-") as scratch:
                copied = Path(scratch)/"papers.parquet"
                io.call({"action": "copy", "source": str(manifest), "target": str(copied)})
                if not provenance.get("verified_discovery") or sha256_file(copied) != provenance.get("manifest_sha256"):
                    raise ValueError("Unverified repair manifest")
                import pandas as pd
                frame = pd.read_parquet(copied)
                assigned = frame.loc[frame.owner_student_id.astype(str) == owner, "arxiv_id"].tolist()
            plan_path, progress_path = base/"repair-plan.json", base/"repair-progress.json"
            plan = read(plan_path)
            progress = read(progress_path)
            if plan and (progress.get("finished") or plan.get("audit_sha256") != fingerprint(audit)):
                stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
                write(base/"repair-history"/f"repair-plan_{stamp}.json", plan)
                if progress:
                    write(base/"repair-history"/f"repair-progress_{stamp}.json", progress)
                plan, progress = {}, {}
            if not plan:
                repair_max_seconds = int(os.getenv("IDS_REPAIR_MAX_SECONDS", "32400") or 32400)
                plan = build_plan(audit, owner, provenance["manifest_sha256"], max_seconds=repair_max_seconds)
                validate_plan(plan, audit, assigned)
                write(plan_path, plan)
            if progress.get("finished"):
                state.update(state="stopped_for_review", stage="finished")
                return progress
            validate_plan(plan, audit, assigned)
            if progress and progress.get("plan_sha256") != plan["plan_sha256"]:
                raise ValueError("Repair progress belongs to another immutable plan")
            progress = progress or {"plan_sha256": plan["plan_sha256"], "attempted": {}, "started_epoch": time.time()}
            # The wall budget is persistent across VM loss/resume, not reset by Run all.
            end = progress["started_epoch"] + plan["max_seconds"]
            spool = Path(tempfile.gettempdir())/"ids13-repair"/runtime_id()/owner/plan["plan_sha256"][:16]
            spool.mkdir(parents=True, exist_ok=True)
            events = spool/"http-events.jsonl"
            state.update(planned=len(plan["targets"]), processed=len(progress["attempted"]))
            paper_env = dict(environment(config))
            paper_env.setdefault("IDS_S2_WAIT_CAP_SECONDS", "125")
            with IsolatedService("ids_arxiv.crawler.paper_worker", timeout=180, environment=paper_env) as papers:
                def init():
                    if papers.process is None or papers.process.poll() is not None:
                        papers.call({"action": "init", "root": str(spool)})
                for target in plan["targets"]:
                    aid = target["arxiv_id"]
                    previous = progress["attempted"].get(aid)
                    local = spool/"raw"/to_dir_id(aid)
                    remote = base/"raw"/to_dir_id(aid)
                    if previous:
                        if previous.get("state") == "upload_pending":
                            if previous.get("runtime_id") != runtime_id():
                                raise RuntimeError("Pending repair upload belongs to a lost runtime; inspect before proceeding")
                            io.call({"action": "commit", "local": str(local), "remote": str(remote), "record": previous["record"]})
                            previous.update(state="committed")
                            write(progress_path, progress)
                        continue
                    if time.time() >= end:
                        break
                    if target["audit_only"]:
                        continue
                    expected_marker = target.get("commit_marker_sha256")
                    marker = io.call({"action": "marker_hash", "path": str(remote)})
                    if marker != expected_marker:
                        raise ValueError("Audited commit changed; refusing stale repair: " + aid)
                    current = read(remote/"crawl_status.json")
                    if current.get("next_retry_epoch", 0) > time.time():
                        continue  # Never bypass Retry-After or persisted cooldown.
                    window = configured_window()
                    while window and not window.status()["allowed"] and time.time() < end:
                        state.update(stage="retry_wait", next_retry_epoch=window.status()["next_epoch"])
                        time.sleep(min(1, max(.05, end-time.time())))
                    if time.time() >= end:
                        break
                    state.update(stage="repair", current_paper=aid)
                    progress["attempted"][aid] = {"state": "attempt_reserved", "at": utc_now(), "runtime_id": runtime_id()}
                    write(progress_path, progress)
                    offset = events.stat().st_size if events.exists() else 0
                    try:
                        io.call({"action": "stage", "remote": str(remote), "local": str(local), "force_revalidate": True})
                        prepare_local(local, target["metadata_refresh"], allow_missing=expected_marker is None)
                        init()
                        # Existing clients enforce the same per-provider pacing and UTC schedule.
                        result = papers.call({"action": "paper", "arxiv_id": aid, "output": str(spool/"raw"), "resume": True},
                                             timeout=min(180, max(1, end-time.time())))
                        from .retry_budget import had_http_activity
                        result["bounded_network_passes"] = current.get("bounded_network_passes", 0) + int(had_http_activity(events, offset))
                        result["repair_plan_sha256"] = plan["plan_sha256"]
                        progress["attempted"][aid].update(state="upload_pending", record=result)
                        write(progress_path, progress)
                        io.call({"action": "commit", "local": str(local), "remote": str(remote), "record": result})
                        progress["attempted"][aid].update(state="committed")
                    except (TimeoutError, RuntimeError, OSError) as error:
                        row = progress["attempted"][aid]
                        if row["state"] == "upload_pending":
                            raise  # Preserve pending payload; no audit over unsaved results.
                        row.update(state="attempt_failed_review", error=type(error).__name__ + ": " + str(error))
                    write(progress_path, progress)
                    state["processed"] = len(progress["attempted"])
            state["stage"] = "source_evidence"
            collect_source_evidence(config, io, {"failed_ids": [t["arxiv_id"] for t in plan["targets"]]})
            state["stage"] = "audit"
            if events.exists():
                try:
                    io.call({"action": "copy", "source": str(events),
                             "target": str(base/"repair-history"/f"http-events-{plan['plan_sha256'][:12]}.jsonl")})
                except (OSError, RuntimeError, TimeoutError):
                    pass
            report = finalize(config, freeze_s2_404=True, repair_pending=True)
            receipt = {k: v for k, v in report.items() if k != "records"}
            receipt.update(automatic_retry_suppressed=True, workflow_finished=True, repair_plan_sha256=plan["plan_sha256"])
            write(base/"closure.json", receipt)
            write(base/"exceptions.json", {"owner": owner, "updated_at": utc_now(),
                  "records": [r for r in report["records"] if r["classification"] != "full_success"]})
            progress.update(finished=True, finished_at=utc_now(), counts=report["counts"])
            write(progress_path, progress)
            state.update(state="stopped_with_documented_exceptions" if report["operational_closed"] else "stopped_for_review", stage="finished", counts=report["counts"])
            return receipt
    except BaseException as error:
        state.update(state="interrupted" if isinstance(error, KeyboardInterrupt) else "failed", stage="failed", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        stop.set()
        thread.join(timeout=3)
        atomic_json(run_dir/"progress.json", state)
        signal.signal(signal.SIGTERM, old_signal)


def start(config):
    from .runtime import (
        current_worker_record,
        launch_detached,
        local_lock,
        runtime_id,
        stop_owned_worker,
    )
    from .team_run import environment
    from .workflow import active_local_jobs, validate_workflow
    config = validate_workflow(config)
    owner = config["target_owner_ids"][0]
    with local_lock(Path(tempfile.gettempdir())/"ids13-workflow-launch.lock"):
        jobs = active_local_jobs()
        if len(jobs) == 1 and jobs[0]["workflow"] and jobs[0]["owner"] != owner:
            previous, _ = current_worker_record(jobs[0]["owner"])
            if (previous.get("pid") == jobs[0]["pid"] and previous.get("runtime_id") == runtime_id()
                    and abs(previous.get("create_time", -1) - jobs[0]["create_time"]) < .01):
                stop_owned_worker(previous, grace_seconds=20)
                jobs = active_local_jobs()
        if jobs:
            return {"not_launched": True, "active_local_jobs": jobs,
                    "reason": "An existing local crawler/audit is already active in this runtime"}
        code = Path(__file__).resolve().parents[2]
        command = [sys.executable, "-u", "-m", "ids_arxiv.repair", "worker", "--config-json", json.dumps(config)]
        process, record = launch_detached(command, code, owner, environment(config))
        return {"launched": process.pid, "run_id": record["run_id"], "owner": owner, "workflow": "targeted_repair_then_audit"}


if __name__ == "__main__":
    import argparse

    from .workflow import validate_workflow
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "worker"])
    parser.add_argument("--config-json", required=True)
    args = parser.parse_args()
    config = validate_workflow(json.loads(args.config_json))
    print(json.dumps(start(config) if args.action == "start" else execute(config), default=str))
