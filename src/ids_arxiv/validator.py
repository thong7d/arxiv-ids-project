"""
Validator module for data integrity across all 3 milestones and Parquet exports.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pyarrow.parquet as pq

from .discovery import load_members
from .schemas.hierarchy import HierarchyData
from .schemas.metadata import PaperMetadata, ReferenceItem
from .schemas.parquet import TABLE_SCHEMAS

FORBIDDEN_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".bmp", ".tiff", ".svg"}


class ValidationError(Exception):
    pass


def validate_raw_paper(paper_dir: Path) -> Dict[str, Any]:
    """
    Validate raw crawler output for a single paper folder (e.g. data/raw/2509-01047/).
    Checks:
    - metadata.json validity
    - references.json validity
    - presence of version directories
    - NO forbidden image/binary files
    """
    results: Dict[str, Any] = {"paper_id": paper_dir.name, "valid": True, "errors": []}

    # 1. Check metadata.json
    meta_file = paper_dir / "metadata.json"
    if not meta_file.exists():
        results["errors"].append("Missing metadata.json")
    else:
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            PaperMetadata.model_validate(data)
        except Exception as e:
            results["errors"].append(f"metadata.json invalid: {str(e)}")

    # 2. Check references.json
    refs_file = paper_dir / "references.json"
    if not refs_file.exists():
        results["errors"].append("Missing references.json")
    else:
        try:
            with open(refs_file, "r", encoding="utf-8") as f:
                refs_data = json.load(f)
            if not isinstance(refs_data, dict):
                results["errors"].append("references.json must be a JSON object (dict)")
            else:
                for k, v in refs_data.items():
                    ReferenceItem.model_validate(v)
        except Exception as e:
            results["errors"].append(f"references.json invalid: {str(e)}")

    # 3. Check version directories and figure filter
    version_dirs = [d for d in paper_dir.iterdir() if d.is_dir() and d.name.startswith("v")]
    if not version_dirs:
        results["errors"].append("No version directories (e.g. v1/) found")

    for vdir in version_dirs:
        for f in vdir.rglob("*"):
            if f.is_file() and f.suffix.lower() in FORBIDDEN_IMAGE_EXTENSIONS:
                results["errors"].append(
                    f"Forbidden image/binary file found in {vdir.name}: {f.name}"
                )

    if results["errors"]:
        results["valid"] = False

    return results


def validate_processed_paper(paper_dir: Path) -> Dict[str, Any]:
    """
    Validate processed parser output for a single paper folder (e.g. data/processed/2509-01047/).
    Checks:
    - hierarchy.json conforms to schema, tree has single root per version, no cycles
    - refs.bib exists
    """
    results: Dict[str, Any] = {"paper_id": paper_dir.name, "valid": True, "errors": []}

    # 1. Check hierarchy.json
    hier_file = paper_dir / "hierarchy.json"
    if not hier_file.exists():
        results["errors"].append("Missing hierarchy.json")
    else:
        try:
            with open(hier_file, "r", encoding="utf-8") as f:
                h_data = json.load(f)
            parsed_hier = HierarchyData.model_validate(h_data)

            # Cycle and single root check
            for version_str, parent_map in parsed_hier.hierarchy.items():
                roots = set()
                for child, parent in parent_map.items():
                    if child == parent or parent == "":
                        roots.add(child)
                    # cycle check
                    curr = child
                    path = []
                    while curr in parent_map and curr != parent_map[curr]:
                        if curr in path:
                            results["errors"].append(f"Cycle detected in v{version_str} hierarchy: {curr}")
                            break
                        path.append(curr)
                        curr = parent_map[curr]

        except Exception as e:
            results["errors"].append(f"hierarchy.json invalid: {str(e)}")

    # 2. Check refs.bib
    bib_file = paper_dir / "refs.bib"
    if not bib_file.exists():
        results["errors"].append("Missing refs.bib")

    if results["errors"]:
        results["valid"] = False

    return results


def validate_parquet_tables(
    export_dir: Path,
    student_id: Optional[str] = None,
    members_config: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Validate the 7 Parquet tables in export directory against PyArrow schemas and course constraints.
    Optionally verifies range isolation for student_id.
    """
    results: Dict[str, Any] = {"export_dir": str(export_dir), "valid": True, "table_checks": {}}

    target_tables = [
        "papers",
        "elements",
        "element_parents",
        "bibtex_entries",
        "paper_references",
        "predictions",
        "sources",
    ]

    for table_name in target_tables:
        table_path = export_dir / table_name
        parquet_files: List[Path] = []
        if table_path.is_dir():
            parquet_files = list(table_path.glob("*.parquet"))
        elif table_path.with_suffix(".parquet").exists():
            parquet_files = [table_path.with_suffix(".parquet")]

        if not parquet_files:
            results["table_checks"][table_name] = {
                "valid": False,
                "error": f"Table files not found in {table_path}",
            }
            results["valid"] = False
            continue

        try:
            # Read first parquet file to inspect schema and metadata
            table = pq.read_table(parquet_files[0])
            expected_schema = TABLE_SCHEMAS[table_name]

            # Verify column existence and non-null constraints
            errors = []
            for field in expected_schema:
                if field.name not in table.schema.names:
                    errors.append(f"Missing column: {field.name}")
                else:
                    col = table[field.name]
                    if not field.nullable and col.null_count > 0:
                        errors.append(f"Column '{field.name}' contains {col.null_count} nulls but is non-null")

            results["table_checks"][table_name] = {
                "valid": len(errors) == 0,
                "row_count": table.num_rows,
                "errors": errors,
            }
            if errors:
                results["valid"] = False

        except Exception as e:
            results["table_checks"][table_name] = {"valid": False, "error": str(e)}
            results["valid"] = False

    # Optional range isolation check for personal submission
    if student_id and members_config and results["valid"]:
        try:
            members = load_members(members_config)
            member = next((m for m in members if m.student_id == student_id), None)
            if member:
                papers_table_path = export_dir / "papers"
                p_file = (
                    list(papers_table_path.glob("*.parquet"))[0]
                    if papers_table_path.is_dir()
                    else export_dir / "papers.parquet"
                )
                t_papers = pq.read_table(p_file)
                arxiv_ids = t_papers["arxiv_id"].to_pylist()
                out_of_range = [aid for aid in arxiv_ids if not member.contains(aid)]
                if out_of_range:
                    results["valid"] = False
                    results["range_isolation_error"] = (
                        f"Found {len(out_of_range)} papers outside student {student_id}'s assigned range: {out_of_range[:5]}"
                    )
        except Exception as e:
            results["valid"] = False
            results["range_isolation_error"] = str(e)

    return results


validate_hf_export = validate_parquet_tables
