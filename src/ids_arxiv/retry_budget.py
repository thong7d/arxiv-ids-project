"""Finite work budgets are dispositions, never evidence of permanent absence."""

import json


def had_http_activity(path, offset):
    if not path.exists():
        return False
    with path.open("rb") as handle:
        handle.seek(offset)
        for line in handle:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("kind", "http") == "http":
                return True
    return False


def bounded_result(previous, result, limit, http_activity=False, task_timeout=False):
    """Do not charge a UTC-slot/cooldown wait as an upstream failure.

    A committed but unavailable record remains false-success. Quarantine only
    stops automatic network work; audit still verifies it or requires review.
    Upload failures are never quarantined: local pending bytes must survive.
    """
    result = dict(result)
    if limit is None:
        return result, None
    if not 1 <= limit <= 10:
        raise ValueError("Network pass budget must be between 1 and 10")
    count = int(previous.get("bounded_network_passes", 0))
    count += int(bool(http_activity or task_timeout))
    result["bounded_network_passes"] = count
    if result.get("success") or result.get("commit_state") != "committed":
        return result, None
    refs = result.get("references_status", {})
    metadata_ready = result.get("metadata_dates_complete") and result.get("metadata_versions_complete")
    source_404_only = bool(result.get("versions")) and all(
        v.get("success") or v.get("error") == "HTTP 404" for v in result["versions"])
    references_ready = refs.get("success") and refs.get("dates_complete")
    references_404 = refs.get("state") == "not_indexed" and refs.get("http_status") == 404
    terminal_404 = metadata_ready and (
        (result.get("source_success") and references_404)
        or (source_404_only and not result.get("source_success") and (references_ready or references_404)))
    if terminal_404 or count >= limit:
        result["automatic_stop_reason"] = "observed_404_needs_audit" if terminal_404 else "network_pass_budget_exhausted"
        result["download_success"] = False
        return result, "quarantined"
    return result, None
