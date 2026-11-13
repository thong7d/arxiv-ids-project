"""Local paper processing plus a supervised, indexed, bounded-I/O coordinator."""

import hashlib
import json
import os
import shutil
import signal
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from ..benchmark import BenchmarkSession
from ..checkpoint import (
    EMPTY_SOURCE_STATES,
    METADATA_QUALITY,
    PROTOCOL,
    SOURCE_POLICY,
    WorkIndex,
    read_json,
    verified_record,
)
from ..discovery import load_members, to_arxiv_id, to_dir_id
from ..isolation import IsolatedService, TaskTimeout
from ..network_schedule import configured_window
from ..profiling import StageClock, profile_paper
from ..runtime import runtime_id
from ..storage import atomic_json, sha256_file, utc_now, verify_inventory
from ..validator import validate_raw_paper
from .reference_dates import ReferenceDates


class PaperTimeoutError(RuntimeError):
    """Compatibility helper. Production uses an external process deadline."""


@contextmanager
def paper_timeout(seconds=180):
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def handler(signum, frame):
        raise PaperTimeoutError(f"Paper crawl exceeded timeout limit of {seconds}s")
    old_handler = signal.signal(signal.SIGALRM, handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def load_json(path, default=None):
    return read_json(path, default)


def valid_version(paper_dir, value, fast=False):
    # fast is kept for API compatibility, but never downgrades integrity checks.
    directory = Path(paper_dir) / f"v{value['version']}"
    if (not value.get("success") or value.get("source_policy") != SOURCE_POLICY
            or any(Path(name).suffix.lower() not in {".tex", ".bib"} for name in value.get("files", {}))):
        return False
    if value.get("state") in EMPTY_SOURCE_STATES:
        return directory.is_dir() and not any(directory.iterdir())
    return verify_inventory(directory, value.get("files", {}))


def enrich_reference_dates(references, crawler, cache_path):
    resolver = getattr(crawler, "reference_dates", None)
    if resolver is None:
        resolver = ReferenceDates(cache_path, getattr(crawler, "metadata_cache", {}))
        crawler.reference_dates = resolver
    return resolver.enrich(references, crawler)


@profile_paper
def crawl_paper(arxiv_id, output_dir, arxiv_crawler, s2_client, resume=True):
    """Process ONLY local disk. Upload is a separate verified transaction."""
    output_dir = Path(output_dir)
    if str(output_dir).replace("\\", "/").startswith("/content/drive/"):
        raise ValueError("Use the supervised coordinator for Drive; paper processing is local only")
    clean_id = to_arxiv_id(arxiv_id)
    paper_dir = output_dir / to_dir_id(clean_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    status_file = paper_dir / "crawl_status.json"
    previous = read_json(status_file, {}) if resume else {}
    trusted = previous.get("schema_version") in (2, 3, PROTOCOL)
    if (resume and previous.get("schema_version") == PROTOCOL and previous.get("success")
            and previous.get("metadata_dates_complete")
            and previous.get("references_status", {}).get("dates_complete")
            and verified_record(paper_dir, previous, require_commit=False)
            and validate_raw_paper(paper_dir)["valid"]):
        return {**previous, "cache_hit": True}

    started = time.monotonic()
    progress = getattr(arxiv_crawler, "progress", lambda *a, **k: None)
    record = {
        "schema_version": PROTOCOL, "arxiv_id": clean_id, "dir_name": paper_dir.name,
        "success": False, "source_success": False, "metadata_dates_complete": False,
        "cache_hit": False, "commit_state": "staged", "started_at": utc_now(),
        "attempt_count": previous.get("attempt_count", 0) + 1,
        "versions": previous.get("versions", []) if trusted else [],
        "references_status": {"state": "pending", "success": False}, "error": None,
    }
    atomic_json(status_file, record)
    progress("metadata", arxiv_id=clean_id)
    metadata = read_json(paper_dir / "metadata.json") if trusted else None
    expected = previous.get("expected_versions") if trusted else None
    cache = getattr(arxiv_crawler, "metadata_cache", {})
    refreshed = cache.get(clean_id, {})
    if (isinstance(cache, dict) and metadata and expected
            and int(refreshed.get("latest_version") or 1) < max(expected)):
        # A stale discovery cache must never reduce the already observed range.
        refreshed = {**refreshed, "title": metadata["title"], "authors": metadata.get("authors", []),
                     "submission_date": metadata["submission_date"], "latest_version": max(expected),
                     "latest_updated": metadata.get("version_dates", {}).get(str(max(expected))),
                     "atom_fetched_epoch": metadata.get("atom_fetched_epoch") or 0,
                     "version_metadata": metadata.get("version_metadata", {})}
        cache[clean_id] = refreshed
    new_revision_seen = bool(expected and int(refreshed.get("latest_version") or 1) > max(expected))
    if (not metadata or not expected or metadata.get("metadata_quality_version") != METADATA_QUALITY
            or not metadata.get("metadata_dates_complete") or not metadata.get("version_metadata_complete") or new_revision_seen):
        fetched = arxiv_crawler.fetch_metadata(clean_id)
        if fetched is None:
            retry_epoch = getattr(arxiv_crawler, "last_retry_epoch", None)
            if not isinstance(retry_epoch, (int, float)):
                retry_epoch = time.time() + 120
            record.update(error=getattr(arxiv_crawler, "last_error", None) or "Metadata unavailable",
                          elapsed_seconds=time.monotonic() - started,
                          next_retry_epoch=retry_epoch)
            atomic_json(status_file, record)
            return record
        metadata, expected = fetched
        atomic_json(paper_dir / "metadata.json", metadata)
    record["expected_versions"] = expected
    record["metadata_dates_complete"] = bool(metadata.get("metadata_dates_complete"))
    record["metadata_versions_complete"] = bool(metadata.get("version_metadata_complete"))
    versions = {value["version"]: value for value in record["versions"]}
    for version in expected:
        old = versions.get(version)
        if resume and old and valid_version(paper_dir, old):
            continue
        if old and old.get("next_retry_epoch", 0) > time.time():
            continue
        progress("download_source", arxiv_id=clean_id, version=version)
        versions[version] = arxiv_crawler.download_and_extract_version(
            clean_id, version, paper_dir / f"v{version}")
        record["versions"] = [versions[v] for v in expected if v in versions]
        atomic_json(status_file, record)
    record["versions"] = [versions[v] for v in expected if v in versions]
    record["source_success"] = bool(expected) and all(
        v in versions and valid_version(paper_dir, versions[v]) for v in expected)

    progress("references", arxiv_id=clean_id)
    refs_path = paper_dir / "references.json"
    all_refs_path = paper_dir / "references_all.json"
    old_ref_status = previous.get("references_status", {}) if trusted else {}
    # A schema upgrade may require fetching ALL S2 references again, but it
    # need not discard submission dates already proven against arXiv.
    if (trusted and refs_path.is_file() and previous.get("checksums", {}).get("references.json") == sha256_file(refs_path)):
        resolver = getattr(arxiv_crawler, "reference_dates", None)
        if resolver is None:
            resolver = ReferenceDates(output_dir.parent / "reference-dates.json", getattr(arxiv_crawler, "metadata_cache", {}))
            arxiv_crawler.reference_dates = resolver
        resolver.remember(read_json(refs_path, {}))
    if (resume and old_ref_status.get("success") and refs_path.is_file()
            and old_ref_status.get("all_references_retained") and all_refs_path.is_file()
            and previous.get("checksums", {}).get("references_all.json") == sha256_file(all_refs_path)
            and previous.get("checksums", {}).get("references.json") == sha256_file(refs_path)):
        references = read_json(refs_path, {})
        all_references = read_json(all_refs_path, [])
        ref_status = old_ref_status.copy()
    else:
        references = s2_client.get_paper_references(clean_id)
        all_references = s2_client.last_all_references
        ref_status = s2_client.last_status.copy()
    if not isinstance(all_references, list):
        all_references = []
        ref_status["all_references_retained"] = False
    if ref_status.get("all_references_retained") and len(all_references) != ref_status.get("raw_count"):
        ref_status.update(success=False, all_references_retained=False, error="Full reference snapshot count mismatch")
    progress("reference_dates", arxiv_id=clean_id)
    dates_complete = (enrich_reference_dates(
        references, arxiv_crawler, output_dir.parent / "reference-dates.json")
        if ref_status.get("success") else False)
    ref_status["dates_complete"] = dates_complete
    atomic_json(refs_path, references)
    atomic_json(all_refs_path, all_references)
    record["references_status"] = ref_status
    record.update(
        num_references=len(references),
        num_references_all=len(all_references),
        num_references_arxiv=len(references),
        total_initial_bytes=sum(v.get("initial_bytes", 0) for v in record["versions"]),
        total_stripped_bytes=sum(v.get("stripped_bytes", 0) for v in record["versions"]),
        total_saved_bytes=sum(v.get("saved_bytes", 0) for v in record["versions"]),
        checksums={name: sha256_file(paper_dir / name) for name in ("metadata.json", "references.json", "references_all.json")},
        references_scope="publication_snapshot_shared_across_versions",
        reference_snapshot_versions=expected,
    )
    progress("validate_local", arxiv_id=clean_id)
    validation = validate_raw_paper(paper_dir)
    record["validation"] = validation
    record["success"] = bool(record["source_success"] and record["metadata_dates_complete"] and record["metadata_versions_complete"]
                             and ref_status.get("success") and ref_status.get("all_references_retained")
                             and dates_complete and validation["valid"])
    # A 24-hour source cooldown must not postpone a repairable reference/date
    # component for 24 hours too. Each completed component is still reused.
    next_dates = [v.get("next_retry_epoch") or time.time() + 60
                  for v in record["versions"] if not v.get("success")]
    arxiv_retry = time.time() + 120
    window = configured_window()
    if window and not window.status()["allowed"]:
        arxiv_retry = window.status()["next_epoch"]
    if not ref_status.get("success"):
        next_dates.append(ref_status.get("next_retry_epoch") or time.time() + 60)
    elif not dates_complete:
        next_dates.append(arxiv_retry)
    if not record["metadata_dates_complete"] or not record["metadata_versions_complete"]:
        next_dates.append(arxiv_retry)
    record.update(ended_at=utc_now(), elapsed_seconds=time.monotonic() - started,
                  next_retry_epoch=min(next_dates, default=0))
    if not record["success"]:
        record["error"] = "Incomplete sources, version dates, references or reference dates; see component states"
    atomic_json(status_file, record)
    progress("staged", arxiv_id=clean_id)
    return record


def run_crawling_pipeline(
    manifest_path, output_dir, limit=None, pilot_mode=False, members_config=None,
    resume=True, student_id=None, max_seconds=None, paper_seconds=900, io_seconds=120,
    expected_manifest_hash=None,
    source_cache_dirs=(), campaign_mode=None, work_namespace=None,
):
    """Keep a durable local ledger, schedule unseen work first, isolate FUSE and API work.

    A completion index skips already committed v3 papers; legacy v2 papers are
    explicitly queued for semantic/integrity audit, not declared newly verified.
    """
    manifest_path, output_dir = Path(manifest_path), Path(output_dir)
    scope = str(student_id or ("pilot" if pilot_mode else "group"))
    if work_namespace not in (None, "probe"):
        raise ValueError("Unknown work namespace")
    if work_namespace:
        scope += "-" + work_namespace
    key = hashlib.sha256(str(output_dir).encode()).hexdigest()[:16]
    local_root = Path(tempfile.gettempdir()) / "ids13-work" / runtime_id() / key / scope
    local_root.mkdir(parents=True, exist_ok=True)
    state_dir = Path(os.getenv("IDS_LOCAL_STATE_DIR", str(local_root / "control")))
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "progress.json"
    state = {"runtime_id": runtime_id(), "stage": "prepare", "state": "running", "student_id": student_id}
    last_heartbeat = [0.0]
    benchmark_box = [None]
    event_offset = [0]
    event_path = local_root / "http-events.jsonl"
    # Retained local journals belong to earlier measured sessions.
    event_offset[0] = event_path.stat().st_size if event_path.exists() else 0

    def heartbeat(force=False):
        now = time.monotonic()
        if force or now - last_heartbeat[0] >= 1:
            state["heartbeat_epoch"] = time.time()
            state["heartbeat_at"] = utc_now()
            activity = read_json(local_root / "activity.json", {})
            if activity and state.get("stage") == "paper":
                state["paper_activity"] = activity
            atomic_json(state_path, state)
            last_heartbeat[0] = now
        measured = benchmark_box[0]
        if measured and event_path.exists():
            with event_path.open("rb") as handle:
                handle.seek(event_offset[0])
                while line := handle.readline():
                    if not line.endswith(b"\n"):
                        break
                    measured.event(json.loads(line))
                    event_offset[0] = handle.tell()

    environment = dict(os.environ)
    source_root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    with IsolatedService("ids_arxiv.io_worker", io_seconds, heartbeat, environment) as io:
        local_manifest = local_root / "papers.parquet"
        io.call({"action": "copy", "source": str(manifest_path), "target": str(local_manifest)})
        if expected_manifest_hash and sha256_file(local_manifest) != expected_manifest_hash:
            raise ValueError("Manifest checksum/provenance mismatch")
        frame = pd.read_parquet(local_manifest)
        if student_id:
            frame = frame[frame.owner_student_id.astype(str) == str(student_id)]
        if pilot_mode:
            frame = frame.groupby("owner_student_id", group_keys=False).head(10)
        if limit is not None:
            frame = frame.head(limit)
        if frame.empty:
            return {"selected_publications": 0, "total_attempted": 0, "success_count": 0}
        if members_config:
            members = load_members(Path(members_config))
            for row in frame.itertuples():
                if not any(m.student_id == str(row.owner_student_id) and m.contains(row.arxiv_id) for m in members):
                    raise ValueError(f"Invalid manifest ownership: {row.arxiv_id}")
        fingerprint = sha256_file(local_manifest)
        campaign_path = output_dir.parent / "campaign.json"
        campaign = io.call({"action": "read_json", "path": str(campaign_path), "default": {}})
        if campaign and not resume:
            raise ValueError("Cold benchmark requires a fresh campaign directory; existing data is preserved")
        if campaign and campaign["manifest_sha256"] != fingerprint:
            raise ValueError("Campaign manifest changed; refusing incompatible resume")
        if campaign_mode not in (None, "full"):
            raise ValueError("Unknown campaign mode")
        if not campaign:
            campaign = {"campaign_id": output_dir.parent.name, "manifest_sha256": fingerprint,
                        "started_at": utc_now(), "mode": campaign_mode or ("pilot" if pilot_mode or limit else "full")}
            io.call({"action": "write_json", "path": str(campaign_path), "value": campaign})
        if campaign["mode"] == "pilot" and not (pilot_mode or limit):
            raise ValueError("A pilot directory cannot be used as a cold-start full benchmark")
        index = WorkIndex(local_root / "work.sqlite", fingerprint, scope)
        snapshot_path = output_dir.parent / "state-v3" / f"index-{scope}.json"
        saved = io.call({"action": "read_json", "path": str(snapshot_path), "default": None})
        if saved and not index.snapshot()["rows"]:
            index.restore(saved)
        ids = frame.arxiv_id.tolist()
        prefix = 0
        legacy_ids = []
        if resume and not index.snapshot()["rows"]:
            for owner, owner_frame in frame.groupby("owner_student_id", sort=False):
                count = len(owner_frame)
                cursor = io.call({"action": "legacy_prefix", "summary": str(output_dir / f"crawl_summary-{owner}.json"),
                                  "log": str(output_dir.parent.parent / f"m1-agent-{owner}.log"), "count": count})
                legacy_ids.extend(owner_frame.arxiv_id.tolist()[:cursor])
            prefix = len(legacy_ids)
        index.seed(ids, legacy_ids=legacy_ids)
        metadata_path = local_root / "discovery-metadata.json"
        try:
            io.call({"action": "copy", "source": str(manifest_path.parent / "discovery/metadata.json"),
                     "target": str(metadata_path)})
        except (RuntimeError, TaskTimeout):
            atomic_json(metadata_path, {})
        summary_files = [output_dir / f"crawl_summary-{scope}.json"]
        if student_id is None:
            summary_files.append(output_dir / "crawl_summary.json")
        task_count = cache_hits = consecutive_io_failures = 0
        started = time.monotonic()
        last_snapshot = last_mirror = 0.0
        summary = {}
        with BenchmarkSession(output_dir.parent / "benchmark", campaign=campaign["campaign_id"]) as measured:
            measured.record.update(student_id=student_id, resume=resume,
                                   selected_publications=len(ids), legacy_prefix=prefix,
                                   benchmark_mode="resume_recovery" if resume else "cold_requested")
            benchmark_box[0] = measured
            with IsolatedService("ids_arxiv.crawler.paper_worker", paper_seconds, heartbeat, environment) as papers:
                def init_service():
                    if papers.process is None or papers.process.poll() is not None:
                        papers.call({"action": "init", "root": str(local_root), "metadata": str(metadata_path)})

                def persist(force=False):
                    nonlocal last_snapshot, last_mirror
                    now = time.monotonic()
                    atomic_json(local_root / "summary.json", summary)
                    if force or now - last_snapshot >= 300 or task_count % 50 == 0:
                        try:
                            io.call({"action": "write_json", "path": str(snapshot_path), "value": index.snapshot()})
                            for path in summary_files:
                                io.call({"action": "write_json", "path": str(path), "value": summary})
                            last_snapshot = now
                        except (RuntimeError, TaskTimeout) as error:
                            state["checkpoint_error"] = str(error)
                    if force or now - last_mirror >= 60:
                        measured.mirror(io)
                        try:
                            control_remote = output_dir.parent / "control-v3" / scope
                            io.call({"action": "write_json", "path": str(control_remote / "progress.json"), "value": dict(state)})
                            if (state_dir / "worker.log").is_file():
                                io.call({"action": "copy", "source": str(state_dir / "worker.log"),
                                         "target": str(control_remote / "worker.log")})
                        except (RuntimeError, TaskTimeout, OSError) as error:
                            state["control_mirror_error"] = str(error)
                        last_mirror = now

                try:
                    while max_seconds is None or time.monotonic() - started < max_seconds:
                        due = index.batch()
                        if not due:
                            next_due = index.next_due()
                            if next_due is None:
                                break
                            wait = next_due - time.time()
                            remaining = float("inf") if max_seconds is None else max_seconds - (time.monotonic() - started)
                            if wait > min(120, remaining):
                                state["next_retry_epoch"] = next_due
                                break
                            state.update(stage="retry_wait", next_retry_epoch=next_due)
                            heartbeat(True)
                            time.sleep(min(1, max(0.05, wait)))
                            continue
                        metadata_prefetched = False
                        for position, aid in enumerate(due):
                            if max_seconds is not None and time.monotonic() - started >= max_seconds:
                                break
                            if shutil.disk_usage(local_root).free < 2 * 1024**3:
                                raise RuntimeError("Local spool has less than 2 GiB free; preserve pending uploads and free space safely")
                            attempt_clock = StageClock("cache_check_import")
                            local_paper = local_root / "raw" / to_dir_id(aid)
                            remote_paper = output_dir / to_dir_id(aid)
                            state.update(stage="check_cache", current_paper=aid,
                                         stage_deadline_epoch=time.time() + io_seconds)
                            heartbeat(True)
                            try:
                                staged = io.call({"action": "stage", "remote": str(remote_paper), "local": str(local_paper)})
                                if staged.get("already_committed"):
                                    result = {**staged["record"], "cache_hit": True, "paper_stage_seconds": {}}
                                else:
                                    if not (local_paper / "crawl_status.json").exists():
                                        for cache in source_cache_dirs:
                                            imported = io.call({"action": "import_cache", "arxiv_id": aid,
                                                                "source": str(Path(cache) / to_dir_id(aid)),
                                                                "local": str(local_paper)})
                                            if imported.get("imported"):
                                                staged["record"] = imported["record"]
                                                break
                                    init_service()
                                    if not metadata_prefetched:
                                        attempt_clock.switch("metadata_batch_shared")
                                        state.update(stage="metadata_batch", stage_deadline_epoch=time.time() + paper_seconds)
                                        heartbeat(True)
                                        papers.call({"action": "metadata_batch", "ids": due[position:]})
                                        metadata_prefetched = True
                                    attempt_clock.switch("s2_prefetch")
                                    local_record = staged.get("record", {})
                                    ref_file = local_paper / "references.json"
                                    cached_refs = (local_record.get("references_status", {}).get("success")
                                                   and ref_file.is_file()
                                                   and local_record.get("checksums", {}).get("references.json") == sha256_file(ref_file))
                                    if not cached_refs:
                                        papers.call({"action": "prefetch", "ids": due[position:position + 20]})
                                    state.update(stage="paper", stage_deadline_epoch=time.time() + paper_seconds)
                                    attempt_clock.switch("paper_worker")
                                    heartbeat(True)
                                    result = papers.call({"action": "paper", "arxiv_id": aid,
                                                          "output": str(local_root / "raw"), "resume": resume})
                                    state.update(stage="commit", stage_deadline_epoch=time.time() + io_seconds)
                                    attempt_clock.switch("drive_commit")
                                    heartbeat(True)
                                    result = io.call({"action": "commit", "local": str(local_paper),
                                                      "remote": str(remote_paper), "record": result})
                                index.update(aid, result, next_at=max(time.time() + 60, result.get("next_retry_epoch", 0)))
                                cache_hits += int(result.get("cache_hit", False))
                                consecutive_io_failures = 0
                            except (RuntimeError, TaskTimeout, OSError) as error:
                                failure_state = "upload_pending" if state.get("stage") == "commit" else "retry"
                                result = {"arxiv_id": aid, "success": False, "commit_state": failure_state,
                                          "error": f"{type(error).__name__}: {error}",
                                          "local_staging": str(local_paper)}
                                index.update(aid, result, time.time() + 120, state=failure_state)
                                if state.get("stage") in {"check_cache", "commit"}:
                                    consecutive_io_failures += 1
                            task_count += 1
                            attempt_clock.switch("checkpoint")
                            heartbeat()
                            summary = {**index.stats(), "campaign_id": campaign["campaign_id"],
                                       "protocol_version": PROTOCOL, "student_id": student_id,
                                       "attempts_this_session": task_count, "cache_hits": cache_hits,
                                       "session_id": measured.session_id, "updated_at": utc_now(),
                                       "elapsed_seconds": time.monotonic() - started,
                                       "next_retry_epoch": index.next_due()}
                            state.update(summary={k: v for k, v in summary.items() if k != "failed_ids"},
                                         last_completed_at=utc_now())
                            heartbeat(True)
                            persist()
                            measured.event({"kind": "paper_attempt", "timestamp": utc_now(), "arxiv_id": aid,
                                            "success": bool(result.get("success")), "cache_hit": bool(result.get("cache_hit")),
                                            "stage_seconds": attempt_clock.finish(),
                                            "paper_stage_seconds": result.get("paper_stage_seconds", {}),
                                            "elapsed_seconds": time.monotonic() - attempt_clock.started})
                            if task_count % 10 == 0 or not result.get("success"):
                                print(f"Crawl v3 tasks={task_count} verified={summary['success_count']}/{len(ids)} "
                                      f"pending={summary['pending_count']} legacy_audit={summary['legacy_pending_audit']} "
                                      f"last={aid}", flush=True)
                            if consecutive_io_failures >= 3:
                                raise RuntimeError("Three consecutive Drive I/O failures; stop safely instead of spawning more retries")
                        if index.stats()["success_count"] == len(ids):
                            break
                    state["state"] = "completed" if index.stats()["success_count"] == len(ids) else "needs_recovery"
                except KeyboardInterrupt:
                    state.update(state="interrupted", reason="SIGINT")
                    raise
                except BaseException as error:
                    state.update(state="failed", error=type(error).__name__)
                    raise
                finally:
                    heartbeat(True)
                    summary = {**index.stats(), "campaign_id": campaign["campaign_id"],
                               "protocol_version": PROTOCOL, "student_id": student_id,
                               "attempts_this_session": task_count, "cache_hits": cache_hits,
                               "session_id": measured.session_id, "updated_at": utc_now(),
                               "elapsed_seconds": time.monotonic() - started, "state": state["state"],
                               "next_retry_epoch": index.next_due()}
                    persist(True)
                    index.close()
            # The sampler marks the terminal state on context exit; mirror again below.
        measured.mirror(io)
        return summary
