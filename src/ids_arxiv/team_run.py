"""One source/notebook, independent runtimes, immutable data-owner identity."""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import psutil

from .benchmark import BenchmarkSession
from .checkpoint import PROTOCOL, read_json
from .completion import account_owner
from .crawler.runner import run_crawling_pipeline
from .isolation import IsolatedService
from .network_schedule import RUNNERS, configured_window
from .runtime import current_worker_record, launch_detached, runtime_id, stop_owned_worker
from .storage import atomic_json, sha256_file, utc_now


def validate_config(value):
    value = dict(value)
    runner = str(value.get("runner_id", ""))
    targets = [str(v) for v in value.get("target_owner_ids", [runner])]
    if runner not in RUNNERS or not targets or len(targets) != len(set(targets)) or not set(targets) <= set(RUNNERS):
        raise ValueError("Select one real runner and distinct valid target owner IDs")
    root = Path(value["drive_root"])
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("Mount and verify the shared Drive folder first")
    if value.get("network_mode", "independent_utc") not in {"independent_utc", "exclusive"}:
        raise ValueError("Unknown network mode")
    if value.get("network_mode") == "exclusive" and not value.get("exclusive_network_confirmed"):
        raise ValueError("Exclusive mode requires confirmation that the other crawlers are stopped")
    if value.get("network_mode", "independent_utc") == "independent_utc" and not value.get("one_runtime_per_runner_confirmed"):
        raise ValueError("Confirm one active runtime per runner ID; duplicate identities would share a UTC turn")
    if not value.get("personal_s2_key_confirmed"):
        raise ValueError("Independent runtimes require a personal S2 key per runner; do not share credentials")
    hours = float(value.get("max_hours", 9))
    if not 0 < hours <= 24:
        raise ValueError("max_hours must be in (0,24]")
    if not 1 <= int(value.get("pilot_size", 5)) <= 50:
        raise ValueError("pilot_size must be in [1,50]")
    label = value.get("run_label", "main")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", label):
        raise ValueError("run_label must be a short safe path component")
    value.update(runner_id=runner, target_owner_ids=targets, max_hours=hours, run_label=label,
                 network_mode=value.get("network_mode", "independent_utc"))
    return value


def output_root(config, owner, stage="full", runtime=None):
    if owner not in config["target_owner_ids"]:
        raise ValueError("Owner is outside this run")
    # Even two helpers selecting the same owner never overwrite each other.
    root = Path(config["drive_root"]) / "m1-team-v4" / config["runner_id"]
    if not config.get("compact_output"):
        root /= runtime or runtime_id()
    return root / config["run_label"] / stage / owner


def environment(config):
    result = dict(os.environ)
    result.update(IDS_RUNNER_ID=config["runner_id"], IDS_NETWORK_MODE=config["network_mode"], IDS_S2_BATCH_PREFETCH="0")
    return result


def owner_summaries(config, stage="full"):
    result = {}
    for owner in config["target_owner_ids"]:
        raw = output_root(config, owner, stage) / "raw"
        key = hashlib.sha256(str(raw).encode()).hexdigest()[:16]
        local = Path(tempfile.gettempdir()) / "ids13-work" / runtime_id() / key / owner
        summary = read_json(local / "summary.json", {})
        summary.pop("failed_ids", None)
        result[owner] = {"summary": summary, "output_raw": str(raw)}
    return result


