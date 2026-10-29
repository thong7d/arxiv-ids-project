"""
Tests for Pydantic and PyArrow schema definitions.
"""

import pyarrow as pa
import pytest
from pydantic import ValidationError

from ids_arxiv.schemas.hierarchy import HierarchyData
from ids_arxiv.schemas.metadata import PaperMetadata, ReferenceItem
from ids_arxiv.schemas.parquet import (
    PAPERS_ARROW_SCHEMA,
    TABLE_SCHEMAS,
)


def test_paper_metadata_valid():
    data = {
        "title": "A Great Paper",
        "authors": ["Author One", "Author Two"],
        "submission_date": "2025-09-01T10:00:00Z",
        "revised_dates": ["2025-09-01T10:00:00Z"],
        "venue": "NeurIPS",
    }
    meta = PaperMetadata.model_validate(data)
    assert meta.title == "A Great Paper"
    assert len(meta.authors) == 2


def test_paper_metadata_missing_required():
    with pytest.raises(ValidationError):
        PaperMetadata.model_validate({"authors": ["Author One"]})


def test_reference_item_valid():
    ref = ReferenceItem(
        title="Attention Is All You Need",
        authors=["Vaswani et al."],
        submission_date="2017-06-12T17:52:00Z",
        s2_id="abc123456",
    )
    assert ref.s2_id == "abc123456"


def test_hierarchy_schema_valid():
    data = {
        "elements": {
            "elem-1": "Introduction to AI",
            "elem-2": "Machine learning is expanding rapidly.",
        },
        "hierarchy": {
            "1": {
                "elem-1": "doc-root",
                "elem-2": "elem-1",
            }
        },
    }
    h = HierarchyData.model_validate(data)
    assert "1" in h.hierarchy
    assert h.hierarchy["1"]["elem-2"] == "elem-1"


def test_hierarchy_schema_empty_versions():
    with pytest.raises(ValidationError):
        HierarchyData.model_validate({"elements": {}, "hierarchy": {}})


def test_pyarrow_schemas_exist():
    assert len(TABLE_SCHEMAS) == 7
    for name, schema in TABLE_SCHEMAS.items():
        assert isinstance(schema, pa.Schema)
        assert len(schema.names) > 0


def test_pyarrow_papers_creation():
    data = {
        "arxiv_id": ["2509.01047"],
        "title": ["Sample Paper"],
        "authors": [["Alice", "Bob"]],
        "submission_date": ["2025-09-01T00:00:00Z"],
        "revised_dates": [["2025-09-01T00:00:00Z"]],
        "venue": ["ICML"],
    }
    table = pa.Table.from_pydict(data, schema=PAPERS_ARROW_SCHEMA)
    assert table.num_rows == 1
    assert "arxiv_id" in table.column_names
