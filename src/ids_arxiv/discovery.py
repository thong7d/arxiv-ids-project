"""
Discovery module: Range validation, non-overlap checks, and manifest generation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd


@dataclass
class MemberRange:
    student_id: str
    name: str
    start_id: str
    end_id: str
    start_month: str
    end_month: str

    def to_tuple_start(self) -> Tuple[int, int]:
        parts = self.start_id.split(".")
        return int(parts[0]), int(parts[1])

    def to_tuple_end(self) -> Tuple[int, int]:
        parts = self.end_id.split(".")
        return int(parts[0]), int(parts[1])

    def contains(self, arxiv_id: str) -> bool:
        """Check if an arXiv ID (in format YYMM.NNNNN or YYMM-NNNNN) falls into this range."""
        clean_id = to_arxiv_id(arxiv_id)
        parts = clean_id.split(".")
        if len(parts) != 2:
            return False
        try:
            val = (int(parts[0]), int(parts[1]))
            return self.to_tuple_start() <= val <= self.to_tuple_end()
        except ValueError:
            return False


def to_dir_id(arxiv_id: str) -> str:
    """Convert '2509.01047' or 'hep-th/9901001' to local directory format '2509-01047'."""
    clean = arxiv_id.split("v")[0]  # Remove version if present
    return clean.replace(".", "-").replace("/", "_")


def to_arxiv_id(dir_or_arxiv_id: str) -> str:
    """Convert '2509-01047' to canonical arXiv ID '2509.01047'."""
    clean = dir_or_arxiv_id.split("v")[0]
    if "_" in clean:
        return clean.replace("_", "/")
    if "-" in clean and "." not in clean:
        parts = clean.split("-", 1)
        return f"{parts[0]}.{parts[1]}"
    return clean


def load_members(config_path: Path) -> List[MemberRange]:
    """Load and validate member ranges from configs/members.csv."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    df = pd.read_csv(config_path, dtype=str)
    required_cols = {"student_id", "name", "start_id", "end_id"}
    if not required_cols.issubset(df.columns):
        raise ValueError(f"Config must contain columns: {required_cols}")

    members: List[MemberRange] = []
    for _, row in df.iterrows():
        members.append(
            MemberRange(
                student_id=str(row["student_id"]).strip(),
                name=str(row["name"]).strip(),
                start_id=str(row["start_id"]).strip(),
                end_id=str(row["end_id"]).strip(),
                start_month=str(row.get("start_month", "")).strip(),
                end_month=str(row.get("end_month", "")).strip(),
            )
        )

    validate_member_ranges(members)
    return members


def validate_member_ranges(members: List[MemberRange]) -> None:
    """
    Validate:
    1. Each member's start_id <= end_id.
    2. No two members have overlapping ranges.
    3. Exactly one owner for each ID boundary.
    """
    if len(members) == 0:
        raise ValueError("Members list is empty.")

    # Check valid individual bounds
    for m in members:
        start_t = m.to_tuple_start()
        end_t = m.to_tuple_end()
        if start_t > end_t:
            raise ValueError(
                f"Invalid range for student {m.student_id} ({m.name}): start {m.start_id} > end {m.end_id}"
            )

    # Check pairwise non-overlap
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            m1 = members[i]
            m2 = members[j]
            s1, e1 = m1.to_tuple_start(), m1.to_tuple_end()
            s2, e2 = m2.to_tuple_start(), m2.to_tuple_end()

            # Overlap occurs if max(s1, s2) <= min(e1, e2)
            if max(s1, s2) <= min(e1, e2):
                raise ValueError(
                    f"Range overlap detected between {m1.name} ({m1.start_id} - {m1.end_id}) "
                    f"and {m2.name} ({m2.start_id} - {m2.end_id})"
                )


def find_owner(arxiv_id: str, members: List[MemberRange]) -> Optional[str]:
    """Find the student_id who owns this paper."""
    for m in members:
        if m.contains(arxiv_id):
            return m.student_id
    return None


def generate_range_ids(member: MemberRange) -> List[str]:
    """
    Generate synthetic/sequential list of IDs for a single member's range.
    Handles month transition if start_month != end_month.
    """
    s_yymm, s_num = member.to_tuple_start()
    e_yymm, e_num = member.to_tuple_end()

    ids: List[str] = []
    if s_yymm == e_yymm:
        for n in range(s_num, e_num + 1):
            ids.append(f"{s_yymm:04d}.{n:05d}")
    else:
        # Cross-month handling (e.g. 2508 -> 2509)
        # End of 2508: assume up to 99999 or specified cutoff
        # For full discovery, OAI-PMH harvest provides the exact list.
        for n in range(s_num, s_num + 50):  # representative subset
            ids.append(f"{s_yymm:04d}.{n:05d}")
        for n in range(1, e_num + 1):
            ids.append(f"{e_yymm:04d}.{n:05d}")

    return ids


def build_manifest(members: List[MemberRange], discovered_ids: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Build unified paper manifest DataFrame:
    columns: [arxiv_id, dir_id, owner_student_id, owner_name, status]
    """
    records = []

    if discovered_ids is not None:
        for aid in discovered_ids:
            canonical_id = to_arxiv_id(aid)
            owner = find_owner(canonical_id, members)
            if owner:
                member_obj = next(m for m in members if m.student_id == owner)
                records.append({
                    "arxiv_id": canonical_id,
                    "dir_id": to_dir_id(canonical_id),
                    "owner_student_id": owner,
                    "owner_name": member_obj.name,
                    "status": "pending",
                })
    else:
        for m in members:
            # Generate expected IDs
            m_ids = generate_range_ids(m)
            for aid in m_ids:
                records.append({
                    "arxiv_id": aid,
                    "dir_id": to_dir_id(aid),
                    "owner_student_id": m.student_id,
                    "owner_name": m.name,
                    "status": "pending",
                })

    df = pd.DataFrame(records).drop_duplicates(subset=["arxiv_id"]).reset_index(drop=True)
    return df
