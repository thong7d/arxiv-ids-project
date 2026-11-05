"""Audit existing records without modifying the corpus or claiming success."""

import argparse
import json
from collections import Counter
from pathlib import Path

from ids_arxiv.storage import atomic_json, utc_now
from ids_arxiv.validator import validate_raw_paper


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/raw"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/audit/legacy_corpus.json"))
    args = parser.parse_args()
    records = []
    for path in sorted(args.input.glob("*/crawl_status.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        records.append(
            {
                "paper": path.parent.name,
                "schema_version": value.get("schema_version", "legacy"),
                "reported_success": value.get("success"),
                "reference_count": value.get("num_references", 0),
                "versions": len(value.get("versions", [])),
                "stale_version_errors": [
                    v["version"]
                    for v in value.get("versions", [])
                    if v.get("success") and v.get("error")
                ],
                "validation": validate_raw_paper(path.parent),
            }
        )
    report = {
        "audited_at": utc_now(),
        "record_count": len(records),
        "schemas": dict(Counter(str(r["schema_version"]) for r in records)),
        "records": records,
        "note": "Legacy success flags do not prove complete version/reference coverage or Colab timing.",
    }
    atomic_json(args.output, report)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "records"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
