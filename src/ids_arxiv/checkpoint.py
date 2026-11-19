"""Verified publication commits and a small durable work index, independent of Drive scans."""

import json
import shutil
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

from .discovery import to_dir_id
from .storage import atomic_json, sha256_file, utc_now, verify_inventory

PROTOCOL = 4
METADATA_QUALITY = 3
SOURCE_POLICY = "original_tex_bib_only_v1"
EMPTY_SOURCE_STATES = {"pdf_only", "non_tex_source"}


def reference_snapshot_consistent(references, all_references):
    if not isinstance(references, dict) or not isinstance(all_references, list):
        return False
    expected = {}
    for row in all_references:
        if not isinstance(row, dict):
            continue
        external = row.get("externalIds") or {}
        if not isinstance(external, dict):
            return False
        aid = external.get("ArXiv") or external.get("arxiv")
        if aid:
            expected[to_dir_id(aid)] = row.get("paperId") or ""
    return set(expected) == set(references) and all(
        isinstance(references[aid], dict) and references[aid].get("s2_id") == sid for aid, sid in expected.items())


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def verified_record(directory, record, require_quality=True, require_commit=True):
    directory = Path(directory)
    required_files = {"metadata.json", "references.json"}
    if require_quality:
        required_files.add("references_all.json")
    if not record or not required_files.issubset(record.get("checksums", {})):
        return False
    if require_quality and (record.get("schema_version") != PROTOCOL
                            or (require_commit and not record.get("commit_id"))
                            or not record.get("metadata_dates_complete")
                            or not record.get("references_status", {}).get("success")
                            or not record.get("references_status", {}).get("dates_complete")
                            or not record.get("references_status", {}).get("all_references_retained")):
        return False
    for name, digest in record["checksums"].items():
        path = directory / name
        if not path.is_file() or sha256_file(path) != digest:
            return False
    expected = record.get("expected_versions", [])
    versions = {v["version"]: v for v in record.get("versions", [])}
    if not expected or any(v not in versions for v in expected):
        return False
    if expected != list(range(1, max(expected) + 1)):
        return False
    if require_quality:
        metadata = read_json(directory / "metadata.json", {})
        references = read_json(directory / "references.json", {})
        all_references = read_json(directory / "references_all.json")
        if (not isinstance(all_references, list)
                or len(all_references) != record.get("references_status", {}).get("raw_count")
                or not reference_snapshot_consistent(references, all_references)):
            return False
        if (metadata.get("metadata_quality_version") != METADATA_QUALITY or not metadata.get("metadata_dates_complete")
                or not metadata.get("version_metadata_complete")
                or any(str(v) not in metadata.get("version_metadata", {}) for v in expected)):
            return False
        try:
            for version in expected:
                datetime.fromisoformat(metadata["version_dates"][str(version)].replace("Z", "+00:00"))
                if metadata["version_date_sources"][str(version)] not in {
                    "oai_arXivRaw", "arxiv_atom_published", "arxiv_atom_updated", "arxiv_atom_version_updated"
                }:
                    return False
            for reference in references.values():
                datetime.fromisoformat(reference["submission_date"].replace("Z", "+00:00"))
                if not reference.get("s2_id") or reference.get("date_source") not in {"arxiv_atom", "arxiv_atom_published"}:
                    return False
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
    for version in expected:
        status = versions[version]
        if not status.get("success"):
            return False
        if require_quality and (status.get("source_policy") != SOURCE_POLICY or any(
            Path(name).suffix.lower() not in {".tex", ".bib"} for name in status.get("files", {})
        )):
            return False
        target = directory / f"v{version}"
        if status.get("state") in EMPTY_SOURCE_STATES:
            if not target.is_dir() or any(target.iterdir()):
                return False
        elif not verify_inventory(target, status.get("files", {})):
            return False
    return True


