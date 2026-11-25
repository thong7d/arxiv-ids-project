"""Safe Google Drive M1 cleanup utility (dry-run by default; requires explicit confirmation)."""

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROTECTED_BUNDLE_PREFIXES = {"69413196afff", "3734496d4a7f", "a170ab882d12"}
CANONICAL_OWNERS = ("23120364", "23120358", "23120345")
CANONICAL_CATALOG_FILES = {
    "23120364-23120364-main.json",
    "23120358-23120358-main.json",
    "23120345-23120345-main.json",
}
CONFIRM_TOKEN = "DELETE_M1_CLUTTER"


def check_no_active_workers() -> list[str]:
    res = subprocess.run(
        ["ps", "-eo", "pid,args"], capture_output=True, text=True, check=False
    )
    active = []
    my_pid = str(os.getpid())
    for line in res.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2 or parts[0] == my_pid:
            continue
        cmd = parts[1]
        if any(
            mod in cmd
            for mod in (
                "ids_arxiv.workflow",
                "ids_arxiv.repair",
                "ids_arxiv.team_run",
                "ids_arxiv.finalize",
            )
        ):
            active.append(line.strip())
    return active


def verify_canonical_closures(drive_root: Path) -> dict:
    m1 = drive_root / "m1-team-v4"
    status = {}
    for owner in ("23120364", "23120358"):
        cl_path = m1 / owner / "main" / "full" / owner / "closure.json"
        if not cl_path.is_file():
            raise RuntimeError(f"Missing canonical closure.json for {owner}: {cl_path}")
        cl = json.loads(cl_path.read_text(encoding="utf-8"))
        if not cl.get("operational_closed"):
            raise RuntimeError(f"Canonical owner {owner} is not operational_closed: {cl}")
        if owner == "23120358":
            if (
                cl.get("expected_count") != 5000
                or cl.get("assessed_count") != 5000
                or cl.get("missing_ids") != []
            ):
                raise RuntimeError(f"23120358 closure incomplete: {cl}")
        status[owner] = {
            "operational_closed": cl.get("operational_closed"),
            "counts": cl.get("counts"),
            "audited_at": cl.get("audited_at"),
        }
    cl45_path = m1 / "23120345" / "main" / "full" / "23120345" / "closure.json"
    if cl45_path.is_file():
        cl45 = json.loads(cl45_path.read_text(encoding="utf-8"))
        status["23120345"] = {
            "operational_closed": cl45.get("operational_closed"),
            "counts": cl45.get("counts"),
            "audited_at": cl45.get("audited_at"),
        }
    manifest = drive_root / "m1-final-v3" / "manifests" / "papers.parquet"
    if not manifest.is_file():
        raise RuntimeError(f"Protected manifest missing, aborting: {manifest}")
    return status


def discover_cleanup_targets(drive_root: Path) -> dict[str, list[Path]]:
    drive_root = drive_root.resolve()
    m1 = drive_root / "m1-team-v4"
    categories: dict[str, list[Path]] = {
        "duplicate_23120358_dirs": [],
        "duplicate_catalog_files": [],
        "stale_runtime_dirs": [],
        "conflict_json_files": [],
        "obsolete_code_bundles": [],
        "legacy_root_logs_and_status": [],
        "obsolete_root_dirs": [],
    }

    # 1. Duplicate 23120358 (N) directories under m1-team-v4
    if m1.is_dir():
        for entry in sorted(m1.iterdir(), key=lambda p: p.name):
            if entry.is_dir() and re.fullmatch(r"23120358 \(\d+\)", entry.name):
                categories["duplicate_23120358_dirs"].append(entry)

        # 2. Duplicate conflict files inside m1-team-v4/catalog
        catalog = m1 / "catalog"
        if catalog.is_dir():
            for entry in sorted(catalog.iterdir(), key=lambda p: p.name):
                if (
                    entry.is_file()
                    and entry.name not in CANONICAL_CATALOG_FILES
                    and re.search(r"\(\d+\)\.json$", entry.name)
                ):
                    categories["duplicate_catalog_files"].append(entry)

        # 3. Stale non-main runtime stub under 23120364 (only if no raw/ dir inside)
        for owner in CANONICAL_OWNERS:
            owner_dir = m1 / owner
            if not owner_dir.is_dir():
                continue
            for sub in sorted(owner_dir.iterdir(), key=lambda p: p.name):
                if sub.is_dir() and sub.name != "main":
                    raw_candidates = list(sub.glob("*/*/2312*/raw"))
                    if not raw_candidates:
                        categories["stale_runtime_dirs"].append(sub)
            fbase = owner_dir / "main" / "full" / owner
            if fbase.is_dir():
                for item in sorted(fbase.iterdir(), key=lambda p: p.name):
                    m = re.fullmatch(r"(.+) \(\d+\)(\.json)", item.name)
                    if item.is_file() and m:
                        canonical_file = fbase / f"{m.group(1)}{m.group(2)}"
                        if canonical_file.is_file():
                            categories["conflict_json_files"].append(item)

    # 4. Root-level obsolete bundles, logs, status JSONs, and obsolete dirs
    for item in sorted(drive_root.iterdir(), key=lambda p: p.name):
        name = item.name
        if item.is_file():
            if name.startswith("ids13-code") and name.endswith((".zip", ".sha256")):
                keep = any(prefix in name for prefix in PROTECTED_BUNDLE_PREFIXES)
                if not keep:
                    categories["obsolete_code_bundles"].append(item)
            elif (
                re.fullmatch(r"crawl-.*\.log", name)
                or re.fullmatch(r"m1-agent.*\.log", name)
                or re.fullmatch(r"m1-automation-status.*\.json", name)
                or re.fullmatch(r"m1-launch-status.*\.json", name)
            ):
                categories["legacy_root_logs_and_status"].append(item)
        elif item.is_dir():
            if name == "notebooks" and not any(item.iterdir()):
                categories["obsolete_root_dirs"].append(item)
            elif name == "m1-pilot-v3":
                categories["obsolete_root_dirs"].append(item)

    # Safety assertion: never allow canonical paths in any target list
    protected = {
        (drive_root / "m1-final-v3").resolve(),
        (drive_root / "IDS13_M1_Colab.ipynb").resolve(),
        (m1 / "23120364" / "main").resolve(),
        (m1 / "23120358" / "main").resolve(),
        (m1 / "23120345" / "main").resolve(),
    }
    for cat, paths in categories.items():
        for p in paths:
            rp = p.resolve()
            if not rp.is_relative_to(drive_root):
                raise RuntimeError(f"Unsafe target outside drive_root ({cat}): {rp}")
            for prot in protected:
                if rp == prot or prot.is_relative_to(rp):
                    raise RuntimeError(f"Refusing to touch protected path {prot} via {rp}")
                if rp.is_relative_to(prot) and cat != "conflict_json_files":
                    raise RuntimeError(f"Refusing to touch inside protected path {prot} via {rp}")
    return categories


