import sys
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import typer
from rich.console import Console
from rich.table import Table

from .discovery import build_manifest, load_members
from .validator import (
    validate_parquet_tables,
    validate_processed_paper,
    validate_raw_paper,
)

app = typer.Typer(
    name="ids-arxiv",
    help="arXiv Scraping, Hierarchical Parsing, and Reference Matching Pipeline (Group 13 - HCMUS)",
    add_completion=False,
)
console = Console()


@app.command()
def discover(
    config: Path = typer.Option(
        Path("configs/members.csv"),
        "--config",
        "-c",
        help="Path to members.csv configuration file.",
    ),
    output: Path = typer.Option(
        Path("data/manifests/papers.parquet"),
        "--output",
        "-o",
        help="Output path for paper manifest.",
    ),
):
    """Discover paper ID ranges, check for non-overlapping constraints, and generate manifest."""
    console.print(f"[bold cyan]Reading members config from {config}...[/bold cyan]")
    try:
        members = load_members(config)
        console.print(f"[green][OK] Successfully loaded and validated {len(members)} member ranges.[/green]")

        table = Table(title="Group 13 Assigned arXiv Ranges")
        table.add_column("Student ID", style="cyan")
        table.add_column("Name", style="magenta")
        table.add_column("Start ID", style="green")
        table.add_column("End ID", style="green")

        for m in members:
            table.add_row(m.student_id, m.name, m.start_id, m.end_id)
        console.print(table)

        manifest_df = build_manifest(members)
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest_df.to_parquet(output, index=False)
        console.print(f"[bold green][OK] Manifest generated with {len(manifest_df)} total records at {output}[/bold green]")

    except Exception as e:
        console.print(f"[bold red]Discovery Error:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command()
def validate(
    stage: str = typer.Option(
        ...,
        "--stage",
        "-s",
        help="Validation stage: 'raw', 'processed', or 'hf'.",
    ),
    path: Path = typer.Option(
        Path("data/raw"),
        "--path",
        "-p",
        help="Path to directory being validated.",
    ),
    student_id: Optional[str] = typer.Option(
        None,
        "--student-id",
        help="Optional student ID for range isolation check (for 'hf' stage).",
    ),
    config: Path = typer.Option(
        Path("configs/members.csv"),
        "--config",
        help="Path to members.csv config.",
    ),
):
    """Validate data schemas and constraints across raw, processed, and parquet stages."""
    console.print(f"[bold cyan]Running validation for stage: '{stage}' on {path}...[/bold cyan]")

    if stage == "raw":
        import re
        paper_dirs = [
            d for d in path.iterdir()
            if d.is_dir() and re.match(r"^\d{4}[-_]\d+", d.name)
        ] if path.exists() else []
        if not paper_dirs:
            console.print("[yellow]No paper directories found in path.[/yellow]")
            return

        all_valid = True
        for pdir in paper_dirs:
            res = validate_raw_paper(pdir)
            if not res["valid"]:
                all_valid = False
                console.print(f"[red][FAIL] {pdir.name}: {res['errors']}[/red]")
            else:
                console.print(f"[green][OK] {pdir.name}: valid[/green]")

        if not all_valid:
            raise typer.Exit(code=1)

    elif stage == "processed":
        paper_dirs = [d for d in path.iterdir() if d.is_dir()] if path.exists() else []
        if not paper_dirs:
            console.print("[yellow]No paper directories found in path.[/yellow]")
            return

        all_valid = True
        for pdir in paper_dirs:
            res = validate_processed_paper(pdir)
            if not res["valid"]:
                all_valid = False
                console.print(f"[red][FAIL] {pdir.name}: {res['errors']}[/red]")
            else:
                console.print(f"[green][OK] {pdir.name}: valid[/green]")

        if not all_valid:
            raise typer.Exit(code=1)

    elif stage == "hf":
        res = validate_parquet_tables(path, student_id=student_id, members_config=config)
        if not res["valid"]:
            console.print(f"[red][FAIL] Parquet export invalid:[/red] {res}")
            raise typer.Exit(code=1)
        console.print("[bold green][OK] All 7 Parquet tables conform to course schemas.[/bold green]")
    else:
        console.print(f"[red]Unknown stage '{stage}'. Choose 'raw', 'processed', or 'hf'.[/red]")
        raise typer.Exit(code=1)


@app.command()
def crawl(
    manifest: Path = typer.Option(
        Path("data/manifests/papers.parquet"),
        "--manifest",
        "-m",
        help="Path to papers manifest.",
    ),
    output: Path = typer.Option(
        Path("data/raw"),
        "--output",
        "-o",
        help="Output directory for raw corpus.",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Limit number of papers to crawl.",
    ),
    pilot: bool = typer.Option(
        False,
        "--pilot",
        help="Run pilot crawl (10 papers per member = 30 total).",
    ),
    config: Path = typer.Option(
        Path("configs/members.csv"),
        "--config",
        help="Path to members.csv config.",
    ),
    resume: bool = typer.Option(
        True,
        "--resume/--no-resume",
        help="Resume from previous checkpoint.",
    ),
    student_id: Optional[str] = typer.Option(
        None,
        "--student-id",
        help="Filter crawl to papers owned by a specific student ID.",
    ),
):
    """Crawl full-text LaTeX sources and reference metadata (Milestone 1)."""
    from .crawler import run_crawling_pipeline

    run_crawling_pipeline(
        manifest_path=manifest,
        output_dir=output,
        limit=limit,
        pilot_mode=pilot,
        members_config=config,
        resume=resume,
        student_id=student_id,
    )


@app.command()
def parse(
    input_dir: Path = typer.Option(
        Path("data/raw"),
        "--input",
        "-i",
        help="Input raw corpus directory.",
    ),
    output_dir: Path = typer.Option(
        Path("data/processed"),
        "--output",
        "-o",
        help="Output directory for processed hierarchy and bibtex.",
    ),
    resume: bool = typer.Option(True, "--resume"),
):
    """Parse hierarchical structure, normalize math, and deduplicate (Milestone 2)."""
    console.print("[bold cyan]Parse command placeholder (Phase 3 implementation)[/bold cyan]")


@app.command()
def label(
    input_dir: Path = typer.Option(
        Path("data/processed"),
        "--input",
        "-i",
        help="Input processed corpus directory.",
    ),
):
    """Generate ground truth labels (Milestone 3)."""
    console.print("[bold cyan]Label command placeholder (Phase 5 implementation)[/bold cyan]")


@app.command()
def train(
    config: Path = typer.Option(
        Path("configs/model.yaml"),
        "--config",
        help="Model config path.",
    ),
):
    """Train matching models and evaluate MRR (Milestone 3)."""
    console.print("[bold cyan]Train command placeholder (Phase 6 implementation)[/bold cyan]")


@app.command()
def export(
    student_id: str = typer.Option(
        ...,
        "--student-id",
        help="Student ID to export assigned range for Hugging Face upload.",
    ),
    output_dir: Path = typer.Option(
        Path("exports"),
        "--output",
        "-o",
        help="Target export directory.",
    ),
):
    """Export the 7 sharded Parquet tables for Hugging Face dataset (Phase 7)."""
    console.print(f"[bold cyan]Export command placeholder for student {student_id}[/bold cyan]")


@app.command()
def benchmark(
    stage: str = typer.Option(
        ...,
        "--stage",
        "-s",
        help="Benchmark stage: 'crawl' or 'parse'.",
    ),
):
    """Run performance benchmarking for Google Colab CPU report."""
    console.print(f"[bold cyan]Benchmark command placeholder for {stage}[/bold cyan]")


if __name__ == "__main__":
    app()
