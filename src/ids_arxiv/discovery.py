"""
Discovery module: Range validation, non-overlap checks, and manifest generation.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    clean = re.sub(r"v\d+$", "", arxiv_id)
    return clean.replace(".", "-").replace("/", "_")


def to_arxiv_id(dir_or_arxiv_id: str) -> str:
    """Convert '2509-01047' to canonical arXiv ID '2509.01047'."""
    clean = re.sub(r"v\d+$", "", dir_or_arxiv_id)
    if "_" in clean:
        return clean.replace("_", "/")
    if re.fullmatch(r"\d{4}-\d{4,5}", clean):
        return clean.replace("-", ".", 1)
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
        raise ValueError(
            "Cross-month ranges require real discovery; refusing a truncated manifest."
        )

    return ids


def build_manifest(
    members: List[MemberRange], discovered_ids: Optional[List[str]] = None
) -> pd.DataFrame:
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
                records.append(
                    {
                        "arxiv_id": canonical_id,
                        "dir_id": to_dir_id(canonical_id),
                        "owner_student_id": owner,
                        "owner_name": member_obj.name,
                        "status": "pending",
                    }
                )
    else:
        for m in members:
            # Generate expected IDs
            m_ids = generate_range_ids(m)
            for aid in m_ids:
                records.append(
                    {
                        "arxiv_id": aid,
                        "dir_id": to_dir_id(aid),
                        "owner_student_id": m.student_id,
                        "owner_name": m.name,
                        "status": "pending",
                    }
                )

    columns = ["arxiv_id", "dir_id", "owner_student_id", "owner_name", "status"]
    df = pd.DataFrame(records, columns=columns).drop_duplicates(subset=["arxiv_id"])
    df = df.sort_values("arxiv_id").reset_index(drop=True)
    return df


ATOM = {
    "a": "http://www.w3.org/2005/Atom",
    "o": "http://a9.com/-/spec/opensearch/1.1/",
    "x": "http://arxiv.org/schemas/atom",
}


def complete_assigned_manifest(members, observed_ids):
    """Retain search omissions in the denominator; never call them discovered.

    Cross-month upper bounds use the largest actually observed ID in each
    completed month, not an assumed number of publications per student.
    """
    observed = {to_arxiv_id(aid) for aid in observed_ids}
    month_ends = {}
    for aid in observed:
        if re.fullmatch(r"\d{4}\.\d{5}", aid):
            month, number = map(int, aid.split("."))
            month_ends[month] = max(month_ends.get(month, 0), number)
    assigned = set()
    for member in members:
        start_month, start_number = member.to_tuple_start()
        end_month, end_number = member.to_tuple_end()
        date = datetime.strptime(f"{start_month:04d}", "%y%m")
        while int(date.strftime("%y%m")) <= end_month:
            month = int(date.strftime("%y%m"))
            lower = start_number if month == start_month else 1
            upper = end_number if month == end_month else month_ends.get(month)
            if upper is None or upper < lower:
                raise ValueError(f"No observed end-of-month bound for {month}")
            assigned.update(f"{month:04d}.{number:05d}" for number in range(lower, upper + 1))
            date = (date.replace(day=28) + timedelta(days=4)).replace(day=1)
    manifest = build_manifest(members, sorted(assigned))
    manifest.loc[~manifest.arxiv_id.isin(observed), "status"] = "search_missing"
    return manifest, sorted(assigned - observed)


def parse_atom(content: bytes) -> tuple[list[dict], int]:
    root = ET.fromstring(content)
    total_text = root.findtext("o:totalResults", namespaces=ATOM)
    records = []
    for entry in root.findall("a:entry", ATOM):
        full_id = entry.findtext("a:id", default="", namespaces=ATOM).rsplit("/abs/", 1)[-1]
        if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?", full_id):
            raise ValueError("arXiv API returned an error or invalid identifier")
        suffix = re.search(r"v(\d+)$", full_id)
        records.append(
            {
                "arxiv_id": re.sub(r"v\d+$", "", full_id),
                "latest_version": int(suffix.group(1)) if suffix else 1,
                "title": " ".join(entry.findtext("a:title", default="", namespaces=ATOM).split()),
                "authors": [
                    author.findtext("a:name", default="", namespaces=ATOM)
                    for author in entry.findall("a:author", ATOM)
                ],
                "submission_date": entry.findtext("a:published", default="", namespaces=ATOM),
                "latest_updated": entry.findtext("a:updated", default="", namespaces=ATOM),
                "venue": entry.findtext("x:journal_ref", namespaces=ATOM),
            }
        )
    return records, int(total_text) if total_text is not None else len(records)


def discover_publications(members: List[MemberRange], cache_dir: Path, events=None) -> pd.DataFrame:
    """Paged, category-independent discovery; never guess the end of a month.

    Cache pages for resuming discovery, but a benchmark campaign uses its own cache.
    Pad dates to accommodate identifier-month/publication-date boundary differences.
    """
    import os

    import requests

    from .crawler.http import get_response
    from .crawler.rate_limiter import arxiv_limiter
    from .storage import atomic_json, utc_now

    first = min(m.to_tuple_start()[0] for m in members)
    last = max(m.to_tuple_end()[0] for m in members)
    start_date = datetime.strptime(str(first), "%y%m") - timedelta(days=7)
    end_month = datetime.strptime(str(last), "%y%m")
    next_month = (end_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    end_date = next_month + timedelta(days=7)
    end_date = end_date.replace(hour=23, minute=59)
    session = requests.Session()
    session.headers["User-Agent"] = (
        "FIT-HCMUS-IDS-Group13/2.0 (contact: "
        + os.getenv("ARXIV_CONTACT_EMAIL", "thongpham796@gmail.com")
        + ")"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    records = {}
    scanned = 0
    completed_queries = []
    sharded_cache = cache_dir / "date-shards-v3"
    sharded_cache.mkdir(exist_ok=True)

    def scan_range(lower, upper):
        nonlocal scanned
        query = f"submittedDate:[{lower:%Y%m%d%H%M} TO {upper:%Y%m%d%H%M}]"
        tag = f"{lower:%Y%m%d%H%M}-{upper:%Y%m%d%H%M}"
        offset, total = 0, None
        while total is None or offset < total:
            page = sharded_cache / f"page-{tag}-{offset:06d}.xml"
            if page.exists():
                payload = page.read_bytes()
            else:
                with get_response(
                    session,
                    "https://export.arxiv.org/api/query",
                    arxiv_limiter,
                    params={
                        "search_query": query,
                        "start": offset,
                        "max_results": 500,
                        "sortBy": "submittedDate",
                        "sortOrder": "ascending",
                    },
                    events=events,
                ) as response:
                    payload = response.content
                parse_atom(payload)
                temporary = page.with_suffix(".tmp")
                temporary.write_bytes(payload)
                temporary.replace(page)
            entries, page_total = parse_atom(payload)
            # The API rejects deep offsets around 10,000. Split BEFORE that
            # boundary instead of retrying an impossible broad query forever.
            if offset == 0 and page_total > 8000:
                span = int((upper - lower).total_seconds() // 60)
                if span < 1:
                    raise ValueError("More than 8000 records in one minute; use OAI-PMH")
                middle = lower + timedelta(minutes=span // 2)
                scan_range(lower, middle)
                scan_range(middle + timedelta(minutes=1), upper)
                return
            if total is not None and page_total != total:
                raise ValueError(f"Discovery result changed in {tag}; audit this shard")
            total = page_total
            page_root = ET.fromstring(payload)
            actual_offset = page_root.findtext("o:startIndex", namespaces=ATOM)
            if actual_offset is not None and int(actual_offset) != offset:
                raise ValueError(f"Unexpected cached/API page offset in {tag}")
            if not entries and offset < total:
                raise ValueError(f"Unexpected empty discovery page in {tag}")
            for record in entries:
                if find_owner(record["arxiv_id"], members):
                    records[record["arxiv_id"]] = record
            offset += len(entries)
            scanned += len(entries)
            print(
                f"Discovery {tag}: {offset}/{total}; scanned={scanned}; assigned={len(records)}",
                flush=True,
            )
            if not entries:
                break
        completed_queries.append({"query": query, "total": total, "scanned": offset})

    lower = start_date
    while lower <= end_date:
        upper = min(end_date, lower + timedelta(days=7) - timedelta(minutes=1))
        scan_range(lower, upper)
        lower = upper + timedelta(minutes=1)
    if not records:
        raise ValueError("Discovery returned no assigned publications")
    for member in members:
        for boundary in (member.start_id, member.end_id):
            if boundary not in records:
                raise ValueError(
                    f"Assigned boundary {boundary} missing; audit discovery before crawling"
                )
    manifest, search_missing = complete_assigned_manifest(members, list(records))
    atomic_json(cache_dir / "metadata.json", records)
    atomic_json(
        cache_dir / "provenance.json",
        {
            "method": "weekly_date_shards_with_adaptive_split_v3",
            "queries": completed_queries,
            "scanned": scanned,
            "assigned": len(records),
            "assigned_including_search_missing": len(manifest),
            "search_missing_ids": search_missing,
            "created_at": utc_now(),
            "source": "arxiv_atom_api",
        },
    )
    return manifest
