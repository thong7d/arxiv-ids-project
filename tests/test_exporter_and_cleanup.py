"""Tests for 6-table Hugging Face Parquet exporter, HF layout validator, and Drive cleanup safety."""

import importlib.util
import json
from pathlib import Path

import pyarrow.parquet as pq

from ids_arxiv.exporter import export_student_dataset
from ids_arxiv.schemas.hierarchy import HierarchyData
from ids_arxiv.schemas.parquet import TABLE_SCHEMAS
from ids_arxiv.validator import validate_parquet_tables


def _load_cleanup_module():
    spec = importlib.util.spec_from_file_location(
        "_cleanup_drive_m1", Path("scripts/cleanup_drive_m1.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_hierarchy_schema_supports_element_kinds():
    h = HierarchyData.model_validate(
        {
            "elements": {"2509-01047#root1": "Version 1 root", "2509-01047#s1": "Hello."},
            "hierarchy": {"1": {"2509-01047#s1": "2509-01047#root1"}, "2": {}},
            "version_states": {"1": "downloaded", "2": "not_found_404"},
            "element_kinds": {"2509-01047#root1": "document", "2509-01047#s1": "sentence"},
        }
    )
    assert h.element_kinds == {"2509-01047#root1": "document", "2509-01047#s1": "sentence"}


def test_export_student_dataset_m1_only_and_with_m2(tmp_path):
    raw_dir = tmp_path / "raw"
    # In-range paper for 23120358 (2509.01047 .. 2509.06046)
    in_dir = raw_dir / "2509-01047"
    in_dir.mkdir(parents=True)
    (in_dir / "metadata.json").write_text(
        json.dumps(
            {
                "title": "Test Paper",
                "authors": ["Alice", "Bob"],
                "submission_date": "2025-09-02T00:00:00Z",
                "revised_dates": ["2025-09-02T00:00:00Z"],
                "venue": None,
            }
        ),
        encoding="utf-8",
    )
    (in_dir / "references.json").write_text(
        json.dumps(
            {
                "1706-03762": {
                    "arxiv_id": "1706.03762",
                    "title": "Attention Is All You Need",
                    "authors": ["Vaswani"],
                    "submission_date": "2017-06-12T00:00:00Z",
                    "s2_id": "s2abc",
                }
            }
        ),
        encoding="utf-8",
    )
    # Out-of-range paper (belongs to 23120364) must be ignored
    out_dir_raw = raw_dir / "2508-17872"
    out_dir_raw.mkdir(parents=True)
    (out_dir_raw / "metadata.json").write_text(
        json.dumps(
            {
                "title": "Other Owner",
                "authors": ["Carol"],
                "submission_date": "2025-08-25T00:00:00Z",
                "revised_dates": [],
                "venue": None,
            }
        ),
        encoding="utf-8",
    )

    # 1. Export with M1 only (M2/M3 empty schema-valid tables)
    hf_out = tmp_path / "hf_m1"
    summary = export_student_dataset(
        student_id="23120358",
        raw_dir=raw_dir,
        output_dir=hf_out,
        members_config=Path("configs/members.csv"),
    )
    assert summary["tables"]["papers"]["rows"] == 1
    assert summary["tables"]["references"]["rows"] == 1
    assert summary["tables"]["elements"]["rows"] == 0
    assert (hf_out / "README.md").is_file()
    readme = (hf_out / "README.md").read_text(encoding="utf-8")
    for tname in TABLE_SCHEMAS:
        assert f"- config_name: {tname}" in readme
        assert f"path: data/{tname}/*.parquet" in readme

    check = validate_parquet_tables(
        hf_out, student_id="23120358", members_config=Path("configs/members.csv")
    )
    assert check["valid"], f"HF validation failed: {check}"

    # 2. Export with M2 processed output
    proc_dir = tmp_path / "processed" / "2509-01047"
    proc_dir.mkdir(parents=True)
    (proc_dir / "hierarchy.json").write_text(
        json.dumps(
            {
                "elements": {
                    "2509-01047#root1": "Version 1 root",
                    "2509-01047#s1": "We cite \\cite{vaswani2017}.",
                },
                "hierarchy": {"1": {"2509-01047#s1": "2509-01047#root1"}, "2": {}},
                "element_kinds": {"2509-01047#root1": "document", "2509-01047#s1": "sentence"},
            }
        ),
        encoding="utf-8",
    )
    (proc_dir / "refs.bib").write_text(
        "@article{vaswani2017,\n  author = {Ashish Vaswani and Noam Shazeer},\n  title = {Attention Is All You Need},\n  year = {2017}\n}\n",
        encoding="utf-8",
    )
    hf_out2 = tmp_path / "hf_m2"
    summary2 = export_student_dataset(
        student_id="23120358",
        raw_dir=raw_dir,
        processed_dir=tmp_path / "processed",
        output_dir=hf_out2,
        members_config=Path("configs/members.csv"),
    )
    assert summary2["tables"]["elements"]["rows"] == 2
    assert summary2["tables"]["hierarchy"]["rows"] == 1
    assert summary2["tables"]["bibtex"]["rows"] == 1
    t_elem = pq.read_table(hf_out2 / "data" / "elements" / "part-00000.parquet")
    assert set(t_elem["kind"].to_pylist()) == {"document", "sentence"}


def test_cleanup_drive_discovers_only_clutter_and_protects_canonical(tmp_path):
    mod = _load_cleanup_module()
    root = tmp_path / "IDS_Nhom13_Corpus_Backup"
    (root / "m1-final-v3" / "manifests").mkdir(parents=True)
    (root / "m1-final-v3" / "manifests" / "papers.parquet").write_bytes(b"PAR1")
    (root / "IDS13_M1_Colab.ipynb").write_text("{}", encoding="utf-8")

    # Protected & obsolete bundles
    (root / "ids13-code-69413196afff.zip").write_bytes(b"keep")
    (root / "ids13-code-a170ab882d12.zip").write_bytes(b"keep")
    (root / "ids13-code-0fa8d893d639.zip").write_bytes(b"old")
    (root / "crawl-23120358.log").write_text("log", encoding="utf-8")
    (root / "notebooks").mkdir()
    (root / "m1-pilot-v3").mkdir()

    m1 = root / "m1-team-v4"
    for owner in ("23120364", "23120358", "23120345"):
        fbase = m1 / owner / "main" / "full" / owner
        (fbase / "raw").mkdir(parents=True)
        (fbase / "closure.json").write_text(
            json.dumps(
                {
                    "operational_closed": owner != "23120345",
                    "expected_count": 5000,
                    "assessed_count": 5000,
                    "missing_ids": [],
                    "counts": {"full_success": 4962},
                }
            ),
            encoding="utf-8",
        )
        (fbase / "environment.json").write_text("{}", encoding="utf-8")

    # Conflict file in 23120345 + duplicate 23120358 (1) + catalog conflict + stale runtime
    (m1 / "23120345" / "main" / "full" / "23120345" / "environment (1).json").write_text(
        "{}", encoding="utf-8"
    )
    (m1 / "23120358 (1)" / "main" / "full").mkdir(parents=True)
    (m1 / "23120364" / "991b90a524052fd4eee7").mkdir(parents=True)
    (m1 / "catalog").mkdir(parents=True)
    (m1 / "catalog" / "23120358-23120358-main.json").write_text("{}", encoding="utf-8")
    (m1 / "catalog" / "23120358-23120358-main (1).json").write_text("{}", encoding="utf-8")

    closures = mod.verify_canonical_closures(root)
    assert closures["23120358"]["operational_closed"] is True
    cats = mod.discover_cleanup_targets(root)
    assert [p.name for p in cats["duplicate_23120358_dirs"]] == ["23120358 (1)"]
    assert [p.name for p in cats["duplicate_catalog_files"]] == ["23120358-23120358-main (1).json"]
    assert [p.name for p in cats["stale_runtime_dirs"]] == ["991b90a524052fd4eee7"]
    assert [p.name for p in cats["conflict_json_files"]] == ["environment (1).json"]
    assert [p.name for p in cats["obsolete_code_bundles"]] == ["ids13-code-0fa8d893d639.zip"]
    assert [p.name for p in cats["legacy_root_logs_and_status"]] == ["crawl-23120358.log"]
    assert sorted(p.name for p in cats["obsolete_root_dirs"]) == ["m1-pilot-v3", "notebooks"]