def audit_outputs(config, io, manifest, provenance, state_dir):
    import pandas as pd
    local = state_dir / "audit-manifest.parquet"
    io.call({"action": "copy", "source": str(manifest), "target": str(local)})
    if sha256_file(local) != provenance["manifest_sha256"]:
        raise RuntimeError("Audit manifest checksum mismatch")
    frame = pd.read_parquet(local)
    for owner in config["target_owner_ids"]:
        ids = frame.loc[frame.owner_student_id.astype(str) == owner, "arxiv_id"].tolist()
        if len(ids) != len(set(ids)) or len(ids) != 5000:
            raise RuntimeError("Audit must cover the full 5000-ID owner manifest")
        proofs = io.call({"action": "read_json", "path": str(Path(config["drive_root"]) /
                         "m1-final-v3" / f"completion-{owner}" / "withdrawal-evidence.json"), "default": {}}).get("records", {})
        destination = output_root(config, owner, "full")
        rows = []
        last_heartbeat = [0.0]
        audit_state = {"state": "running", "runtime_id": runtime_id(), "stage": "audit", "current_owner": owner}
        def heartbeat():
            if time.monotonic() - last_heartbeat[0] >= 1:
                atomic_json(state_dir / "progress.json", {**audit_state, "heartbeat_epoch": time.time()})
                last_heartbeat[0] = time.monotonic()
        with IsolatedService("ids_arxiv.audit_service", timeout=60, heartbeat=heartbeat) as audit:
            for aid in ids:
                audit_state.update(current_paper=aid, audited_count=len(rows), stage_deadline_epoch=time.time() + 60)
                try:
                    if audit.process is None or audit.process.poll() is not None:
                        audit.call({"action": "init", "ids": ids, "raw": str(destination / "raw"), "proofs": proofs})
                    audit_state["stage_deadline_epoch"] = time.time() + 60
                    rows.append(audit.call({"action": "assess", "arxiv_id": aid}))
                except (RuntimeError, TimeoutError, OSError) as error:
                    rows.append({"arxiv_id": aid, "classification": "pending", "data_download_success": False,
                                 "withdrawn_versions": [], "reasons": [f"Audit I/O failed: {type(error).__name__}"]})
                if len(rows) % 25 == 0 or len(rows) == len(ids):
                    report = account_owner(owner, ids, rows)
                    report.update(runner_student_id=config["runner_id"], protocol_version=PROTOCOL,
                                  source_sha256=os.environ.get("IDS_SOURCE_SHA256"))
                    atomic_json(state_dir / f"audit-{owner}.json", report)
                    io.call({"action": "write_json", "path": str(destination / "audit-result.json"), "value": report})
                    atomic_json(state_dir / "progress.json", {"state": "running", "runtime_id": runtime_id(),
                                "stage": "audit", "current_owner": owner, "audited_count": len(rows),
                                "heartbeat_epoch": time.time(), "collection_closed": report["collection_closed"]})


