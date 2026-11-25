"""
Pydantic schemas for Hierarchical Structure (Milestone 2: hierarchy.json)
"""

from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator


class HierarchyData(BaseModel):
    """
    Schema for hierarchy.json:
    - elements: mapping of element_id -> cleaned content / title
    - hierarchy: mapping of version_str ("1", "2", ...) -> mapping of child_id -> parent_id.
      Versions without TeX source (e.g., PDF-only or HTTP 404 on /src/<id>v<n>) are
      preserved as empty dicts ("2": {}) so every real version remains recorded.
    - version_states: optional mapping of version_str -> status ("downloaded", "pdf_only",
      "not_found_404", "non_tex_source") for explicit provenance in M2/M3.
    """
    elements: Dict[str, str] = Field(
        ...,
        description="Deduplicated elements across all versions (element_id -> text content)"
    )
    hierarchy: Dict[str, Dict[str, str]] = Field(
        ...,
        description="Version mapping (version_str -> dict of child_id -> parent_id; {} for PDF-only/404 versions)"
    )
    version_states: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional per-version source status (downloaded, pdf_only, not_found_404, non_tex_source)"
    )
    element_kinds: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional mapping of element_id -> semantic kind (document, section, sentence, formula, figure, ...)"
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
