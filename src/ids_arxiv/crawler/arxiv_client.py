"""Version-aware arXiv metadata and bounded text-only source extraction."""

import gzip
import os
import re
import shutil
import tarfile
import tempfile
import xml.etree.ElementTree as ET
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
            # arXivRaw records expose every version's actual date. Do not invent
            # intermediate revision timestamps from the Atom first/last dates.
            with get_response(
                self.session,
                "https://oaipmh.arxiv.org/oai",
                arxiv_limiter,
                params={
                    "verb": "GetRecord",
                    "identifier": f"oai:arXiv.org:{clean_id}",
                    "metadataPrefix": "arXivRaw",
                },
                events=self.events,
            ) as response:
                root = ET.fromstring(response.content)
            error = root.find("{*}error")
            if error is not None:
                raise RequestFailure(
                    f"OAI error {error.get('code')}: {error.text}", retryable=False
                )
            version_dates = {}
            for node in root.findall(".//{*}version"):
                version = int(node.get("version", "v0").lstrip("v"))
                date = node.findtext("{*}date")
                if version and date:
                    version_dates[version] = normalize_date(date.strip())
            latest = max(int(record["latest_version"]), max(version_dates, default=0))
            if set(version_dates) != set(range(1, latest + 1)):
                raise RequestFailure(
                    "OAI version dates are incomplete; retry metadata instead of fabricating dates"
                )
            metadata = {
                "title": record["title"],
                "authors": record["authors"],
                "submission_date": version_dates[1],
                "revised_dates": [version_dates[v] for v in sorted(version_dates)],
                "version_dates": {str(k): v for k, v in version_dates.items()},
                "venue": record.get("venue"),
                "metadata_source": "arxiv_atom+oai_arXivRaw",
                "license": root.findtext(".//{*}license"),
            }
            return metadata, list(range(1, latest + 1))
        except (RequestFailure, ET.ParseError, ValueError, KeyError) as error:
            self.last_error = str(error)
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
        }
        # Extraction happens in a new sibling staging directory, never in an
        # already validated version. Temporary cleanup is confined to this path.
        with tempfile.TemporaryDirectory(
            prefix=f".v{version}-", dir=target_vdir.parent
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
                status["initial_bytes"] = sum(
                    p.stat().st_size for p in extracted.rglob("*") if p.is_file()
                )
                for path in extracted.rglob("*"):
                    if not path.is_file():
                        continue
                    remove = path.suffix.lower() in FIGURE_EXTENSIONS
                    if not remove:
                        try:
                            sample = path.read_bytes()[:8192]
                            if b"\x00" in sample:
                                remove = True
                            else:
                                sample.decode("utf-8")
                        except UnicodeDecodeError:
                            # Preserve common legacy TeX encodings, but reject
                            # opaque binary by checking control-byte density.
                            remove = sum(c < 32 and c not in (9, 10, 12, 13) for c in sample) > max(
                                2, len(sample) // 100
                            )
                    if remove:
                        path.unlink()
                inventory = file_inventory(extracted)
                if not inventory:
                    raise ValueError("Source contains no usable text files")
                target_vdir.mkdir(exist_ok=True)
                # Remove old version files only after a replacement is ready.
                # Preserve a backup for recovery; it remains outside vN/.
                if any(target_vdir.iterdir()):
                    backup = target_vdir.with_name(f".previous-{target_vdir.name}")
                    if backup.exists():
                        shutil.rmtree(backup, ignore_errors=True)
                    target_vdir.rename(backup)
                else:
                    target_vdir.rmdir()
                extracted.rename(target_vdir)
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
                    error=str(error), state="retryable_error" if error.retryable else "not_found"
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
                        if member.isdir():
                            path.mkdir(parents=True, exist_ok=True)
                        else:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            with archive.extractfile(member) as source, path.open("wb") as output:
                                shutil.copyfileobj(source, output, 65536)
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
            return True
        except (OSError, EOFError, tarfile.TarError, ValueError):
            return False
