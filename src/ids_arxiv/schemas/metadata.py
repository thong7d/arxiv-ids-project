"""
Pydantic schemas for Raw Metadata (Milestone 1)
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PaperMetadata(BaseModel):
    """Metadata schema for a scraped paper (metadata.json)."""
    model_config = ConfigDict(extra="allow")

    title: str = Field(..., description="Paper title")
    authors: List[str] = Field(default_factory=list, description="List of author names")
    submission_date: str = Field(..., description="Submission date in ISO format")
    revised_dates: List[str] = Field(default_factory=list, description="List of revision dates in ISO format")
    venue: Optional[str] = Field(None, description="Publication venue or conference/journal")


class ReferenceItem(BaseModel):
    """Metadata schema for an individual reference entry."""
    model_config = ConfigDict(extra="allow")

    title: str = Field(..., description="Reference paper title")
    authors: List[str] = Field(default_factory=list, description="List of author names")
    submission_date: Optional[str] = Field("", description="Submission date in ISO format")
    s2_id: str = Field(..., description="Semantic Scholar ID")
    venue: Optional[str] = Field(None, description="Publication venue")
    year: Optional[int] = Field(None, description="Publication year")


# references.json is a dict mapping arXiv ID in "yymm-id" format to ReferenceItem
ReferencesData = Dict[str, ReferenceItem]