def worker(config, stage):
    if not Path("/content").is_dir() or not os.environ.get("COLAB_RELEASE_TAG") or os.environ.get("COLAB_GPU", "0") not in {"", "0"}:
        raise RuntimeError("Run the collection/benchmark on Google Colab CPU")
    root = Path(config["drive_root"])
    manifest = root / "m1-final-v3/manifests/papers.parquet"
    state_dir = Path(os.environ["IDS_LOCAL_STATE_DIR"])
    progress = state_dir / "progress.json"
    budget_end = time.monotonic() + config["max_hours"] * 3600
    os.environ.update(environment(config))
    with IsolatedService("ids_arxiv.io_worker", timeout=60) as io:
        provenance = io.call({"action": "read_json", "path": str(manifest.with_suffix(".json")), "default": {}})
        if not provenance.get("verified_discovery") or not provenance.get("manifest_sha256"):
            raise RuntimeError("Need the verified group manifest; do not invent/re-scrape ranges")
        if stage == "audit":
            audit_outputs(config, io, manifest, provenance, state_dir)
            atomic_json(progress, {"state": "finished", "runtime_id": runtime_id(), "stage": "audit_finished",
                                   "heartbeat_epoch": time.time(), "note": "Read audit-result.json; worker exit alone is not data completion"})
            return
        results = {}
        output_stage = "full" if stage == "auto" else stage
        probe_passed = set()
        with BenchmarkSession(output_root(config, config["target_owner_ids"][0], output_stage) / "team-benchmark",
                              campaign="independent-team-v4") as overall:
            overall.record.update(session_kind="team_supervisor", runner_student_id=config["runner_id"],
                                  target_owner_ids=config["target_owner_ids"], network_mode=config["network_mode"],
                                  protocol_version=PROTOCOL, benchmark_mode="verified_cache_recovery")
            while time.monotonic() < budget_end:
                next_times = []
                for owner in config["target_owner_ids"]:
                    destination = output_root(config, owner, output_stage)
                    if stage == "auto" and owner not in probe_passed:
                        probe_gate = io.call({"action": "read_json", "path": str(destination / "probe-result.json"), "default": {}})
                        if (probe_gate.get("passed") and probe_gate.get("protocol_version") == PROTOCOL
                                and probe_gate.get("source_sha256") == os.environ.get("IDS_SOURCE_SHA256")
                                and probe_gate.get("manifest_sha256") == provenance["manifest_sha256"]):
                            probe_passed.add(owner)
                    probing = stage == "auto" and owner not in probe_passed
                    if stage == "full":
                        gate = io.call({"action": "read_json", "path": str(output_root(config, owner, "pilot") / "pilot-result.json"), "default": {}})
                        if (not gate.get("passed") or gate.get("protocol_version") != PROTOCOL
                                or gate.get("source_sha256") != os.environ.get("IDS_SOURCE_SHA256")
                                or gate.get("manifest_sha256") != provenance["manifest_sha256"]):
                            raise RuntimeError(f"Run a successful current-policy pilot for owner {owner} first")
                    caches = [*config.get("cache_dirs", [])]
                    caches.extend(io.call({"action": "cache_catalog", "root": str(root), "owner": owner}))
                    caches.append(str(root / "m1-final-v3/raw"))
                    remaining = budget_end - time.monotonic()
                    if remaining <= 0:
                        break
                    summary = run_crawling_pipeline(
                        manifest, destination / "raw", student_id=owner,
                        members_config=Path(__file__).resolve().parents[2] / "configs/members.csv",
                        limit=int(config.get("pilot_size", 5)) if stage == "pilot" or probing else None,
                        max_seconds=min(remaining, 1800), expected_manifest_hash=provenance["manifest_sha256"],
                        source_cache_dirs=[path for path in dict.fromkeys(caches) if Path(path) != destination / "raw"],
                        campaign_mode="full" if stage == "auto" else None,
                        work_namespace="probe" if probing else None,
                    )
                    if probing:
                        passed = summary["success_count"] == int(config.get("pilot_size", 5))
                        io.call({"action": "write_json", "path": str(destination / "probe-result.json"),
                                 "value": {"passed": passed, "protocol_version": PROTOCOL,
                                           "source_sha256": os.environ.get("IDS_SOURCE_SHA256"),
                                           "manifest_sha256": provenance["manifest_sha256"]}})
                        summary["auto_probe_only"] = True
                        if passed:
                            probe_passed.add(owner)
                            next_times.append(time.time())
                    results[owner] = summary
                    summary["runner_student_id"] = config["runner_id"]
                    if stage == "pilot":
                        io.call({"action": "write_json", "path": str(destination / "pilot-result.json"),
                                 "value": {"passed": summary["success_count"] == int(config.get("pilot_size", 5)),
                                           "protocol_version": PROTOCOL, "runner_id": config["runner_id"],
                                           "source_sha256": os.environ.get("IDS_SOURCE_SHA256"),
                                           "manifest_sha256": provenance["manifest_sha256"],
                                           "owner_id": owner, "summary": summary}})
                    else:
                        catalog_runtime = "" if config.get("compact_output") else f"-{runtime_id()}"
                        catalog = root / "m1-team-v4" / "catalog" / f"{config['runner_id']}{catalog_runtime}-{owner}-{config['run_label']}.json"
                        io.call({"action": "write_json", "path": str(catalog),
                                 "value": {"owner_id": owner, "runner_id": config["runner_id"], "stage": output_stage,
                                           "raw_path": str(destination / "raw"), "updated_at": utc_now()}})
                    if summary["success_count"] != summary["selected_publications"]:
                        due = summary.get("next_retry_epoch")
                        next_times.append(due if due is not None else time.time() + 60)
                if not next_times:
                    break
                wait_until = min(next_times)
                # Background work-queue wait, not a notebook keepalive loop.
                while time.time() < wait_until and time.monotonic() < budget_end:
                    atomic_json(progress, {"state": "running", "runtime_id": runtime_id(), "stage": "retry_wait",
                                           "next_retry_epoch": wait_until, "heartbeat_epoch": time.time(),
                                           "runner_student_id": config["runner_id"], "results": results})
                    time.sleep(min(1, max(0.05, wait_until - time.time())))
            atomic_json(progress, {"state": "completed" if results and all(
                result["success_count"] == result["selected_publications"] and not result.get("auto_probe_only")
                for result in results.values()) else "needs_recovery",
                "runtime_id": runtime_id(), "runner_student_id": config["runner_id"], "results": results,
                "heartbeat_epoch": time.time()})
        overall.mirror(io)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["preflight", "launch", "worker", "status", "stop", "report"])
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--stage", choices=["pilot", "full", "audit", "auto"], default="pilot")
    parser.add_argument("--confirm-run-id", default="")
    args = parser.parse_args()
    config = validate_config(json.loads(args.config_json))
    runner = config["runner_id"]
    if args.action == "preflight":
        import importlib.metadata

        import pandas as pd
        for name in ("ARXIV_CONTACT_EMAIL", "SEMANTIC_SCHOLAR_API_KEY"):
            if not os.environ.get(name):
                raise ValueError(f"Missing Colab Secret: {name}; never paste its value into notebook code")
        root = Path(config["drive_root"])
        local = Path(tempfile.mkdtemp(prefix="ids13-preflight-")) / "manifest.parquet"
        manifest = root / "m1-final-v3/manifests/papers.parquet"
        with IsolatedService("ids_arxiv.io_worker", timeout=45) as io:
            evidence = io.call({"action": "read_json", "path": str(manifest.with_suffix(".json")), "default": {}})
            io.call({"action": "copy", "source": str(manifest), "target": str(local)})
            if not evidence.get("verified_discovery") or sha256_file(local) != evidence.get("manifest_sha256"):
                raise RuntimeError("Manifest not verified")
            frame = pd.read_parquet(local)
            counts = {owner: int((frame.owner_student_id.astype(str) == owner).sum()) for owner in config["target_owner_ids"]}
            if any(count != 5000 for count in counts.values()):
                raise RuntimeError("Each selected owner must have exactly 5000 manifest IDs")
            environment_record = {"runner_id": runner, "targets": counts, "protocol_version": PROTOCOL,
                                  "source_sha256": os.environ.get("IDS_SOURCE_SHA256"),
                                  "packages": {name: importlib.metadata.version(name) for name in
                                               ("requests", "pandas", "pyarrow", "pydantic", "psutil", "pytest")}}
            for owner in config["target_owner_ids"]:
                io.call({"action": "write_json", "path": str(output_root(config, owner) / "environment.json"),
                         "value": environment_record})
        print(json.dumps(environment_record))
        local.unlink(missing_ok=True)
        local.parent.rmdir()
        return
    if args.action == "report":
        with IsolatedService("ids_arxiv.io_worker", timeout=45) as io:
            reports = {}
            for owner in config["target_owner_ids"]:
                value = io.call({"action": "read_json", "path": str(output_root(config, owner) / "audit-result.json"), "default": {}})
                value.pop("records", None)
                reports[owner] = value or {"note": "No full audit report in this workspace yet"}
        print(json.dumps(reports, ensure_ascii=False))
        return
    if args.action == "worker":
        try:
            worker(config, args.stage)
        except BaseException as error:
            atomic_json(Path(os.environ["IDS_LOCAL_STATE_DIR"]) / "progress.json",
                        {"state": "interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                         "runtime_id": runtime_id(), "runner_student_id": runner,
                         "error": type(error).__name__, "heartbeat_epoch": time.time()})
            raise
        return
    record, health = current_worker_record(runner)
    if args.action == "status":
        os.environ.update(environment(config))
        window = configured_window()
        print(json.dumps({"health": health, "record": record, "owners": owner_summaries(config),
                          "pilot_owners": owner_summaries(config, "pilot"),
                          "network_window": window.status() if window else None}, ensure_ascii=False))
        return
    if args.action == "stop":
        if not record or args.confirm_run_id != record.get("run_id"):
            raise ValueError("Enter the exact run_id from Monitor; never Stop/Interrupt the notebook kernel")
        print(json.dumps(stop_owned_worker(record)))
        return
    if args.action == "launch" and args.stage != "audit":
        with IsolatedService("ids_arxiv.io_worker", timeout=30) as io:
            for owner in config["target_owner_ids"]:
                receipt = io.call({"action": "read_json", "path": str(output_root(config, owner) / "closure.json"), "default": {}})
                if (receipt.get("operational_closed") or receipt.get("audit_in_progress")
                        or receipt.get("automatic_retry_suppressed")) and receipt.get("protocol_version") == PROTOCOL:
                    print(json.dumps({"not_launched": True, "reason": "Owner corpus frozen after audit; no automatic retry. Review closure.json to reopen explicitly.", "owner": owner, "counts": receipt.get("counts"), "collection_closed": receipt.get("collection_closed")}))
                    return
    for process in psutil.process_iter(["pid", "cmdline", "status"]):
        try:
            command = " ".join(process.info["cmdline"] or [])
            if process.info["status"] not in {psutil.STATUS_DEAD, psutil.STATUS_ZOMBIE} and any(
                marker in command for marker in ("colab_autorun.py", "colab_campaign.py", "colab_install_and_run.py", "ids_arxiv.team_run worker", "ids_arxiv.workflow worker")
            ):
                print(json.dumps({"not_launched": True, "existing_pid": process.pid,
                                  "reason": "A crawler is already active; use Monitor/explicit Stop. Its configuration is unchanged."}))
                return
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    code = Path(__file__).resolve().parents[2]
    command = [sys.executable, "-m", "ids_arxiv.team_run", "worker", "--config-json", json.dumps(config), "--stage", args.stage]
    process, record = launch_detached(command, code, runner, environment(config))
    print(json.dumps({"launched": process.pid, "run_id": record["run_id"], "runner_id": runner,
                      "target_owner_ids": config["target_owner_ids"], "stage": args.stage}))


if __name__ == "__main__":
    main()
