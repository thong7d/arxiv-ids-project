"""Durable publication/version checkpoints and observable crawl sessions."""

import json
import os
import time
from pathlib import Path

import pandas as pd

from ..benchmark import BenchmarkSession
from ..discovery import load_members, parse_atom, to_arxiv_id, to_dir_id
from ..storage import atomic_json, sha256_file, utc_now, verify_inventory
from ..validator import validate_raw_paper
from .arxiv_client import ArxivCrawler
from .http import RequestFailure, get_response
from .rate_limiter import arxiv_limiter
from .s2_client import SemanticScholarClient


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def valid_version(paper_dir, value):
    directory = paper_dir / f"v{value['version']}"
    if not value.get("success"):
        return False
    if value.get("state") == "pdf_only":
        return directory.is_dir() and not any(directory.iterdir())
    return verify_inventory(directory, value.get("files", {}))


def enrich_reference_dates(references, crawler, cache_path):
    cache = load_json(cache_path, {})
    missing = sorted(to_arxiv_id(key) for key in references if to_arxiv_id(key) not in cache)
    for start in range(0, len(missing), 100):
        batch = missing[start : start + 100]
        try:
            with get_response(
                crawler.session,
                "https://export.arxiv.org/api/query",
                arxiv_limiter,
                params={"id_list": ",".join(batch), "max_results": len(batch)},
                events=crawler.events,
            ) as response:
                entries, _ = parse_atom(response.content)
            for entry in entries:
                cache[entry["arxiv_id"]] = entry["submission_date"]
            atomic_json(cache_path, cache)
        except (RequestFailure, ValueError):
            break  # Unknown stays null and is retried on the next recovery pass.
    for key, value in references.items():
        date = cache.get(to_arxiv_id(key))
        value.update(submission_date=date, date_source="arxiv_atom" if date else "unknown")
    return all(value.get("submission_date") for value in references.values())


