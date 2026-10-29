"""
Tests for discovery, ID conversions, member range loading, and overlap detection.
"""

from pathlib import Path

import pytest

from ids_arxiv.discovery import (
    MemberRange,
    find_owner,
    load_members,
    to_arxiv_id,
    to_dir_id,
    validate_member_ranges,
)


def test_id_conversions():
    assert to_dir_id("2509.01047") == "2509-01047"
    assert to_dir_id("2509.01047v2") == "2509-01047"
    assert to_dir_id("hep-th/9901001") == "hep-th_9901001"

    assert to_arxiv_id("2509-01047") == "2509.01047"
    assert to_arxiv_id("hep-th_9901001") == "hep-th/9901001"


def test_load_members_valid():
    config_path = Path("configs/members.csv")
    assert config_path.exists()
    members = load_members(config_path)
    assert len(members) == 3

    # Check IDs from plan
    assert members[0].student_id == "23120364"
    assert members[0].start_id == "2508.17872"
    assert members[0].end_id == "2509.01046"

    assert members[1].student_id == "23120358"
    assert members[1].start_id == "2509.01047"
    assert members[1].end_id == "2509.06046"

    assert members[2].student_id == "23120345"
    assert members[2].start_id == "2509.06047"
    assert members[2].end_id == "2509.11046"


def test_member_range_contains():
    m = MemberRange(
        student_id="23120358",
        name="Thành",
        start_id="2509.01047",
        end_id="2509.06046",
        start_month="2509",
        end_month="2509",
    )
    assert m.contains("2509.01047")
    assert m.contains("2509.03000")
    assert m.contains("2509.06046")
    assert not m.contains("2509.01046")
    assert not m.contains("2509.06047")


def test_detect_overlap_error():
    m1 = MemberRange(
        student_id="A", name="User A", start_id="2509.01000", end_id="2509.02000", start_month="2509", end_month="2509"
    )
    m2 = MemberRange(
        student_id="B", name="User B", start_id="2509.01500", end_id="2509.03000", start_month="2509", end_month="2509"
    )
    with pytest.raises(ValueError, match="Range overlap detected"):
        validate_member_ranges([m1, m2])


def test_find_owner():
    members = load_members(Path("configs/members.csv"))
    # Thông
    assert find_owner("2508.18000", members) == "23120364"
    # Thành
    assert find_owner("2509.01047", members) == "23120358"
    # Quang
    assert find_owner("2509.07000", members) == "23120345"
    # Out of range
    assert find_owner("2509.99999", members) is None
