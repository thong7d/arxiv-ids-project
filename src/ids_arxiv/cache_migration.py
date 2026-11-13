"""Import verified cache bytes into a NEW workspace without modifying the input."""

import shutil
from pathlib import Path

from .checkpoint import EMPTY_SOURCE_STATES, PROTOCOL, SOURCE_POLICY, read_json
from .storage import atomic_json, file_inventory, sha256_file, verify_inventory


def import_source_cache(source, local, aid):
    source, local = Path(source), Path(local)
    if source.resolve() == local.resolve():
        raise ValueError("Cache input and output must be different directories")
    previous = read_json(source / "crawl_status.json", {})
    if previous.get("arxiv_id") != aid or previous.get("schema_version") not in (2, 3, PROTOCOL):
        return {"imported": False}
    marker_before = sha256_file(source / "crawl_status.json")
    local.mkdir(parents=True, exist_ok=True)
    if (local / "crawl_status.json").exists():
        return {"imported": False, "reason": "local_staging_already_exists"}
    versions = []
    for original in previous.get("versions", []):
        version = dict(original)
        number = version["version"]
        if not version.get("success"):
            versions.append(version)
            continue
        old, new = source / f"v{number}", local / f"v{number}"
        if version.get("state") in EMPTY_SOURCE_STATES:
            valid = old.is_dir() and not any(old.iterdir())
        else:
            valid = verify_inventory(old, version.get("files", {}))
        if not valid:
            version.update(success=False, error="Cache inventory verification failed")
            versions.append(version)
            continue
        new.mkdir(parents=True, exist_ok=True)
        for name in version.get("files", {}):
            if Path(name).suffix.lower() not in {".tex", ".bib"}:
                continue
            target = new / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old / name, target)
            if sha256_file(target) != version["files"][name]["sha256"]:
                raise OSError("Cache copy checksum mismatch")
        inventory = file_inventory(new)
        if not inventory and version.get("state") not in EMPTY_SOURCE_STATES:
            version.update(state="non_tex_source", empty_reason="verified_archive_cache_without_tex_or_bib")
        version.update(source_policy=SOURCE_POLICY, files=inventory,
                       stripped_bytes=sum(row["bytes"] for row in inventory.values()))
        version["saved_bytes"] = max(0, version.get("initial_bytes", 0) - version["stripped_bytes"])
        versions.append(version)
    checksums = {}
    for name in ("metadata.json", "references.json", "references_all.json"):
        old = source / name
        if old.is_file() and previous.get("checksums", {}).get(name) == sha256_file(old):
            shutil.copy2(old, local / name)
            checksums[name] = sha256_file(local / name)
            if checksums[name] != previous["checksums"][name]:
                raise OSError("Cache changed while copying metadata/reference snapshot")
    ref_status = dict(previous.get("references_status", {}))
    all_refs = read_json(local / "references_all.json")
    if not isinstance(all_refs, list) or len(all_refs) != ref_status.get("raw_count"):
        ref_status.update(success=False, all_references_retained=False)
    record = {**previous, "schema_version": PROTOCOL, "versions": versions,
              "success": False, "commit_state": "staged", "checksums": checksums,
              "references_status": ref_status, "cache_imported_from": str(source)}
    record.pop("commit_id", None)
    if sha256_file(source / "crawl_status.json") != marker_before:
        raise OSError("Cache commit changed during import; retry the consistent snapshot")
    atomic_json(local / "crawl_status.json", record)
    return {"imported": True, "record": record}
