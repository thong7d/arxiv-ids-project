"""Explicit bounded final audit/freeze. Never rewrite crawler success flags."""

import argparse
import json
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .audit_journal import AuditJournal, digest
from .checkpoint import PROTOCOL, read_json
from .completion import account_owner
from .isolation import IsolatedService
from .network_schedule import RUNNERS
from .runtime import current_worker_record, stop_owned_worker
from .storage import atomic_json, sha256_file, utc_now
from .team_run import output_root, validate_config


def finalize(config, stop_current=False, freeze_s2_404=False, extra_evidence=None, repair_pending=False,
             resume=True, freeze_s2_rate_limited=False):
    config = validate_config(config)
    if len(config["target_owner_ids"]) != 1:
        raise ValueError("Audit one owner at a time")
    owner = config["target_owner_ids"][0]
    # Operator and data owner are independent; owner determines the manifest
    # and output, never the account supplying credentials/network identity.
    record, health = current_worker_record(owner)
    if record.get("pid") != os.getpid() and health["health"] in {"RUNNING", "WAITING", "STALLED"}:
        if not stop_current:
            raise ValueError("Stop/checkpoint the owner's crawler first, or explicitly pass --stop-current")
        print(json.dumps({"stopping_run": record["run_id"], "result": stop_owned_worker(record, grace_seconds=20)}), flush=True)
        if current_worker_record(owner)[1]["health"] in {"RUNNING", "WAITING", "STALLED"}:
            raise RuntimeError("Crawler still active; refusing concurrent final audit")
    root = Path(config["drive_root"])
    data_runner = str(config.get("data_runner_id", owner))
    if data_runner not in RUNNERS:
        raise ValueError("Invalid data runner namespace")
    destination = output_root({**config, "runner_id": data_runner}, owner)
    local = Path(tempfile.gettempdir()) / "ids13-finalize" / owner
    local.mkdir(parents=True, exist_ok=True)
    state = {"state": "auditing", "owner": owner, "started_at": utc_now(), "assessed_count": 0}
    atomic_json(local / "progress.json", state)
    with IsolatedService("ids_arxiv.io_worker", timeout=60) as io:
        manifest = root / "m1-final-v3/manifests/papers.parquet"
        provenance = io.call({"action": "read_json", "path": str(manifest.with_suffix(".json")), "default": {}})
        with tempfile.TemporaryDirectory(prefix="ids13-final-manifest-") as temporary:
            copied = Path(temporary) / "papers.parquet"
            io.call({"action": "copy", "source": str(manifest), "target": str(copied)})
            if not provenance.get("verified_discovery") or sha256_file(copied) != provenance.get("manifest_sha256"):
                raise ValueError("Manifest provenance mismatch")
            import pandas as pd
            frame = pd.read_parquet(copied)
            ids = frame.loc[frame.owner_student_id.astype(str) == owner, "arxiv_id"].tolist()
        if len(ids) != 5000 or len(set(ids)) != 5000:
            raise ValueError("Need exactly 5000 distinct owned IDs")
        proofs = io.call({"action": "read_json", "path": str(root / f"m1-final-v3/completion-{owner}/withdrawal-evidence.json"), "default": {}}).get("records", {})
        saved_proofs = io.call({"action": "read_json", "path": str(destination / "closure-evidence.json"), "default": {}})
        if str(saved_proofs.get("student_id")) == owner:
            proofs.update(saved_proofs.get("records", {}))
        if extra_evidence:
            extra = read_json(extra_evidence, {})
            if str(extra.get("student_id")) != owner:
                raise ValueError("Extra evidence belongs to another owner")
            values = extra.get("records", [])
            if isinstance(values, dict):
                values = values.values()
            for proof in values:
                if proof.get("arxiv_id") not in set(ids):
                    raise ValueError("Evidence outside owner manifest")
                proofs[f"{proof['arxiv_id']}v{proof['version']}"] = proof
        previous = {}
        audit_ids = ids
        rows = []
        if repair_pending:
            previous = io.call({"action": "read_json", "path": str(destination / "audit-result.json"), "default": {}})
            old_rows = previous.get("records", [])
            if (previous.get("protocol_version") != PROTOCOL
                    or previous.get("discovery_manifest_sha256") != provenance["manifest_sha256"]
                    or len(old_rows) != 5000 or {r.get("arxiv_id") for r in old_rows} != set(ids)):
                raise ValueError("Incremental repair requires an exact prior full audit of this manifest")
            rows = [r for r in old_rows if r.get("classification") != "pending"]
            audit_ids = [r["arxiv_id"] for r in old_rows if r.get("classification") == "pending"]
            state.update(reused_assessments=len(rows), repair_count=len(audit_ids), assessed_count=len(rows))
        context = {"owner": owner, "raw_path": str(destination / "raw"),
                   "manifest_sha256": provenance["manifest_sha256"], "protocol": PROTOCOL,
                   "proofs_sha256": digest(proofs), "freeze_s2_404": freeze_s2_404,
                   "freeze_s2_rate_limited": freeze_s2_rate_limited,
                   "validator_sha256": digest({name: sha256_file(Path(__file__).with_name(name))
                                               for name in ("completion.py", "audit_service.py")})}
        journal = AuditJournal(io, destination / "audit-checkpoint", context, ids)
        restored = journal.load() if resume else {}
        if resume and not repair_pending:
            resume_stamp = 0
            for checked, (aid, row) in enumerate(restored.items(), 1):
                if row.get("classification") == "pending" or not row.get("commit_marker_sha256"):
                    continue
                actual = io.call({"action": "marker_hash", "path": str(destination / "raw" / aid.replace(".", "-"))})
                if actual == row["commit_marker_sha256"]:
                    rows.append(row)
                if time.monotonic() - resume_stamp >= 2:
                    state.update(state="validating_checkpoint", assessed_count=len(rows),
                                 reused_assessments=len(rows), restored_checked_count=checked,
                                 current_paper=aid, heartbeat_at=utc_now())
                    atomic_json(local / "progress.json", state)
                    resume_stamp = time.monotonic()
            seen = {row["arxiv_id"] for row in rows}
            audit_ids = [aid for aid in ids if aid not in seen]
            state.update(reused_assessments=len(rows), assessed_count=len(rows))
        for row in rows:
            if row["arxiv_id"] not in restored:
                journal.remember(row)
        io.call({"action": "write_json", "path": str(destination / "closure.json"),
                 "value": {"student_id": owner, "protocol_version": PROTOCOL,
                           "audit_in_progress": True, "operational_closed": False,
                           "collection_closed": False, "started_at": utc_now()}})
        services, thread = [], threading.local()
        state.update(state="auditing", assessed_count=len(rows))
        atomic_json(local / "progress.json", state)
        def assess(aid):
            if not hasattr(thread, "audit"):
                thread.audit = IsolatedService("ids_arxiv.audit_service", timeout=90 if repair_pending else 30)
                services.append(thread.audit)
            audit = thread.audit
            try:
                if audit.process is None or audit.process.poll() is not None:
                    audit.call({"action": "init", "ids": ids, "raw": str(destination / "raw"),
                                "proofs": proofs, "allow_s2_unavailable": freeze_s2_404,
                                "allow_s2_rate_limited": freeze_s2_rate_limited})
                return audit.call({"action": "assess", "arxiv_id": aid})
            except (OSError, RuntimeError, TimeoutError) as error:
                return {"arxiv_id": aid, "classification": "pending", "data_download_success": False,
                        "withdrawn_versions": [], "reasons": [str(error)]}
        last_saved = 0
        try:
            # Read-only I/O concurrency, NOT network crawling. Each lane has a
            # separate bounded child, so a blocked Drive read cannot hang all.
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(assess, aid) for aid in audit_ids]
                for future in as_completed(futures):
                    row = future.result()
                    rows.append(row)
                    journal.remember(row)
                    state.update(assessed_count=len(rows), current_paper=row["arxiv_id"], heartbeat_at=utc_now())
                    if time.monotonic() - last_saved >= 2 or len(rows) == len(ids):
                        atomic_json(local / "progress.json", state)
                        last_saved = time.monotonic()
                    if len(rows) % 100 == 0:
                        journal.flush()
                        io.call({"action": "write_json", "path": str(destination / "audit-progress.json"), "value": dict(state)})
                        print(json.dumps(state), flush=True)
        finally:
            for service in services:
                service.close()
            journal.flush()
        report = account_owner(owner, ids, rows)
        operational = (len(rows) == 5000 and not report["missing_ids"] and not report["outside_ids"]
                       and not report["duplicate_ids"] and all(not r["reasons"] and r["classification"] in {
                           "full_success", "verified_exception", "references_unavailable"} for r in rows))
        report.update(operational_closed=operational, protocol_version=PROTOCOL,
                      operator_student_id=config["runner_id"], data_runner_id=data_runner,
                      discovery_manifest_sha256=provenance["manifest_sha256"],
                      source_sha256=os.getenv("IDS_SOURCE_SHA256"),
                      s2_404_freeze_authorized=freeze_s2_404,
                      s2_rate_limited_freeze_authorized=freeze_s2_rate_limited,
                      academic_exception_approval_pending=bool(report["counts"].get("references_unavailable")),
                      state="stopped_with_documented_exceptions" if operational else "needs_repair")
        if repair_pending:
            report.update(incremental_audit=True, rechecked_count=len(audit_ids),
                          reused_assessments_from=previous.get("audited_at"),
                          previous_source_sha256=previous.get("source_sha256"))
        atomic_json(local / "audit-result.json", report)
        # Evidence and audit are durable; no raw/status/index record is changed.
        io.call({"action": "write_json", "path": str(destination / "closure-evidence.json"),
                 "value": {"student_id": owner, "records": proofs}})
        io.call({"action": "write_json", "path": str(destination / "audit-result.json"), "value": report})
        receipt = {k: v for k, v in report.items() if k != "records"}
        receipt["note"] = "Operational stop is not academic approval or 5000 successful downloads. Explicitly reopen by removing this receipt after review."
        io.call({"action": "write_json", "path": str(destination / "closure.json"), "value": receipt})
        atomic_json(local / "progress.json", {**state, "state": report["state"], "finished_at": utc_now(), "counts": report["counts"]})
        io.call({"action": "write_json", "path": str(destination / "audit-progress.json"),
                 "value": {**state, "state": report["state"], "finished_at": utc_now(), "counts": report["counts"]}})
        print(json.dumps(receipt), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--stop-current", action="store_true")
    parser.add_argument("--freeze-s2-404", action="store_true")
    parser.add_argument("--freeze-s2-rate-limited", action="store_true")
    parser.add_argument("--extra-evidence")
    parser.add_argument("--repair-pending", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="Ignore cached audit assessments after external raw edits")
    args = parser.parse_args()
    finalize(json.loads(args.config_json), args.stop_current, args.freeze_s2_404, args.extra_evidence, args.repair_pending,
             resume=not args.fresh, freeze_s2_rate_limited=args.freeze_s2_rate_limited)
