"""Publish Group 13 report to Hugging Face Spaces (static) or personal Parquet Dataset to HF Hub."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ids_arxiv.exporter import export_student_dataset
from ids_arxiv.validator import validate_parquet_tables


def resolve_hf_token() -> str:
    token = os.environ.get("HF_TOKEN", "").strip()
    if token:
        return token
    try:
        from google.colab import userdata  # type: ignore[import-not-found]

        token = (userdata.get("HF_TOKEN") or "").strip()
    except Exception:
        token = ""
    if not token:
        raise RuntimeError(
            "Missing HF_TOKEN. Set HF_TOKEN in Colab Secrets or environment variables (never hardcode in code)."
        )
    return token


def build_static_space_bundle(
    project_root: Path,
    stage_dir: Path,
    snapshot_path: Path | None = None,
    space_title: str = "IDS Nhom 13 - arXiv Pipeline Report",
) -> Path:
    stage_dir.mkdir(parents=True, exist_ok=True)
    html_dir = project_root / "book" / "_build" / "html"
    if not (html_dir / "index.html").is_file():
        env = dict(os.environ)
        if snapshot_path is not None and snapshot_path.is_file():
            env["IDS_M1_REPORT_SNAPSHOT"] = str(snapshot_path.resolve())
        subprocess.run(
            [
                sys.executable,
                "-m",
                "jupyter_book",
                "build",
                str(project_root / "book"),
                "--all",
                "--keep-going",
            ],
            check=True,
            env=env,
        )
    if not (html_dir / "index.html").is_file():
        raise RuntimeError(f"Compiled book HTML not found at {html_dir}")

    for child in stage_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(html_dir, stage_dir, dirs_exist_ok=True)

    space_readme = (
        "---\n"
        f"title: {space_title}\n"
        "emoji: 📚\n"
        "colorFrom: blue\n"
        "colorTo: indigo\n"
        "sdk: static\n"
        "app_file: index.html\n"
        "pinned: false\n"
        "---\n\n"
        "# Báo cáo Đồ án Nhập môn Khoa học Dữ liệu — Nhóm 13 (FIT - HCMUS)\n\n"
        "- **Thành viên:** Phạm Minh Thông, Nguyễn Tiến Thành, Nguyễn Trịnh Quang\n"
        "- **GitHub Repository:** https://github.com/thong7d/arxiv-ids-project\n"
        "- **GitHub Pages:** https://thong7d.github.io/arxiv-ids-project/\n"
    )
    (stage_dir / "README.md").write_text(space_readme, encoding="utf-8")
    return stage_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and upload Hugging Face Static Space (report) or personal Hugging Face Dataset (6 Parquet tables)."
    )
    parser.add_argument(
        "--mode",
        choices=("space", "dataset"),
        required=True,
        help="'space' uploads compiled Jupyter Book as a Static HF Space; 'dataset' exports & uploads 6 Parquet tables.",
    )
    parser.add_argument(
        "--repo-id",
        required=True,
        help="Target Hugging Face repo_id, e.g. '<hf_username>/ids-nhom13-book' or '<hf_username>/ids-arxiv-23120364'.",
    )
    parser.add_argument(
        "--student-id",
        choices=("23120364", "23120358", "23120345"),
        default=None,
        help="Required when --mode=dataset.",
    )
    parser.add_argument(
        "--drive-root",
        type=Path,
        default=Path("/content/drive/MyDrive/IDS_Nhom13_Corpus_Backup"),
        help="Shared Google Drive root when exporting directly from Colab.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Explicit raw directory override (defaults to m1-team-v4/<student_id>/main/full/<student_id>/raw).",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=None,
        help="Optional processed M2 directory.",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        default=None,
        help="Optional predictions Parquet file from M3.",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="Optional M1 report snapshot.json when building the static Space.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("/tmp/ids13-hf-staging"),
        help="Local staging folder before upload.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build & validate local staging folder only without uploading to Hugging Face.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]

    if args.mode == "space":
        stage = build_static_space_bundle(
            project_root=project_root,
            stage_dir=args.work_dir / "space",
            snapshot_path=args.snapshot,
        )
        print(f"[OK] Prepared Static Space bundle at: {stage}")
        if args.dry_run:
            return 0
        token = resolve_hf_token()
        from huggingface_hub import HfApi  # type: ignore[import-not-found]

        api = HfApi(token=token)
        api.create_repo(
            repo_id=args.repo_id,
            repo_type="space",
            space_sdk="static",
            private=False,
            exist_ok=True,
        )
        api.upload_folder(
            repo_id=args.repo_id,
            repo_type="space",
            folder_path=str(stage),
            commit_message="Deploy Group 13 Jupyter Book static Space",
        )
        print(f"[OK] Uploaded HF Space: https://huggingface.co/spaces/{args.repo_id}")
        return 0

    if not args.student_id:
        raise SystemExit("--student-id is required when --mode=dataset")
    raw_dir = args.raw_dir or (
        args.drive_root / "m1-team-v4" / args.student_id / "main" / "full" / args.student_id / "raw"
    )
    proc_dir = args.processed_dir or (
        args.drive_root
        / "m1-team-v4"
        / args.student_id
        / "main"
        / "processed"
        / args.student_id
    )
    stage = args.work_dir / f"dataset-{args.student_id}"
    summary = export_student_dataset(
        student_id=args.student_id,
        raw_dir=raw_dir,
        output_dir=stage,
        processed_dir=proc_dir if proc_dir.is_dir() else None,
        predictions_path=args.predictions,
        members_config=project_root / "configs" / "members.csv",
    )
    validation = validate_parquet_tables(
        stage,
        student_id=args.student_id,
        members_config=project_root / "configs" / "members.csv",
    )
    if not validation["valid"]:
        raise SystemExit(f"Export validation failed: {validation}")
    print(f"[OK] Prepared & validated 6-table HF Dataset at {stage}: {summary['tables']}")
    if args.dry_run:
        return 0
    token = resolve_hf_token()
    from huggingface_hub import HfApi  # type: ignore[import-not-found]

    api = HfApi(token=token)
    api.create_repo(
        repo_id=args.repo_id,
        repo_type="dataset",
        private=False,
        exist_ok=True,
    )
    api.upload_folder(
        repo_id=args.repo_id,
        repo_type="dataset",
        folder_path=str(stage),
        commit_message=f"Upload Group 13 dataset shard for {args.student_id}",
    )
    print(f"[OK] Uploaded HF Dataset: https://huggingface.co/datasets/{args.repo_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
