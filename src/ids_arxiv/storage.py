"""Atomic checkpoints and content verification shared by crawl stages."""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A failed replace must NEVER remove the last good checkpoint. Separate
    # names also prevent two writers from corrupting each other's temporary file.
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        # The old checkpoint is never unlinked; only this operation's scratch
        # file is discarded after success OR a normal write/replace exception.
        temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_inventory(directory: Path) -> dict:
    return {
        path.relative_to(directory).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(directory.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def verify_inventory(directory: Path, inventory: dict) -> bool:
    if not directory.is_dir() or not inventory:
        return False
    actual = set()
    for item in directory.rglob("*"):
        if item.is_symlink():
            return False
        if item.is_file():
            actual.add(item.relative_to(directory).as_posix())
    if actual != set(inventory):
        return False
    for name, expected in inventory.items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            return False
        if path.stat().st_size != expected["bytes"] or sha256_file(path) != expected["sha256"]:
            return False
    return True
