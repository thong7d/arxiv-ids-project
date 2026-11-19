"""Durable audit checkpoints for a quiescent corpus, independent of a Colab VM."""

import hashlib
import json
from pathlib import Path

from .storage import utc_now


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


class AuditJournal:
    """Chunk files are durable evidence, not a second raw corpus.

    Resume assumes the input corpus remains frozen. Each reused assessment is
    also bound to its raw commit marker; an operator editing raw bytes outside
    the crawler must request a fresh audit instead of trusting an old receipt.
    """

    def __init__(self, io, directory, context, ids):
        self.io, self.directory = io, Path(directory)
        self.context, self.ids = context, set(ids)
        if len(self.ids) != len(ids):
            raise ValueError("Duplicate audit manifest IDs")
        self.parts, self.rows, self.pending = [], {}, {}

    def load(self):
        index = self.io.call({"action": "read_json", "path": str(self.directory / "index.json"), "default": {}})
        if not index or index.get("context") != self.context:
            return {}
        rows = {}
        parts = index.get("parts", [])
        for part in parts:
            name = part["name"]
            if Path(name).name != name or not name.endswith(".json"):
                raise ValueError("Invalid audit checkpoint path")
            chunk = self.io.call({"action": "read_json", "path": str(self.directory / name), "default": {}})
            if digest(chunk) != part["sha256"] or not isinstance(chunk.get("records"), dict):
                raise ValueError("Audit checkpoint integrity failure")
            for aid, row in chunk["records"].items():
                if aid not in self.ids or row.get("arxiv_id") != aid:
                    raise ValueError("Checkpoint record outside owner manifest")
                rows[aid] = row
        self.parts, self.rows = parts, rows
        return dict(rows)

    def remember(self, row):
        aid = row["arxiv_id"]
        if aid not in self.ids:
            raise ValueError("Audit result outside owner manifest")
        self.rows[aid] = row
        self.pending[aid] = row

    def flush(self):
        if not self.pending:
            return
        chunk = {"records": dict(self.pending)}
        checksum = digest(chunk)
        name = f"part-{len(self.parts):05d}-{checksum[:12]}.json"
        # Commit the chunk first, index last. An interrupted chunk upload cannot
        # advance the acknowledged prefix or discard an earlier checkpoint.
        self.io.call({"action": "write_json", "path": str(self.directory / name), "value": chunk})
        if self.io.call({"action": "read_json", "path": str(self.directory / name), "default": {}}) != chunk:
            raise OSError("Audit checkpoint readback mismatch")
        parts = self.parts + [{"name": name, "sha256": checksum}]
        index = {"context": self.context, "parts": parts, "updated_at": utc_now(), "assessed_count": len(self.rows)}
        self.io.call({"action": "write_json", "path": str(self.directory / "index.json"), "value": index})
        if self.io.call({"action": "read_json", "path": str(self.directory / "index.json"), "default": {}}) != index:
            raise OSError("Audit index readback mismatch")
        self.parts, self.pending = parts, {}