def commit_publication(local, target, record):
    """Write the completion marker LAST, verify uploads, retain local files on failure.

    Old version directories are renamed to recoverable backups, never recursively
    deleted here. A failed upload therefore cannot destroy the last good source.
    """
    local, target = Path(local), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    previous = read_json(target / "crawl_status.json", {})
    if previous.get("success") and not record.get("success"):
        raise ValueError("Refusing to replace a successful publication with an incomplete attempt")
    commit_id = uuid.uuid4().hex
    for version in record.get("versions", []):
        if not version.get("success"):
            continue
        number = version["version"]
        source, destination = local / f"v{number}", target / f"v{number}"
        old = next((v for v in previous.get("versions", []) if v["version"] == number), {})
        # Reuse versions only after checking the persisted bytes, not an old flag.
        if version.get("success") and old.get("files") == version.get("files"):
            if version.get("state") not in EMPTY_SOURCE_STATES and verify_inventory(destination, version.get("files", {})):
                continue
            if version.get("state") in EMPTY_SOURCE_STATES and destination.is_dir() and not any(destination.iterdir()):
                continue
        if not source.is_dir():
            # A partial/legacy record may have no local version. Its old copy
            # stays untouched and the record remains incomplete.
            continue
        incoming = target / f".incoming-v{number}-{commit_id}"
        shutil.copytree(source, incoming)
        if version.get("success") and version.get("state") not in EMPTY_SOURCE_STATES:
            if not verify_inventory(incoming, version.get("files", {})):
                raise OSError(f"Uploaded v{number} failed checksum verification")
        if destination.exists():
            destination.rename(target / f".previous-v{number}-{commit_id}")
        incoming.rename(destination)
    for name in ("metadata.json", "references.json", "references_all.json"):
        source = local / name
        if source.is_file():
            if (target / name).is_file() and sha256_file(target / name) == sha256_file(source):
                continue  # Identical verified payload: no upload or backup churn.
            incoming = target / f".{name}.{commit_id}.upload"
            shutil.copy2(source, incoming)
            if sha256_file(incoming) != sha256_file(source):
                raise OSError(f"Upload checksum mismatch: {name}")
            if (target / name).is_file():
                shutil.copy2(target / name, target / f".previous-{name}-{commit_id}")
            incoming.replace(target / name)
    committed = {**record, "commit_id": commit_id, "committed_at": utc_now(),
                 "commit_state": "committed"}
    if committed.get("success") and not verified_record(target, committed):
        raise OSError("Publication could not be verified at destination; no success marker written")
    # Preserve the last complete checkpoint as recoverable evidence.
    status = target / "crawl_status.json"
    if status.exists() and previous.get("success"):
        shutil.copy2(status, target / f".previous-status-{commit_id}.json")
    atomic_json(status, committed)
    if read_json(status) != committed:
        raise OSError("Commit marker readback failed")
    # Delete only backups created by THIS acknowledged transaction. Failure
    # paths retain the last good data; never sweep old user/corpus directories.
    for path in target.glob(f".previous-*-{commit_id}*"):
        if path.parent.resolve() != target.resolve():
            raise ValueError("Unexpected transaction cleanup target")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return committed


