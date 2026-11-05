from ids_arxiv.discovery import MemberRange, complete_assigned_manifest


def test_search_gaps_retained_including_month_transition():
    member = MemberRange("x", "X", "2508.00003", "2509.00002", "2508", "2509")
    frame, missing = complete_assigned_manifest(
        [member], ["2508.00003", "2508.00005", "2509.00002"])
    assert len(frame) == 5
    assert missing == ["2508.00004", "2509.00001"]
    assert frame[frame.status == "search_missing"].arxiv_id.tolist() == missing
