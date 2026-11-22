"""Read-only final accounting. Exceptions never mutate crawler success flags."""

import hashlib
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from ids_arxiv.checkpoint import (
    EMPTY_SOURCE_STATES,
    METADATA_QUALITY,
    PROTOCOL,
    SOURCE_POLICY,
    read_json,
    reference_snapshot_consistent,
)
from ids_arxiv.schemas.metadata import PaperMetadata, ReferenceItem
from ids_arxiv.storage import sha256_file, utc_now, verify_inventory


def _date(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Date must include its timezone")
    return parsed


def _withdrawn(evidence, aid, version):
    """A flag alone, generic 404, or rate-limit response is not evidence."""
    return bool(
        evidence.get("verified") is True
        and evidence.get("data_download_success") is False
        and evidence.get("http_status") == 200
        and evidence.get("arxiv_id") == aid
        and evidence.get("version") == version
        and evidence.get("url") == f"https://arxiv.org/abs/{aid}v{version}"
        and evidence.get("withdrawn_banner") is True
        and evidence.get("no_pdf_available") is True
        and evidence.get("version_identity_confirmed") is True
        and re.fullmatch(r"[0-9a-f]{64}", evidence.get("response_sha256", ""))
        and _date(evidence["checked_at"])
    )


def assess_publication(directory, aid, withdrawal_records=None, allow_s2_unavailable=False,
                       allow_s2_rate_limited=False):
    """Verify local/readback bytes. Caller must impose a deadline for Drive I/O.

    Missing S2 references and their temporary errors remain pending. Only the
    explicit source-withdrawal exception authorized for this run is supported.
    The returned classification is NOT written to crawl_status.json or SQLite.
    """
    directory = Path(directory)
    record = read_json(directory / "crawl_status.json", {})
    result = {"arxiv_id": aid, "classification": "pending", "reasons": [],
              "withdrawn_versions": [], "data_download_success": False}
    errors = result["reasons"]
    evidence = withdrawal_records or {}
    try:
        if (record.get("arxiv_id") != aid or record.get("schema_version") != PROTOCOL
                or record.get("commit_state") != "committed" or not record.get("commit_id")):
            raise ValueError("Missing/mismatched current-protocol durable commit")
        expected = record.get("expected_versions", [])
        if not expected or expected != list(range(1, max(expected) + 1)):
            raise ValueError("Incomplete expected version sequence")
        for name in ("metadata.json", "references.json", "references_all.json"):
            path = directory / name
            if path.is_symlink() or sha256_file(path) != record.get("checksums", {}).get(name):
                raise ValueError(f"Checksum mismatch: {name}")
        metadata = read_json(directory / "metadata.json", {})
        references = read_json(directory / "references.json", {})
        PaperMetadata.model_validate(metadata)
        if (metadata.get("metadata_quality_version") != METADATA_QUALITY
                or not metadata.get("metadata_dates_complete") or not record.get("metadata_dates_complete")
                or not metadata.get("version_metadata_complete")
                or any(str(v) not in metadata.get("version_metadata", {}) for v in expected)):
            raise ValueError("Version dates not verified")
        dates = []
        for number in expected:
            dates.append(_date(metadata["version_dates"][str(number)]))
            if metadata["version_date_sources"][str(number)] not in {
                "oai_arXivRaw", "arxiv_atom_published", "arxiv_atom_updated", "arxiv_atom_version_updated"
            }:
                raise ValueError("Unverified version date provenance")
        if dates != sorted(dates) or _date(metadata["submission_date"]) != dates[0]:
            raise ValueError("Inconsistent version/submission dates")
        ref_status = record.get("references_status", {})
        all_references = read_json(directory / "references_all.json")
        s2_evidence = ref_status.get("evidence", {})
        unavailable = bool(allow_s2_unavailable and not record.get("success")
                           and not ref_status.get("success") and ref_status.get("state") == "not_indexed"
                           and ref_status.get("http_status") == s2_evidence.get("http_status") == 404
                           and s2_evidence.get("url") == f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{aid}/references"
                           and re.fullmatch(r"[0-9a-f]{64}", s2_evidence.get("response_sha256", ""))
                           and _date(s2_evidence["checked_at"]) and references == {} and all_references == [])
        s2_rate_limited = bool(
            allow_s2_rate_limited and not record.get("success")
            and not ref_status.get("success")
            and (
                ref_status.get("state") == "deferred"
                or (ref_status.get("state") == "retryable_error" and ref_status.get("http_status") == 429)
            )
            and int(record.get("attempt_count") or 0) >= 1
            and references == {} and all_references == []
        )
        s2_missing_allowed = unavailable or s2_rate_limited
        if not s2_missing_allowed and (not ref_status.get("success") or not ref_status.get("dates_complete")
                or not ref_status.get("all_references_retained") or not isinstance(all_references, list)
                or len(all_references) != ref_status.get("raw_count")
                or not reference_snapshot_consistent(references, all_references)):
            raise ValueError("References/date retrieval incomplete; not a source-withdrawal exception")
        if not s2_missing_allowed:
            if not isinstance(references, dict) or record.get("num_references", len(references)) != len(references):
                raise ValueError("Reference count/shape mismatch")
            if ref_status.get("arxiv_count", len(references)) != len(references):
                raise ValueError("S2 arXiv reference count mismatch")
            if ref_status.get("raw_count", len(references)) < len(references):
                raise ValueError("S2 raw count smaller than retained references")
            for reference in references.values():
                ReferenceItem.model_validate(reference)
                _date(reference["submission_date"])
                if not reference.get("s2_id") or reference.get("date_source") not in {"arxiv_atom", "arxiv_atom_published"}:
                    raise ValueError("Unverified reference date or missing S2 ID")
        rows = record.get("versions", [])
        versions = {row["version"]: row for row in rows}
        if len(versions) != len(rows) or set(versions) != set(expected):
            raise ValueError("Missing/duplicate/unexpected version records")
        for number in expected:
            version = versions[number]
            target = directory / f"v{number}"
            if not version.get("success"):
                proof = evidence.get(f"{aid}v{number}", {})
                historical_404 = (proof.get("source_failure_recorded") == "HTTP 404"
                                  and proof.get("source_url") == f"https://export.arxiv.org/src/{aid}v{number}")
                if (version.get("error") != "HTTP 404" and not historical_404) or not _withdrawn(proof, aid, number):
                    raise ValueError(f"v{number}: failure has no authoritative withdrawal evidence")
                result["withdrawn_versions"].append(number)
                continue
            if version.get("source_policy") != SOURCE_POLICY:
                raise ValueError(f"v{number}: legacy extraction policy")
            if target.is_symlink():
                raise ValueError(f"v{number}: symlink")
            if version.get("state") in EMPTY_SOURCE_STATES:
                if not target.is_dir() or any(target.iterdir()):
                    raise ValueError(f"v{number}: invalid PDF-only directory")
            elif not verify_inventory(target, version.get("files", {})):
                raise ValueError(f"v{number}: source inventory mismatch")
            if any(p.is_file() and p.suffix.lower() not in {".tex", ".bib"} for p in target.rglob("*")):
                raise ValueError(f"v{number}: forbidden binary/image file")
        if s2_missing_allowed:
            result["classification"] = "references_unavailable"
        elif result["withdrawn_versions"]:
            if record.get("success") or record.get("source_success"):
                raise ValueError("Withdrawal incorrectly marked as downloaded success")
            result["classification"] = "verified_exception"
        # All hashes/inventories/metadata and reference consistency were checked
        # above; do not reread the entire Drive tree a second time here.
        elif record.get("success") and record.get("source_success"):
            result.update(classification="full_success", data_download_success=True)
        else:
            raise ValueError("Not a verified complete publication")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        errors.append(str(error))
    return result


def account_owner(student_id, expected_ids, assessments):
    """Close only an exact, duplicate-free manifest with no pending assessment."""
    ids = list(expected_ids)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Expected manifest must be nonempty and duplicate-free")
    rows = list(assessments)
    counts = Counter(row["arxiv_id"] for row in rows)
    expected = set(ids)
    missing = sorted(expected - counts.keys())
    outside = sorted(counts.keys() - expected)
    duplicates = sorted(aid for aid, count in counts.items() if count != 1)
    classes = Counter(row.get("classification", "pending") for row in rows)
    consistent = all(
        not row.get("reasons") and (
            (row.get("classification") == "full_success" and row.get("data_download_success") is True
             and not row.get("withdrawn_versions"))
            or (row.get("classification") == "verified_exception" and row.get("data_download_success") is False
                and bool(row.get("withdrawn_versions")))
        ) for row in rows
    )
    closed = (not missing and not outside and not duplicates and len(rows) == len(ids)
              and consistent and classes["full_success"] + classes["verified_exception"] == len(ids))
    return {
        "student_id": str(student_id), "audited_at": utc_now(),
        "expected_count": len(ids), "assessed_count": len(rows),
        "manifest_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
        "counts": dict(classes), "missing_ids": missing, "outside_ids": outside,
        "duplicate_ids": duplicates, "collection_closed": closed,
        "state": ("complete_with_verified_exceptions" if classes["verified_exception"] else "complete") if closed else "incomplete",
        "note": "Verified exceptions preserve IDs and evidence; they are not downloaded successes.",
        "records": rows,
    }