class WorkIndex:
    """SQLite is LOCAL only. Portable snapshots are bound to manifest and owner."""
    def __init__(self, path, fingerprint, owner="group"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS work (id TEXT PRIMARY KEY, ordinal INTEGER, state TEXT, next_at REAL, attempts INTEGER, result TEXT)")
        for key, value in {"manifest_sha256": fingerprint, "owner": str(owner), "protocol": str(PROTOCOL)}.items():
            old = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            if old and old[0] != value:
                raise ValueError(f"Work index {key} mismatch")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES (?,?)", (key, value))
        self.db.commit()

    def seed(self, ids, legacy_prefix=0, legacy_ids=()):
        legacy_ids = set(legacy_ids)
        with self.db:
            for ordinal, aid in enumerate(ids):
                state = "legacy_audit" if ordinal < legacy_prefix or aid in legacy_ids else "pending"
                self.db.execute("INSERT OR IGNORE INTO work VALUES (?,?,?,?,?,?)",
                                (aid, ordinal, state, 0.0, 0, "{}"))

    def pending(self, now=None):
        now = time.time() if now is None else now
        rows = self.db.execute(
            "SELECT id FROM work WHERE state NOT IN ('complete','quarantined') AND next_at<=? "
            "ORDER BY CASE state WHEN 'pending' THEN 0 WHEN 'upload_pending' THEN 1 WHEN 'retry' THEN 2 ELSE 3 END, ordinal", (now,))
        return [r[0] for r in rows]

    def batch(self, size=40, now=None):
        """Fair bounded batches: unseen, retry/upload and legacy all progress."""
        now = time.time() if now is None else now
        rows = self.db.execute(
            "SELECT id,state FROM work WHERE state NOT IN ('complete','quarantined') "
            "AND next_at<=? ORDER BY next_at,ordinal", (now,))
        buckets = {"pending": [], "retry": [], "legacy_audit": []}
        for aid, state in rows:
            buckets[state if state in buckets else "retry"].append(aid)
        offsets = {k: 0 for k in buckets}
        result = []
        while len(result) < size:
            before = len(result)
            for key in ("pending", "pending", "retry", "legacy_audit"):
                offset = offsets[key]
                if offset < len(buckets[key]) and len(result) < size:
                    result.append(buckets[key][offset])
                    offsets[key] += 1
            if len(result) == before:
                break
        return result

    def update(self, aid, result, next_at=0, state=None):
        if result.get("success") and result.get("commit_state") != "committed":
            raise ValueError("Cannot mark an uncommitted publication complete")
        state = state or ("complete" if result.get("success") else "retry")
        # The index is a completion ledger, not a duplicate of every file's
        # inventory. Keep portable snapshots small even for 15,000 papers.
        result = {k: v for k, v in result.items() if k in {
            "arxiv_id", "success", "source_success", "metadata_dates_complete", "references_status",
            "commit_state", "commit_id", "error", "next_retry_epoch", "elapsed_seconds",
            "total_initial_bytes", "total_stripped_bytes", "num_references", "local_staging",
            "bounded_network_passes", "automatic_stop_reason",
        }}
        with self.db:
            self.db.execute("UPDATE work SET state=?, next_at=?, attempts=attempts+1, result=? WHERE id=?",
                            (state, next_at, json.dumps(result, ensure_ascii=False), aid))

    def result(self, aid):
        row = self.db.execute("SELECT result FROM work WHERE id=?", (aid,)).fetchone()
        return json.loads(row[0]) if row else {}

    def stats(self):
        rows = list(self.db.execute("SELECT state, result FROM work"))
        results = [json.loads(r[1]) for r in rows]
        return {"selected_publications": len(rows),
                "total_attempted": sum(bool(r) for r in results),
                "success_count": sum(r[0] == "complete" for r in rows),
                "source_success_count": sum(bool(r.get("source_success")) for r in results),
                "reference_success_count": sum(bool(r.get("references_status", {}).get("success")) for r in results),
                "pending_count": sum(r[0] not in ("complete", "quarantined") for r in rows),
                "quarantined_count": sum(r[0] == "quarantined" for r in rows),
                "upload_pending_count": sum(r[0] == "upload_pending" for r in rows),
                "uncommitted_attempt_count": sum(bool(r) and r.get("commit_state") != "committed" for r in results),
                "legacy_pending_audit": sum(r[0] == "legacy_audit" for r in rows),
                "failed_ids": [r.get("arxiv_id") for r in results if r and not r.get("success")]}

    def next_due(self):
        row = self.db.execute("SELECT MIN(next_at) FROM work WHERE state NOT IN ('complete','quarantined')").fetchone()
        return row[0] if row and row[0] is not None else None

    def snapshot(self):
        return {"meta": dict(self.db.execute("SELECT key,value FROM meta")),
                "rows": list(self.db.execute("SELECT * FROM work"))}

    def restore(self, value):
        if value.get("meta") != dict(self.db.execute("SELECT key,value FROM meta")):
            raise ValueError("Snapshot belongs to another manifest/owner/protocol")
        with self.db:
            for row in value.get("rows", []):
                self.db.execute("INSERT OR IGNORE INTO work VALUES (?,?,?,?,?,?)", tuple(row))

    def close(self):
        self.db.close()
