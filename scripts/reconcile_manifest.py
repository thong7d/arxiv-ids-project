"""Audit search gaps before the first full crawl, preserving the pilot selection."""

import argparse
import json
import shutil
from pathlib import Path

import pandas as pd

from ids_arxiv.discovery import complete_assigned_manifest, load_members
from ids_arxiv.storage import atomic_json, sha256_file, utc_now


def reconcile(root, config):
    final, pilot = root / "m1-final-v3", root / "m1-pilot-v3"
    manifest = final / "manifests/papers.parquet"
    if (final / "campaign.json").exists() or (final / "raw").exists():
        raise ValueError("Refusing to change a manifest after full crawling starts")
    evidence_path = manifest.with_suffix(".json")
    evidence = json.loads(evidence_path.read_text())
    old_hash = sha256_file(manifest)
    if evidence["manifest_sha256"] != old_hash:
        raise ValueError("Existing manifest checksum mismatch")
    old = pd.read_parquet(manifest)
    metadata = json.loads((manifest.parent / "discovery/metadata.json").read_text())
    new, missing = complete_assigned_manifest(load_members(config), metadata)
    old_ids, new_ids = set(old.arxiv_id), set(new.arxiv_id)
    if not old_ids.issubset(new_ids):
        raise ValueError("Reconciliation would remove existing records")
    def selection(frame):
        return frame.groupby("owner_student_id", group_keys=False).head(10).arxiv_id.tolist()
    if selection(old) != selection(new):
        raise ValueError("Reconciliation would change the pilot sample")
    campaign_path = pilot / "campaign.json"
    campaign = json.loads(campaign_path.read_text()) if campaign_path.exists() else None
    if campaign and (campaign["mode"] != "pilot" or campaign["manifest_sha256"] != old_hash):
        raise ValueError("Unexpected pilot campaign fingerprint or mode")
    if old_ids == new_ids:
        print(json.dumps({"state": "already_reconciled", "count": len(new), "search_missing": missing}))
        return
    # Backups are intentionally retained; never overwrite earlier evidence.
    for path in (manifest, evidence_path, campaign_path):
        if path.exists():
            backup = path.with_name(path.name + ".before-gap-audit")
            if backup.exists():
                raise ValueError(f"Backup already exists: {backup}; inspect before retry")
            shutil.copy2(path, backup)
    temporary = manifest.with_suffix(".reconciled.tmp")
    new.to_parquet(temporary, index=False)
    new_hash = sha256_file(temporary)
    migration = {"old_sha256": old_hash, "new_sha256": new_hash, "added_ids": missing,
                 "pilot_selection_unchanged": True, "created_at": utc_now(),
                 "reason": "Retain assigned IDs absent from search; exact-ID crawl still required"}
    atomic_json(final / "manifest-gap-migration.json", migration)
    temporary.replace(manifest)
    evidence.update(manifest_sha256=new_hash, count=len(new), search_missing_ids=missing,
                    by_owner={str(k): int(v) for k, v in new.groupby("owner_student_id").size().items()},
                    gap_audit=migration)
    atomic_json(evidence_path, evidence)
    if campaign:
        campaign.update(manifest_sha256=new_hash, manifest_gap_migration=migration)
        atomic_json(campaign_path, campaign)
    print(json.dumps({"state": "reconciled", "count": len(new), "by_owner": evidence["by_owner"],
                      "search_missing": missing, "pilot_selection_unchanged": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/members.csv"))
    args = parser.parse_args()
    reconcile(args.root, args.config)
