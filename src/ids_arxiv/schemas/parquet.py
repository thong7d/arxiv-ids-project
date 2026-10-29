"""
PyArrow and Pydantic Schemas for 7 Hugging Face Parquet Tables (Milestone 3 & Final Submission)
"""

from typing import List, Optional

import pyarrow as pa
from pydantic import BaseModel, Field

# ---------------------------------------------------------
# 1. Pydantic Models for Row Validation
# ---------------------------------------------------------

class PaperRow(BaseModel):
    arxiv_id: str = Field(..., min_length=1)
    title: str = Field(default="")
    authors: List[str] = Field(default_factory=list)
    submission_date: str = Field(default="")
    revised_dates: List[str] = Field(default_factory=list)
    venue: Optional[str] = Field(default=None)


class ElementRow(BaseModel):
    element_id: str = Field(..., min_length=1)
    arxiv_id: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    content: str = Field(default="")


class ElementParentRow(BaseModel):
    arxiv_id: str = Field(..., min_length=1)
    version: int = Field(..., ge=1)
    element_id: str = Field(..., min_length=1)
    parent_id: str = Field(..., min_length=1)


class BibtexEntryRow(BaseModel):
    arxiv_id: str = Field(..., min_length=1)
    citation_key: str = Field(..., min_length=1)
    entry_type: str = Field(default="misc")
    title: str = Field(default="")
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = Field(default=None)
    doi: str = Field(default="")
    journal: str = Field(default="")
    url: str = Field(default="")


class PaperReferenceRow(BaseModel):
    arxiv_id: str = Field(..., min_length=1)
    ref_arxiv_id: str = Field(..., min_length=1)
    ref_title: str = Field(default="")
    ref_authors: List[str] = Field(default_factory=list)
    ref_submission_date: str = Field(default="")
    ref_s2_id: str = Field(default="")


class PredictionRow(BaseModel):
    arxiv_id: str = Field(..., min_length=1)
    partition: str = Field(...)  # 'train', 'valid', 'test'
    citation_key: str = Field(..., min_length=1)
    groundtruth_arxiv_id: Optional[str] = Field(default=None)
    cand_1: Optional[str] = Field(default=None)
    cand_2: Optional[str] = Field(default=None)
    cand_3: Optional[str] = Field(default=None)
    cand_4: Optional[str] = Field(default=None)
    cand_5: Optional[str] = Field(default=None)


class SourceRow(BaseModel):
    arxiv_id: str = Field(..., min_length=1)
    version: int = Field(..., ge=1)
    filename: str = Field(..., min_length=1)
    content: str = Field(default="")


# ---------------------------------------------------------
# 2. Strict PyArrow Schemas (Conforming to Specification)
# ---------------------------------------------------------

PAPERS_ARROW_SCHEMA = pa.schema([
    ("arxiv_id", pa.string(), False),
    ("title", pa.string(), True),
    ("authors", pa.list_(pa.string()), True),
    ("submission_date", pa.string(), True),
    ("revised_dates", pa.list_(pa.string()), True),
    ("venue", pa.string(), True),
])

ELEMENTS_ARROW_SCHEMA = pa.schema([
    ("element_id", pa.string(), False),
    ("arxiv_id", pa.string(), False),
    ("kind", pa.dictionary(pa.int32(), pa.string()), True),
    ("content", pa.string(), True),
])

ELEMENT_PARENTS_ARROW_SCHEMA = pa.schema([
    ("arxiv_id", pa.string(), False),
    ("version", pa.int32(), False),
    ("element_id", pa.string(), False),
    ("parent_id", pa.string(), False),
])

BIBTEX_ENTRIES_ARROW_SCHEMA = pa.schema([
    ("arxiv_id", pa.string(), False),
    ("citation_key", pa.string(), False),
    ("entry_type", pa.dictionary(pa.int32(), pa.string()), True),
    ("title", pa.string(), True),
    ("authors", pa.list_(pa.string()), True),
    ("year", pa.int32(), True),
    ("doi", pa.string(), True),
    ("journal", pa.string(), True),
    ("url", pa.string(), True),
])

PAPER_REFERENCES_ARROW_SCHEMA = pa.schema([
    ("arxiv_id", pa.string(), False),
    ("ref_arxiv_id", pa.string(), False),
    ("ref_title", pa.string(), True),
    ("ref_authors", pa.list_(pa.string()), True),
    ("ref_submission_date", pa.string(), True),
    ("ref_s2_id", pa.string(), True),
])

PREDICTIONS_ARROW_SCHEMA = pa.schema([
    ("arxiv_id", pa.string(), False),
    ("partition", pa.dictionary(pa.int32(), pa.string()), False),
    ("citation_key", pa.string(), False),
    ("groundtruth_arxiv_id", pa.string(), True),
    ("cand_1", pa.string(), True),
    ("cand_2", pa.string(), True),
    ("cand_3", pa.string(), True),
    ("cand_4", pa.string(), True),
    ("cand_5", pa.string(), True),
])

SOURCES_ARROW_SCHEMA = pa.schema([
    ("arxiv_id", pa.string(), False),
    ("version", pa.int32(), False),
    ("filename", pa.string(), False),
    ("content", pa.string(), True),
])

TABLE_SCHEMAS = {
    "papers": PAPERS_ARROW_SCHEMA,
    "elements": ELEMENTS_ARROW_SCHEMA,
    "element_parents": ELEMENT_PARENTS_ARROW_SCHEMA,
    "bibtex_entries": BIBTEX_ENTRIES_ARROW_SCHEMA,
    "paper_references": PAPER_REFERENCES_ARROW_SCHEMA,
    "predictions": PREDICTIONS_ARROW_SCHEMA,
    "sources": SOURCES_ARROW_SCHEMA,
}