def crawl_paper(arxiv_id, output_dir, arxiv_crawler, s2_client, resume=True):
    clean_id = to_arxiv_id(arxiv_id)
    paper_dir = Path(output_dir) / to_dir_id(clean_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    status_file = paper_dir / "crawl_status.json"
    previous = load_json(status_file, {}) if resume else {}
    trusted = previous.get("schema_version") == 2
    if trusted and previous.get("success"):
        hashes_ok = all(
            (paper_dir / name).is_file() and sha256_file(paper_dir / name) == digest
            for name, digest in previous.get("checksums", {}).items()
        )
        if (
            previous.get("checksums")
            and hashes_ok
            and previous.get("versions")
            and all(valid_version(paper_dir, value) for value in previous["versions"])
            and validate_raw_paper(paper_dir)["valid"]
        ):
            return {**previous, "cache_hit": True}

    record = {
        "schema_version": 2,
        "arxiv_id": clean_id,
        "dir_name": paper_dir.name,
        "success": False,
        "source_success": False,
        "cache_hit": False,
        "started_at": utc_now(),
        "attempt_count": previous.get("attempt_count", 0) + 1,
        "versions": previous.get("versions", []) if trusted else [],
        "references_status": {"state": "pending", "success": False},
        "error": None,
    }
    started = time.monotonic()
    atomic_json(status_file, record)
    metadata = load_json(paper_dir / "metadata.json") if trusted else None
    expected = previous.get("expected_versions") if trusted else None
    if not metadata or not expected:
        result = arxiv_crawler.fetch_metadata(clean_id)
        if result is None:
            record.update(
                error=getattr(arxiv_crawler, "last_error", None) or "Metadata unavailable",
                elapsed_seconds=time.monotonic() - started,
            )
            atomic_json(status_file, record)
            return record
        metadata, expected = result
        atomic_json(paper_dir / "metadata.json", metadata)
    record["expected_versions"] = expected
    version_map = {value["version"]: value for value in record["versions"]}
    for version in expected:
        old = version_map.get(version)
        if not (resume and old and valid_version(paper_dir, old)):
            version_map[version] = arxiv_crawler.download_and_extract_version(
                clean_id, version, paper_dir / f"v{version}"
            )
        record["versions"] = [version_map[v] for v in expected if v in version_map]
        atomic_json(status_file, record)
    record["source_success"] = bool(expected) and all(
        valid_version(paper_dir, version_map[v]) for v in expected
    )

    refs_path = paper_dir / "references.json"
    ref_status = previous.get("references_status", {}) if trusted else {}
    refs_unchanged = (
        previous.get("checksums", {}).get("references.json")
        and refs_path.exists()
        and sha256_file(refs_path) == previous["checksums"]["references.json"]
    )
    if resume and ref_status.get("success") and refs_unchanged:
        references = load_json(refs_path, {})
    else:
        references = s2_client.get_paper_references(clean_id)
        ref_status = s2_client.last_status.copy()
    dates_complete = (
        enrich_reference_dates(
            references, arxiv_crawler, Path(output_dir).parent / "reference_dates.json"
        )
        if ref_status.get("success")
        else False
    )
    ref_status["dates_complete"] = dates_complete
    atomic_json(refs_path, references)
    record["references_status"] = ref_status
    record.update(
        num_references=len(references),
        total_initial_bytes=sum(v.get("initial_bytes", 0) for v in record["versions"]),
        total_stripped_bytes=sum(v.get("stripped_bytes", 0) for v in record["versions"]),
        total_saved_bytes=sum(v.get("saved_bytes", 0) for v in record["versions"]),
        checksums={
            name: sha256_file(paper_dir / name) for name in ("metadata.json", "references.json")
        },
    )
    validation = validate_raw_paper(paper_dir)
    record["validation"] = validation
    record["success"] = bool(
        record["source_success"]
        and ref_status.get("success")
        and dates_complete
        and validation["valid"]
    )
    record.update(ended_at=utc_now(), elapsed_seconds=time.monotonic() - started)
    if not record["success"]:
        record["error"] = (
            "Incomplete sources, references, reference dates or validation; see component states"
        )
    atomic_json(status_file, record)
    return record


def run_crawling_pipeline(
    manifest_path,
    output_dir,
    limit=None,
    pilot_mode=False,
    members_config=None,
    resume=True,
    student_id=None,
    max_seconds=None,
):
    manifest_path, output_dir = Path(manifest_path), Path(output_dir)
    frame = pd.read_parquet(manifest_path)
    if student_id:
        frame = frame[frame["owner_student_id"].astype(str) == str(student_id)]
    if frame.empty:
        return {"total_attempted": 0, "success_count": 0}
    if pilot_mode:
        frame = frame.groupby("owner_student_id", group_keys=False).head(10)
    if limit is not None:
        frame = frame.head(limit)
    if members_config:
        members = load_members(Path(members_config))
        for row in frame.itertuples():
            if not any(
                m.student_id == str(row.owner_student_id) and m.contains(row.arxiv_id)
                for m in members
            ):
                raise ValueError(f"Invalid manifest ownership for {row.arxiv_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    campaign_path = output_dir.parent / "campaign.json"
    campaign = load_json(campaign_path)
    fingerprint = sha256_file(manifest_path)
    if campaign and campaign["manifest_sha256"] != fingerprint:
        raise ValueError("Campaign manifest changed; use a new campaign directory")
    if not campaign:
        campaign = {
            "campaign_id": output_dir.parent.name,
            "manifest_sha256": fingerprint,
            "started_at": utc_now(),
            "mode": "pilot" if pilot_mode or limit else "full",
        }
        atomic_json(campaign_path, campaign)
    if campaign["mode"] == "pilot" and not (pilot_mode or limit):
        raise ValueError("A pilot directory cannot be reused as a cold-start full benchmark")
    metadata = load_json(manifest_path.parent / "discovery" / "metadata.json", {})
    summary = {
        "selected_publications": len(frame),
        "total_attempted": 0,
        "success_count": 0,
        "source_success_count": 0,
        "reference_success_count": 0,
        "cache_hits": 0,
        "campaign_id": campaign["campaign_id"],
        "failed_ids": [],
    }
    start = time.monotonic()
    with BenchmarkSession(
        output_dir.parent / "benchmark", campaign=campaign["campaign_id"]
    ) as benchmark:
        crawler = ArxivCrawler(metadata_cache=metadata, events=benchmark.event)
        s2 = SemanticScholarClient(events=benchmark.event)
        for row in frame.itertuples():
            if max_seconds is not None and time.monotonic() - start >= max_seconds:
                break
            result = crawl_paper(row.arxiv_id, output_dir, crawler, s2, resume)
            summary["total_attempted"] += 1
            summary["success_count"] += int(result["success"])
            summary["source_success_count"] += int(result.get("source_success", False))
            summary["reference_success_count"] += int(
                result.get("references_status", {}).get("success", False)
            )
            summary["cache_hits"] += int(result.get("cache_hit", False))
            if not result["success"]:
                summary["failed_ids"].append(row.arxiv_id)
            summary.update(
                updated_at=utc_now(),
                session_id=benchmark.session_id,
                elapsed_seconds=time.monotonic() - start,
            )
            atomic_json(output_dir / "crawl_summary.json", summary)
            if hasattr(os, "sync"):
                os.sync()
            if summary["total_attempted"] % 10 == 0 or not result["success"]:
                print(
                    f"Crawl {summary['total_attempted']}/{len(frame)}: "
                    f"complete={summary['success_count']} sources={summary['source_success_count']} "
                    f"references={summary['reference_success_count']} last={row.arxiv_id}",
                    flush=True,
                )
    atomic_json(output_dir.parent / f"pass-{benchmark.session_id}.json", summary)
    return summary
