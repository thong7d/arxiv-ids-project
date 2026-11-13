"""Version-aware arXiv metadata and bounded text-only source extraction."""

import gzip
import os
import re
import shutil
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from ..discovery import parse_atom, to_arxiv_id
from ..storage import file_inventory, sha256_file
from .http import RequestFailure, get_response
from .rate_limiter import arxiv_limiter

EXPORT_SRC_BASE = "https://export.arxiv.org/src/"
FIGURE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".eps",
    ".bmp",
    ".tiff",
    ".svg",
    ".ps",
    ".gif",
    ".webp",
}
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXTRACTED_BYTES = 1024 * 1024 * 1024
MAX_MEMBERS = 10000
SOURCE_SUFFIXES = {".tex", ".bib"}
SOURCE_POLICY = "original_tex_bib_only_v1"


def normalize_date(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()


class ArxivCrawler:
    def __init__(self, contact_email=None, metadata_cache=None, events=None):
        self.email = contact_email or os.getenv("ARXIV_CONTACT_EMAIL", "thongpham796@gmail.com")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"FIT-HCMUS-IDS-Group13/2.0 (contact: {self.email})"
        self.metadata_cache = metadata_cache or {}
        self.events = events
        self.last_error = None

    def prefetch_metadata(self, ids):
        """Refresh a target-only Atom batch; never trust an old discovery as fresh."""
        ids = list(dict.fromkeys(to_arxiv_id(aid) for aid in ids))
        now = time.time()
        missing = [aid for aid in ids if not 0 <= now - self.metadata_cache.get(aid, {}).get("atom_fetched_epoch", 0) < 1800]
        updated = 0
        for start in range(0, len(missing), 100):
            batch = missing[start:start + 100]
            try:
                with get_response(self.session, "https://export.arxiv.org/api/query", arxiv_limiter,
                                  params={"id_list": ",".join(batch), "max_results": len(batch)},
                                  timeout=(10, 25), attempts=1, events=self.events,
                                  defer_on_rate_limit=True) as response:
                    records, _ = parse_atom(response.content)
                for record in records:
                    aid = record["arxiv_id"]
                    old = self.metadata_cache.get(aid, {})
                    if aid in batch and int(record.get("latest_version") or 1) >= int(old.get("latest_version") or 1):
                        self.metadata_cache[aid] = {**record, "atom_fetched_epoch": time.time(),
                                                    "version_metadata": old.get("version_metadata", {})}
                        updated += 1
            except (RequestFailure, ET.ParseError, ValueError, KeyError):
                break  # Per-paper authoritative fallback remains available.
        snapshots = self.prefetch_version_metadata(ids)
        return {"requested": len(missing), "updated": updated + snapshots}

    def prefetch_version_metadata(self, ids):
        """Batch actual versioned Atom entries, not copies of the latest title."""
        wanted = {}
        for aid in ids:
            record = self.metadata_cache.get(aid, {})
            latest = int(record.get("latest_version") or 1)
            versions = record.setdefault("version_metadata", {})
            if 0 <= time.time() - record.get("atom_fetched_epoch", 0) < 1800:
                versions[str(latest)] = {k: v for k, v in record.items() if k != "version_metadata"}
            for version in range(1, latest + 1):
                if str(version) not in versions:
                    wanted[f"{aid}v{version}"] = (aid, version)
        updated = 0
        keys = list(wanted)
        for start in range(0, len(keys), 100):
            batch = keys[start:start + 100]
            try:
                with get_response(self.session, "https://export.arxiv.org/api/query", arxiv_limiter,
                                  params={"id_list": ",".join(batch), "max_results": len(batch)},
                                  timeout=(10, 25), attempts=1, events=self.events, defer_on_rate_limit=True) as response:
                    records, _ = parse_atom(response.content)
                for row in records:
                    key = f"{row['arxiv_id']}v{int(row['latest_version'])}"
                    if key in wanted:
                        aid, version = wanted[key]
                        self.metadata_cache[aid].setdefault("version_metadata", {})[str(version)] = row
                        updated += 1
            except (RequestFailure, ET.ParseError, ValueError, KeyError, TypeError):
                break
        return updated

    def fetch_metadata(self, arxiv_id):
        clean_id = to_arxiv_id(arxiv_id)
        self.last_error = None
        try:
            record = self.metadata_cache.get(clean_id)
            if not record:
                with get_response(
                    self.session,
                    "https://export.arxiv.org/api/query",
                    arxiv_limiter,
                    params={"id_list": clean_id},
                    events=self.events,
                ) as response:
                    records, _ = parse_atom(response.content)
                if not records:
                    raise RequestFailure("Publication absent from arXiv API", 404, False)
                record = records[0]
                record["atom_fetched_epoch"] = time.time()
                self.metadata_cache[clean_id] = record
            self.prefetch_version_metadata([clean_id])
            version_metadata = record.get("version_metadata", {})
            version_dates = {}
            date_sources = {}
            license_text = None
            metadata_source = "arxiv_atom+oai_arXivRaw"
            atom_latest = int(record.get("latest_version") or 1)
            for number, snapshot in version_metadata.items():
                date = snapshot.get("submission_date") if int(number) == 1 else snapshot.get("latest_updated")
                if date:
                    version_dates[int(number)] = normalize_date(date)
                    date_sources[int(number)] = "arxiv_atom_published" if int(number) == 1 else "arxiv_atom_version_updated"
            recent_atom = (0 <= time.time() - record.get("atom_fetched_epoch", 0) < 1800
                           and atom_latest <= 2 and record.get("submission_date")
                           and (atom_latest == 1 or record.get("latest_updated")))
            # Recent Atom supplies every date for v1/v2; older or more
            # complex records still require authoritative OAI/versioned queries.
            if not recent_atom and set(version_dates) != set(range(1, atom_latest + 1)):
                try:
                    with get_response(
                        self.session,
                        "https://oaipmh.arxiv.org/oai",
                        arxiv_limiter,
                        params={
                            "verb": "GetRecord",
                            "identifier": f"oai:arXiv.org:{clean_id}",
                            "metadataPrefix": "arXivRaw",
                        },
                        timeout=(5, 10),
                        attempts=1,
                        events=self.events,
                    ) as response:
                        root = ET.fromstring(response.content)
                    error = root.find("{*}error")
                    if error is None:
                        for node in root.findall(".//{*}version"):
                            version = int(node.get("version", "v0").lstrip("v"))
                            date = node.findtext("{*}date")
                            if version and date:
                                version_dates[version] = normalize_date(date.strip())
                                date_sources[version] = "oai_arXivRaw"
                        license_text = root.findtext(".//{*}license")
                except (RequestFailure, ET.ParseError, ValueError, KeyError):
                    pass

            latest = max(int(record.get("latest_version") or 1), max(version_dates, default=0))
            sub_date = normalize_date(record["submission_date"]) if record.get("submission_date") else None
            upd_date = normalize_date(record["latest_updated"]) if record.get("latest_updated") else (sub_date if latest == 1 else None)
            if 1 not in version_dates and sub_date:
                version_dates[1] = sub_date
                date_sources[1] = "arxiv_atom_published"
            if latest not in version_dates and upd_date:
                version_dates[latest] = upd_date
                date_sources[latest] = "arxiv_atom_updated"
            missing = [v for v in range(1, latest + 1) if v not in version_dates]
            # The API accepts versioned IDs. Retrieve the actual updated date
            # for each missing revision; never copy the last revision date.
            for start in range(0, len(missing), 100):
                batch = missing[start:start + 100]
                try:
                    with get_response(self.session, "https://export.arxiv.org/api/query",
                                      arxiv_limiter, params={"id_list": ",".join(f"{clean_id}v{v}" for v in batch),
                                                             "max_results": len(batch)},
                                      events=self.events, attempts=1) as response:
                        entries, _ = parse_atom(response.content)
                    for entry in entries:
                        v = int(entry["latest_version"])
                        if entry["arxiv_id"] == clean_id and v in batch and entry.get("latest_updated"):
                            version_dates[v] = normalize_date(entry["latest_updated"])
                            date_sources[v] = "arxiv_atom_version_updated"
                except (RequestFailure, ET.ParseError, ValueError, KeyError):
                    continue
            if "oai_arXivRaw" not in date_sources.values():
                metadata_source = "arxiv_atom_recent_batch" if recent_atom else "arxiv_atom_fallback"

            metadata = {
                "title": record["title"],
                "authors": record["authors"],
                "submission_date": version_dates.get(1, sub_date),
                "revised_dates": [version_dates[v] for v in sorted(version_dates) if v > 1 and version_dates[v]],
                "version_dates": {str(k): v for k, v in version_dates.items() if v},
                "version_date_sources": {str(k): v for k, v in date_sources.items()},
                "metadata_dates_complete": set(version_dates) == set(range(1, latest + 1)),
                "missing_version_dates": [v for v in range(1, latest + 1) if v not in version_dates],
                "metadata_quality_version": 3,
                "version_metadata": version_metadata,
                "version_metadata_complete": all(str(v) in version_metadata for v in range(1, latest + 1)),
                "atom_fetched_epoch": record.get("atom_fetched_epoch"),
                "venue": record.get("venue"),
                "metadata_source": metadata_source,
                "license": license_text,
            }
            return metadata, list(range(1, latest + 1))
        except (RequestFailure, ET.ParseError, ValueError, KeyError) as error:
            self.last_error = str(error)
            self.last_retry_epoch = time.time() + max(120, getattr(error, "retry_after", 0))
            return None

    def download_and_extract_version(self, clean_id, version, target_vdir):
        target_vdir = Path(target_vdir)
        target_vdir.parent.mkdir(parents=True, exist_ok=True)
        status = {
            "version": version,
            "success": False,
            "state": "retryable_error",
            "is_pdf_only": False,
            "initial_bytes": 0,
            "stripped_bytes": 0,
            "saved_bytes": 0,
            "error": None,
            "files": {},
            "source_policy": SOURCE_POLICY,
        }
        # Extraction happens in a local staging directory on the local SSD,
        # never directly inside Google Drive FUSE. This prevents uploading
        # tens of megabytes of raw binaries and images that get deleted immediately,
        # which throttles and crashes the Colab Google Drive FUSE client.
        staging_dir = Path(tempfile.gettempdir()) / "ids_staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".v{version}-", dir=staging_dir
        ) as temporary:
            staging = Path(temporary)
            archive = staging / "source.part"
            extracted = staging / "text"
            extracted.mkdir()
            try:
                status["transfer_requests"] = self._download_source(
                    f"{EXPORT_SRC_BASE}{clean_id}v{version}", archive)
                status["source_sha256"] = sha256_file(archive)
                with archive.open("rb") as handle:
                    head = handle.read(1024)
                if head.startswith(b"%PDF-"):
                    with archive.open("rb") as handle:
                        handle.seek(max(0, archive.stat().st_size - 2048))
                        if b"%%EOF" not in handle.read():
                            raise ValueError("Incomplete PDF-only source: EOF marker absent")
                    status.update(
                        success=True,
                        state="pdf_only",
                        is_pdf_only=True,
                        downloaded_bytes=archive.stat().st_size,
                    )
                    target_vdir.mkdir(exist_ok=True)
                    return status
                if not self._safe_extract(archive, extracted):
                    raise ValueError("Unsupported, unsafe or corrupt source archive")
                status["initial_bytes"] = self.last_extraction_stats["initial_bytes"]
                inventory = file_inventory(extracted)
                if not inventory:
                    # Valid PDF/Word/other non-TeX versions remain explicitly
                    # empty; never turn an HTML error page into an empty source.
                    target_vdir.mkdir(parents=True, exist_ok=True)
                    if any(target_vdir.iterdir()):
                        raise ValueError("Non-TeX version has stale source files; preserve for audit")
                    status.update(success=True, state="non_tex_source", empty_reason="valid_archive_without_tex_or_bib",
                                  downloaded_bytes=archive.stat().st_size, saved_bytes=status["initial_bytes"])
                    return status
                target_vdir.mkdir(parents=True, exist_ok=True)
                # Clear target_vdir of any stale files safely
                for old_f in target_vdir.glob("*"):
                    if old_f.is_file():
                        old_f.unlink()
                    elif old_f.is_dir():
                        shutil.rmtree(old_f, ignore_errors=True)
                # Copy clean stripped text-only files from local SSD staging to target_vdir
                for path in extracted.rglob("*"):
                    if path.is_file():
                        dest = target_vdir / path.relative_to(extracted)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, dest)
                status.update(
                    success=True,
                    state="downloaded",
                    files=inventory,
                    stripped_bytes=sum(p["bytes"] for p in inventory.values()),
                    downloaded_bytes=archive.stat().st_size,
                )
                status["saved_bytes"] = status["initial_bytes"] - status["stripped_bytes"]
            except RequestFailure as error:
                status.update(
                    error=str(error), state="retryable_error" if error.retryable else "not_found",
                    next_retry_epoch=time.time() + (max(60, error.retry_after) if error.retryable else 86400),
                )
            except (requests.RequestException, ValueError, OSError) as error:
                status["error"] = f"{type(error).__name__}: {error}"
        return status

    def _download_source(self, url, archive):
        """Keep an interrupted prefix and request bounded continuation ranges.

        A 200 response to a Range request RESTARTS the file; it is never appended.
        Content-Range and validators protect against mixing two representations.
        """
        position, total, validator, stalls = 0, None, None, 0
        validator_key = None
        for transfer in range(1024):
            headers = {"Accept-Encoding": "identity"}
            if position:
                headers["Range"] = f"bytes={position}-"
                if validator:
                    headers["If-Range"] = validator
            before = position
            try:
                with get_response(self.session, url, arxiv_limiter, stream=True,
                                  headers=headers, success_statuses=(200, 206), events=self.events) as response:
                    if response.status_code == 206:
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                        if (not match or int(match[1]) != position
                                or not position <= int(match[2]) < int(match[3])):
                            raise ValueError("Invalid continuation Content-Range")
                        incoming_total = int(match[3])
                        if total is not None and total != incoming_total:
                            raise ValueError("Source changed while resuming")
                        total = incoming_total
                        mode = "ab" if position else "wb"
                    else:
                        position = 0
                        total_header = response.headers.get("Content-Length")
                        total = int(total_header) if total_header else None
                        mode = "wb"
                        validator_key = "Last-Modified" if response.headers.get("Last-Modified") else "ETag"
                        validator = response.headers.get(validator_key)
                    if total is not None and total > MAX_ARCHIVE_BYTES:
                        raise ValueError("Archive exceeds configured size limit")
                    # Observed arXiv ETags differ between selected ranges.
                    # ETag is opaque (RFC 9110 8.8.3), not a promised body hash.
                    # Compare the same stable Last-Modified field when available.
                    if validator_key is None:
                        validator_key = "Last-Modified" if response.headers.get("Last-Modified") else "ETag"
                    new_validator = response.headers.get(validator_key)
                    if response.status_code == 206 and validator and new_validator and validator != new_validator:
                        raise ValueError("Source validator changed while resuming")
                    validator = new_validator or validator
                    with archive.open(mode) as handle:
                        for chunk in response.iter_content(65536):
                            position += len(chunk)
                            if position > MAX_ARCHIVE_BYTES or (total is not None and position > total):
                                raise ValueError("Source exceeded declared size")
                            handle.write(chunk)
                    if total is None or position == total:
                        if not position:
                            raise ValueError("Empty source response")
                        return transfer + 1
            except requests.RequestException as error:
                if self.events:
                    self.events({"kind": "transfer_error", "url": url,
                                 "error": type(error).__name__, "retained_bytes": position})
            if position <= before:
                stalls += 1
                if stalls >= 4:
                    raise RequestFailure("Source server did not make resumable download progress")
                arxiv_limiter.wait(extra_delay=min(60, 2 ** stalls))
            else:
                stalls = 0
        raise RequestFailure("Source transfer request budget exhausted")

    def _safe_extract(self, archive_path, dest_dir):
        self.last_extraction_stats = {"initial_bytes": 0, "source_policy": SOURCE_POLICY}
        try:
            dest_dir = Path(dest_dir).resolve()
            # Read gzip through EOF to verify its CRC/trailer before extraction.
            # A valid tar header alone cannot establish transfer completeness.
            with Path(archive_path).open("rb") as handle:
                compressed = handle.read(2) == b"\x1f\x8b"
            if compressed:
                with gzip.open(archive_path, "rb") as handle:
                    expanded = 0
                    while chunk := handle.read(65536):
                        expanded += len(chunk)
                        if expanded > MAX_EXTRACTED_BYTES:
                            return False
            if tarfile.is_tarfile(archive_path):
                with tarfile.open(archive_path, "r:*") as archive:
                    total = count = 0
                    for member in archive:
                        count += 1
                        total += member.size
                        path = (dest_dir / member.name).resolve()
                        if (
                            count > MAX_MEMBERS
                            or total > MAX_EXTRACTED_BYTES
                            or member.size < 0
                            or not path.is_relative_to(dest_dir)
                            or member.issym()
                            or member.islnk()
                            or not (member.isfile() or member.isdir())
                        ):
                            return False
                        if member.isfile() and path.suffix.lower() in SOURCE_SUFFIXES:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            with archive.extractfile(member) as source, path.open("wb") as output:
                                shutil.copyfileobj(source, output, 65536)
                    self.last_extraction_stats["initial_bytes"] = total
                return True
            if zipfile.is_zipfile(archive_path):
                with zipfile.ZipFile(archive_path) as archive:
                    entries = archive.infolist()
                    if len(entries) > MAX_MEMBERS or sum(v.file_size for v in entries) > MAX_EXTRACTED_BYTES:
                        return False
                    for entry in entries:
                        # ZIP paths use '/', but reject Windows separators too.
                        if "\\" in entry.filename:
                            return False
                        path = (dest_dir / entry.filename).resolve()
                        mode = entry.external_attr >> 16
                        if not path.is_relative_to(dest_dir) or mode & 0o170000 == 0o120000:
                            return False
                        if not entry.is_dir() and path.suffix.lower() in SOURCE_SUFFIXES:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(entry) as source, path.open("wb") as output:
                                shutil.copyfileobj(source, output, 65536)
                    if archive.testzip() is not None:
                        return False
                    self.last_extraction_stats["initial_bytes"] = sum(v.file_size for v in entries)
                return True
            with Path(archive_path).open("rb") as handle:
                compressed = handle.read(2) == b"\x1f\x8b"
            opener = gzip.open if compressed else open
            with opener(archive_path, "rb") as handle:
                content = handle.read(MAX_EXTRACTED_BYTES + 1)
            if len(content) > MAX_EXTRACTED_BYTES or b"\x00" in content:
                return False
            if not (b"\\document" in content or b"\\begin" in content or b"\\input" in content):
                return False
            (dest_dir / "main.tex").write_bytes(content)
            self.last_extraction_stats["initial_bytes"] = len(content)
            return True
        except (OSError, EOFError, tarfile.TarError, zipfile.BadZipFile, ValueError, zlib.error):
            return False
