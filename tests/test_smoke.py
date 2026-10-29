"""
End-to-End Smoke Test: Fixture -> Raw Validation -> Processed Validation -> 7 Parquet Tables Export & Validation.
Runs under 30 seconds to serve as acceptance gate for Phase 1.
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ids_arxiv.schemas.parquet import TABLE_SCHEMAS
from ids_arxiv.validator import (
    validate_parquet_tables,
    validate_processed_paper,
    validate_raw_paper,
)


def test_fixture_raw_validation():
    fixture_dir = Path("tests/fixtures/synthetic_paper")
    assert fixture_dir.exists(), "Synthetic paper fixture directory must exist."

    res = validate_raw_paper(fixture_dir)
    assert res["valid"], f"Raw validation failed: {res.get('errors')}"
    assert len(res["errors"]) == 0


def test_fixture_processed_validation(tmp_path):
    # Prepare a processed paper folder in tmp_path
    paper_dir = tmp_path / "synthetic_paper"
    paper_dir.mkdir()

    # Create valid hierarchy.json
    hierarchy_data = {
        "elements": {
            "2509-01047-doc": "Deep Learning for Reference Resolution",
            "2509-01047-sec-1": "Introduction",
            "2509-01047-sent-1": "Deep learning has revolutionized artificial intelligence in recent decades.",
            "2509-01047-eq-1": "\\begin{equation}\nL(\\theta) = \\sum_{i=1}^N (y_i - \\hat{y}_i)^2\n\\end{equation}",
        },
        "hierarchy": {
            "1": {
                "2509-01047-sec-1": "2509-01047-doc",
                "2509-01047-sent-1": "2509-01047-sec-1",
                "2509-01047-eq-1": "2509-01047-sec-1",
            },
            "2": {
                "2509-01047-sec-1": "2509-01047-doc",
                "2509-01047-sent-1": "2509-01047-sec-1",
            },
        },
    }
    with open(paper_dir / "hierarchy.json", "w", encoding="utf-8") as f:
        json.dump(hierarchy_data, f, indent=2)

    # Create valid refs.bib
    bib_content = """@article{vaswani2017attention,
  author = {Ashish Vaswani and Noam Shazeer and Niki Parmar},
  title = {Attention Is All You Need},
  year = {2017}
}
"""
    with open(paper_dir / "refs.bib", "w", encoding="utf-8") as f:
        f.write(bib_content)

    res = validate_processed_paper(paper_dir)
    assert res["valid"], f"Processed validation failed: {res.get('errors')}"


def test_parquet_export_end_to_end_validation(tmp_path):
    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    # 1. papers
    t_papers = pa.Table.from_pydict(
        {
            "arxiv_id": ["2509.01047"],
            "title": ["Deep Learning for Reference Resolution"],
            "authors": [["Alice Smith", "Bob Jones"]],
            "submission_date": ["2025-09-01T10:00:00Z"],
            "revised_dates": [["2025-09-01T10:00:00Z"]],
            "venue": ["ICML 2025"],
        },
        schema=TABLE_SCHEMAS["papers"],
    )
    pq.write_table(t_papers, export_dir / "papers.parquet")

    # 2. elements
    t_elements = pa.Table.from_pydict(
        {
            "element_id": ["2509-01047-sent-1"],
            "arxiv_id": ["2509.01047"],
            "kind": ["sentence"],
            "content": ["Deep learning has revolutionized artificial intelligence."],
        },
        schema=TABLE_SCHEMAS["elements"],
    )
    pq.write_table(t_elements, export_dir / "elements.parquet")

    # 3. element_parents
    t_parents = pa.Table.from_pydict(
        {
            "arxiv_id": ["2509.01047"],
            "version": [1],
            "element_id": ["2509-01047-sent-1"],
            "parent_id": ["2509-01047-sec-1"],
        },
        schema=TABLE_SCHEMAS["element_parents"],
    )
    pq.write_table(t_parents, export_dir / "element_parents.parquet")

    # 4. bibtex_entries
    t_bib = pa.Table.from_pydict(
        {
            "arxiv_id": ["2509.01047"],
            "citation_key": ["vaswani2017attention"],
            "entry_type": ["article"],
            "title": ["Attention Is All You Need"],
            "authors": [["Ashish Vaswani", "Noam Shazeer"]],
            "year": [2017],
            "doi": ["10.5555/3295222"],
            "journal": ["NeurIPS"],
            "url": ["https://arxiv.org/abs/1706.03762"],
        },
        schema=TABLE_SCHEMAS["bibtex_entries"],
    )
    pq.write_table(t_bib, export_dir / "bibtex_entries.parquet")

    # 5. paper_references
    t_refs = pa.Table.from_pydict(
        {
            "arxiv_id": ["2509.01047"],
            "ref_arxiv_id": ["1706-03762"],
            "ref_title": ["Attention Is All You Need"],
            "ref_authors": [["Ashish Vaswani", "Noam Shazeer"]],
            "ref_submission_date": ["2017-06-12T17:52:00Z"],
            "ref_s2_id": ["204e3073870fae3d05bcbc2f6a8e263d9b72e776"],
        },
        schema=TABLE_SCHEMAS["paper_references"],
    )
    pq.write_table(t_refs, export_dir / "paper_references.parquet")

    # 6. predictions
    t_preds = pa.Table.from_pydict(
        {
            "arxiv_id": ["2509.01047"],
            "partition": ["test"],
            "citation_key": ["vaswani2017attention"],
            "groundtruth_arxiv_id": ["1706-03762"],
            "cand_1": ["1706-03762"],
            "cand_2": [None],
            "cand_3": [None],
            "cand_4": [None],
            "cand_5": [None],
        },
        schema=TABLE_SCHEMAS["predictions"],
    )
    pq.write_table(t_preds, export_dir / "predictions.parquet")

    # 7. sources
    t_src = pa.Table.from_pydict(
        {
            "arxiv_id": ["2509.01047"],
            "version": [1],
            "filename": ["main.tex"],
            "content": ["\\documentclass{article}"],
        },
        schema=TABLE_SCHEMAS["sources"],
    )
    pq.write_table(t_src, export_dir / "sources.parquet")

    # Run complete validator
    res = validate_parquet_tables(
        export_dir=export_dir,
        student_id="23120358",
        members_config=Path("configs/members.csv"),
    )
    assert res["valid"], f"Parquet export validation failed: {res}"
    assert len(res["table_checks"]) == 7
    for t_name, check in res["table_checks"].items():
        assert check["valid"], f"Table {t_name} failed: {check.get('errors')}"
