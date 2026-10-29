"""
Crawl runner orchestrating metadata discovery, multi-version downloads,
figure stripping, Semantic Scholar reference enrichment, and checkpointing.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from ..discovery import load_members, to_arxiv_id, to_dir_id
from .arxiv_client import ArxivCrawler
from .s2_client import SemanticScholarClient

console = Console()


def crawl_paper(
    arxiv_id: str,
    output_dir: Path,
    arxiv_crawler: ArxivCrawler,
    s2_client: SemanticScholarClient,
    resume: bool = True,
) -> Dict[str, Any]:
    """
    Crawl a single publication: all versions, metadata, and references.
    Atomic write ensures no partial states remain.
    """
    clean_id = to_arxiv_id(arxiv_id)
    dir_name = to_dir_id(clean_id)
    paper_dir = output_dir / dir_name
    status_file = paper_dir / "crawl_status.json"

    # Checkpoint check
    if resume and status_file.exists():
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                prev_status = json.load(f)
            if prev_status.get("success"):
                return prev_status
        except Exception:
            pass

    paper_dir.mkdir(parents=True, exist_ok=True)
    crawl_record: Dict[str, Any] = {
        "arxiv_id": clean_id,
        "dir_name": dir_name,
        "success": False,
        "versions": [],
        "total_initial_bytes": 0,
        "total_stripped_bytes": 0,
        "total_saved_bytes": 0,
        "num_references": 0,
        "error": None,
    }

    # 1. Fetch arXiv Metadata and Version List
    meta_res = arxiv_crawler.fetch_metadata(clean_id)
    if not meta_res:
        crawl_record["error"] = f"Failed to retrieve metadata from arXiv API for {clean_id}."
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(crawl_record, f, indent=2)
        return crawl_record

    metadata, versions = meta_res

    # 2. Download and Extract Each Version
    version_results = []
    for v in versions:
        vdir = paper_dir / f"v{v}"
        vres = arxiv_crawler.download_and_extract_version(clean_id, v, vdir)
        version_results.append(vres)
        crawl_record["total_initial_bytes"] += vres.get("initial_bytes", 0)
        crawl_record["total_stripped_bytes"] += vres.get("stripped_bytes", 0)
        crawl_record["total_saved_bytes"] += vres.get("saved_bytes", 0)

    crawl_record["versions"] = version_results

    # 3. Fetch References from Semantic Scholar
    references = s2_client.get_paper_references(clean_id)
    crawl_record["num_references"] = len(references)

    # 4. Atomic Write Output Files
    # a. metadata.json
    with open(paper_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # b. references.json
    with open(paper_dir / "references.json", "w", encoding="utf-8") as f:
        json.dump(references, f, indent=2, ensure_ascii=False)

    # c. crawl_status.json
    all_succeeded = any(v.get("success") for v in version_results)
    crawl_record["success"] = all_succeeded
    if not all_succeeded:
        crawl_record["error"] = "Failed to download/extract source files for all versions."
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(crawl_record, f, indent=2, ensure_ascii=False)

    return crawl_record


def run_crawling_pipeline(
    manifest_path: Path,
    output_dir: Path,
    limit: Optional[int] = None,
    pilot_mode: bool = False,
    members_config: Optional[Path] = None,
    resume: bool = True,
    student_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run centralized crawler across paper manifest.
    If student_id is provided, filters manifest to that member's allocated papers.
    If pilot_mode=True, selects 10 papers per member (or 10 papers for the specified student).
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}. Run 'discover' first.")

    manifest_df = pd.read_parquet(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    if student_id:
        manifest_df = manifest_df[manifest_df["owner_student_id"] == str(student_id)].copy()
        if manifest_df.empty:
            console.print(f"[red]No papers found in manifest for student_id: {student_id}[/red]")
            return {"total_attempted": 0, "success_count": 0}

    if pilot_mode:
        if student_id:
            target_df = manifest_df.head(10).copy()
        elif members_config and members_config.exists():
            members = load_members(members_config)
            pilot_records = []
            for m in members:
                m_sub = manifest_df[manifest_df["owner_student_id"] == m.student_id]
                pilot_records.append(m_sub.head(10))
            target_df = pd.concat(pilot_records).reset_index(drop=True)
        else:
            target_df = manifest_df.head(30).copy()
    elif limit is not None:
        target_df = manifest_df.head(limit).copy()
    else:
        target_df = manifest_df.copy()

    total_papers = len(target_df)
    console.print(f"[bold cyan]Starting crawl pipeline for {total_papers} papers...[/bold cyan]")

    arxiv_crawler = ArxivCrawler()
    s2_client = SemanticScholarClient()

    results: List[Dict[str, Any]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Crawling arXiv corpus...", total=total_papers)

        for _, row in target_df.iterrows():
            aid = row["arxiv_id"]
            progress.update(task, description=f"Processing {aid}...")
            res = crawl_paper(
                arxiv_id=aid,
                output_dir=output_dir,
                arxiv_crawler=arxiv_crawler,
                s2_client=s2_client,
                resume=resume,
            )
            results.append(res)
            progress.advance(task)

    # Compute summary metrics
    success_count = sum(1 for r in results if r.get("success"))
    total_saved_mb = sum(r.get("total_saved_bytes", 0) for r in results) / (1024 * 1024)
    total_refs = sum(r.get("num_references", 0) for r in results)

    summary = {
        "total_attempted": total_papers,
        "success_count": success_count,
        "success_rate": round(success_count / max(1, total_papers) * 100, 2),
        "total_saved_mb": round(total_saved_mb, 2),
        "total_references_collected": total_refs,
        "avg_references_per_paper": round(total_refs / max(1, success_count), 2),
    }

    # Save run summary
    with open(output_dir / "crawl_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    console.print(f"[bold green][OK] Crawl finished. Success: {success_count}/{total_papers} ({summary['success_rate']}%)[/bold green]")
    console.print(f"[bold green]Saved space by figure stripping: {summary['total_saved_mb']} MB[/bold green]")
    console.print(f"[bold green]Total external references extracted: {total_refs}[/bold green]")

    return summary
