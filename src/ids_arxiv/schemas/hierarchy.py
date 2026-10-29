"""
Pydantic schemas for Hierarchical Structure (Milestone 2: hierarchy.json)
"""

from typing import Dict

from pydantic import BaseModel, Field, field_validator


class HierarchyData(BaseModel):
    """
    Schema for hierarchy.json:
    - elements: mapping of element_id -> cleaned content / title
    - hierarchy: mapping of version_str ("1", "2", ...) -> mapping of child_id -> parent_id
    """
    elements: Dict[str, str] = Field(
        ...,
        description="Deduplicated elements across all versions (element_id -> text content)"
    )
    hierarchy: Dict[str, Dict[str, str]] = Field(
        ...,
        description="Version mapping (version_str -> dict of child_id -> parent_id)"
    )

    @field_validator("hierarchy")
    @classmethod
    def validate_hierarchy_versions(cls, v: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        if not v:
            raise ValueError("Hierarchy must contain at least one version mapping.")
        for version_str, parent_map in v.items():
            if not isinstance(parent_map, dict):
                raise ValueError(f"Parent map for version {version_str} must be a dictionary.")
        return v
