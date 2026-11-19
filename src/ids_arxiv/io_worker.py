"""Bounded I/O service. No network APIs; all potentially blocking Drive work stays here."""

import re
import shutil
import uuid
from pathlib import Path

from .checkpoint import EMPTY_SOURCE_STATES, commit_publication, read_json, verified_record
from .isolation import serve
from .storage import atomic_json, sha256_file


def handle(request):
    action = request["action"]
    if action == "owner_snapshot":
        base, owner = Path(request["base"]), request["owner"]
        result = {}
        for key, path in (("closure", base / "closure.json"), ("audit", base / "audit-progress.json"),
                          ("crawl", base / "raw" / f"crawl_summary-{owner}.json")):
            value = read_json(path, {})
            value.pop("records", None)
            value.pop("failed_ids", None)
            result[key] = value
        if not result["crawl"]:
            value = read_json(Path(request["legacy_raw"]) / f"crawl_summary-{owner}.json", {})
            value.pop("failed_ids", None)
            result["legacy_crawl"] = value
        return result
    if action == "cache_catalog":
        root = Path(request["root"]).resolve()
        result = []
        for item in (root / "m1-team-v4/catalog").glob("*.json"):
            row = read_json(item, {})
            if row.get("owner_id") == request["owner"] and row.get("stage") == "full":
                path = Path(row.get("raw_path", "")).resolve()
                if path.is_relative_to(root / "m1-team-v4"):
                    result.append((row.get("updated_at", ""), str(path)))
        return [path for _, path in sorted(result, reverse=True)]
    if action == "import_cache":
        from .cache_migration import import_source_cache
        return import_source_cache(request["source"], request["local"], request["arxiv_id"])
    if action == "read_json":
        return read_json(request["path"], request.get("default"))
    if action == "marker_hash":
        path = Path(request["path"]) / "crawl_status.json"
        return sha256_file(path) if path.is_file() else None
    if action == "legacy_prefix":
        summary = read_json(request["summary"], {})
        count = request["count"]
        prefix = int(summary.get("total_attempted", 0)) if summary.get("selected_publications") == count else 0
        log = Path(request["log"])
        if log.is_file():
            with log.open("rb") as handle:
                handle.seek(max(0, log.stat().st_size - 2 * 1024 * 1024))
                text = handle.read().decode("utf-8", errors="replace")
            for done, total in re.findall(r"Crawl (\d+)/(\d+):", text):
                if int(total) == count:
                    prefix = max(prefix, int(done))
        return min(count, max(0, prefix))
    if action == "stage":
        remote, local = Path(request["remote"]), Path(request["local"])
        local.mkdir(parents=True, exist_ok=True)
        record = read_json(remote / "crawl_status.json", {})
        if record.get("success") and verified_record(remote, record):
            return {"already_committed": True, "record": record}
        # Metadata/references are small. Only copy usable, inventoried versions,
        # and never copy a version already staged locally with matching bytes.
        for name in ("metadata.json", "references.json", "references_all.json", "crawl_status.json"):
            source, target = remote / name, local / name
            if source.is_file() and not target.exists():
                shutil.copy2(source, target)
        from .storage import verify_inventory
        for version in record.get("versions", []):
            target = local / f"v{version['version']}"
            source = remote / target.name
            if not version.get("success"):
                continue
            if version.get("state") in EMPTY_SOURCE_STATES:
                if source.is_dir() and not any(source.iterdir()):
                    target.mkdir(exist_ok=True)
            elif not verify_inventory(target, version.get("files", {})):
                if verify_inventory(source, version.get("files", {})):
                    if target.exists():
                        # Local stale files are retained for audit, not merged.
                        target.rename(target.with_name(target.name + ".stale-" + uuid.uuid4().hex))
                    shutil.copytree(source, target)
        return {"already_committed": False, "record": read_json(local / "crawl_status.json", {})}
    if action == "commit":
        return commit_publication(request["local"], request["remote"], request["record"])
    if action == "write_json":
        atomic_json(Path(request["path"]), request["value"])
        return True
    if action == "copy":
        source, target = Path(request["source"]), Path(request["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and sha256_file(target) == sha256_file(source):
            return True
        temporary = target.with_name(target.name + ".upload")
        shutil.copy2(source, temporary)
        if sha256_file(temporary) != sha256_file(source):
            raise OSError("Copied artifact checksum mismatch")
        temporary.replace(target)
        return True
    raise ValueError("Unsupported I/O action")


if __name__ == "__main__":
    serve(handle)