def delete_single_path(path: Path) -> tuple[str, bool, str]:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)
        return str(path), True, ""
    except OSError as exc:
        return str(path), False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit and clean duplicate 23120358 folders and obsolete M1 files on Google Drive."
    )
    parser.add_argument(
        "--drive-root",
        default="/content/drive/MyDrive/IDS_Nhom13_Corpus_Backup",
        help="Mounted Google Drive shared folder path.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete discovered clutter (default is read-only dry-run).",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Must equal '{CONFIRM_TOKEN}' when --execute is set.",
    )
    parser.add_argument(
        "--sync-notebook",
        type=Path,
        default=None,
        help="Optional path to latest IDS13_M1_Colab.ipynb to update on Drive root.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Parallel I/O threads for Google Drive FUSE deletion.",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("/content/drive_cleanup_report.json"),
        help="Local JSON report output path.",
    )
    args = parser.parse_args()

    drive_root = Path(args.drive_root)
    if not drive_root.is_dir():
        raise SystemExit(f"Drive root not mounted or missing: {drive_root}")

    active = check_no_active_workers()
    if active:
        raise SystemExit(f"Active crawler/repair workers detected; stop first: {active}")

    closures = verify_canonical_closures(drive_root)
    categories = discover_cleanup_targets(drive_root)
    counts = {k: len(v) for k, v in categories.items()}
    total_targets = sum(counts.values())

    report = {
        "mode": "execute" if args.execute else "dry_run",
        "drive_root": str(drive_root),
        "canonical_closures": closures,
        "protected_bundle_prefixes": sorted(PROTECTED_BUNDLE_PREFIXES),
        "counts": counts,
        "total_targets": total_targets,
        "samples": {
            k: [p.name for p in v[:8]] + (["..."] if len(v) > 8 else [])
            for k, v in categories.items()
        },
    }

    print("=== KẾT QUẢ KIỂM TOÁN DỌN DẸP DRIVE M1 ===")
    print(f"Chế độ: {'EXECUTE (XÓA THẬT)' if args.execute else 'DRY-RUN (CHỈ ĐỌC, KHÔNG XÓA)'}")
    print(f"Trạng thái dữ liệu chính tắc đã xác minh: {json.dumps(closures, ensure_ascii=False)}")
    for k, v in counts.items():
        print(f"  - {k}: {v} mục | mẫu: {report['samples'][k]}")
    print(f"Tổng số mục rác/trùng lặp phát hiện: {total_targets}")

    if not args.execute:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Đã lưu báo cáo dry-run tại: {args.report_out}")
        print(
            f"Để thực thi xóa thật sau khi xác nhận, truyền: --execute --confirm {CONFIRM_TOKEN}"
        )
        return 0

    if args.confirm != CONFIRM_TOKEN:
        raise SystemExit(
            f"Confirmation token mismatch: pass --confirm {CONFIRM_TOKEN} to execute deletion."
        )

    all_paths = [p for paths in categories.values() for p in paths]
    started = time.time()
    deleted = 0
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 32))) as pool:
        futures = {pool.submit(delete_single_path, p): p for p in all_paths}
        for idx, fut in enumerate(as_completed(futures), 1):
            target_str, ok, err = fut.result()
            if ok:
                deleted += 1
            else:
                errors.append({"path": target_str, "error": err})
            if idx % 50 == 0 or idx == len(all_paths):
                print(
                    f"  Tiến độ xóa: {idx}/{len(all_paths)} (thành công={deleted}, lỗi={len(errors)}, {time.time() - started:.1f}s)",
                    flush=True,
                )

    if args.sync_notebook is not None:
        if not args.sync_notebook.is_file():
            raise SystemExit(f"Notebook source not found: {args.sync_notebook}")
        dest_nb = drive_root / "IDS13_M1_Colab.ipynb"
        tmp_nb = drive_root / "IDS13_M1_Colab.ipynb.tmp"
        shutil.copy2(args.sync_notebook, tmp_nb)
        tmp_nb.replace(dest_nb)
        report["synced_notebook"] = str(dest_nb)
        print(f"Đã cập nhật IDS13_M1_Colab.ipynb mới nhất lên Drive: {dest_nb}")

    report.update(
        deleted_count=deleted,
        error_count=len(errors),
        errors=errors[:50],
        elapsed_seconds=round(time.time() - started, 2),
    )
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Hoàn tất xóa: {deleted}/{len(all_paths)} mục | lỗi: {len(errors)} | báo cáo: {args.report_out}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
