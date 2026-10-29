"""
arXiv API metadata discovery and secure LaTeX source downloader with figure stripping.
"""

import gzip
import os
import re
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import arxiv
import requests

from .rate_limiter import arxiv_limiter

EXPORT_SRC_BASE = "https://export.arxiv.org/src/"
FIGURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".bmp", ".tiff", ".svg", ".ps"}


class ArxivCrawler:
    """Handles arXiv metadata retrieval and source file extraction."""

    def __init__(self, contact_email: Optional[str] = None):
        self.email = contact_email or os.getenv("ARXIV_CONTACT_EMAIL", "thongpham796@gmail.com")
        self.user_agent = f"FIT-HCMUS-IDS-Group13/1.0 (contact: {self.email})"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self.api_client = arxiv.Client(
            page_size=100,
            delay_seconds=3.0,
            num_retries=3,
        )

    def fetch_metadata(self, arxiv_id: str) -> Optional[Tuple[Dict[str, Any], List[int]]]:
        """
        Query arXiv API for metadata and detect available version numbers.
        Returns: (metadata_dict, list_of_versions)
        """
        clean_id = arxiv_id.split("v")[0]
        search = arxiv.Search(id_list=[clean_id])

        arxiv_limiter.wait()
        try:
            results = list(self.api_client.results(search))
            if not results:
                return None

            paper = results[0]

            # Detect versions from paper.entry_id suffix (e.g. .../2508.17872v3)
            latest_version = 1
            match = re.search(r"v(\d+)$", paper.entry_id)
            if match:
                latest_version = int(match.group(1))

            versions = list(range(1, max(1, latest_version) + 1))

            submission_iso = paper.published.isoformat() if paper.published else ""
            revised_iso = paper.updated.isoformat() if paper.updated else submission_iso

            revised_dates = [submission_iso]
            if revised_iso != submission_iso:
                revised_dates.append(revised_iso)

            metadata = {
                "title": paper.title.strip().replace("\n", " "),
                "authors": [a.name.strip() for a in paper.authors],
                "submission_date": submission_iso,
                "revised_dates": revised_dates,
                "venue": paper.journal_ref or paper.comment or None,
            }

            return metadata, versions

        except Exception:
            return None

    def download_and_extract_version(
        self,
        clean_id: str,
        version: int,
        target_vdir: Path,
    ) -> Dict[str, Any]:
        """
        Download source archive for a specific version, safely extract,
        remove image binaries, and delete the archive to preserve disk space.
        """
        target_vdir.mkdir(parents=True, exist_ok=True)
        version_id = f"{clean_id}v{version}"
        url = f"{EXPORT_SRC_BASE}{version_id}"

        status_info = {
            "version": version,
            "success": False,
            "is_pdf_only": False,
            "initial_bytes": 0,
            "stripped_bytes": 0,
            "saved_bytes": 0,
            "error": None,
        }

        arxiv_limiter.wait()
        temp_part = target_vdir / f"{version_id}.part"

        download_ok = False
        for attempt in range(3):
            if attempt > 0:
                arxiv_limiter.wait(extra_delay=3.0)
            try:
                with self.session.get(url, stream=True, timeout=60) as resp:
                    if resp.status_code == 404:
                        status_info["error"] = f"HTTP 404: Version {version_id} not found."
                        return status_info
                    elif resp.status_code != 200:
                        status_info["error"] = f"HTTP {resp.status_code} while fetching source."
                        continue

                    with open(temp_part, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                download_ok = True
                break
            except Exception as dl_err:
                status_info["error"] = str(dl_err)
                if temp_part.exists():
                    try:
                        temp_part.unlink()
                    except OSError:
                        pass

        if not download_ok or not temp_part.exists():
            return status_info

        try:
            # Inspect magic bytes
            with open(temp_part, "rb") as f:
                head = f.read(1024)

            # 1. Check if PDF-only
            if head.startswith(b"%PDF-"):
                status_info["is_pdf_only"] = True
                status_info["success"] = True
                if temp_part.exists():
                    temp_part.unlink()
                return status_info

            # 2. Extract archive safely
            extracted = self._safe_extract(temp_part, target_vdir)
            if not extracted:
                status_info["error"] = "Failed to extract source archive."
                if temp_part.exists():
                    temp_part.unlink()
                return status_info

            # 3. Measure size before figure filter
            initial_size = sum(f.stat().st_size for f in target_vdir.rglob("*") if f.is_file() and f != temp_part)
            status_info["initial_bytes"] = initial_size

            # 4. Filter and remove all figure binaries
            for f in list(target_vdir.rglob("*")):
                if f.is_file() and f != temp_part and f.suffix.lower() in FIGURE_EXTENSIONS:
                    try:
                        f.unlink()
                    except OSError:
                        pass

            # 5. Measure final size after stripping
            final_size = sum(f.stat().st_size for f in target_vdir.rglob("*") if f.is_file() and f != temp_part)
            status_info["stripped_bytes"] = final_size
            status_info["saved_bytes"] = max(0, initial_size - final_size)
            status_info["success"] = True

        except Exception as e:
            status_info["error"] = str(e)

        finally:
            # Delete temporary archive
            if temp_part.exists():
                try:
                    temp_part.unlink()
                except OSError:
                    pass

        return status_info

    def _safe_extract(self, archive_path: Path, dest_dir: Path) -> bool:
        """Extract tar/gz safely preventing directory traversal and symlinks."""
        # Try tar extraction (tar.gz or uncompressed tar)
        try:
            if tarfile.is_tarfile(archive_path):
                with tarfile.open(archive_path, "r:*") as tar:
                    resolved_dest = dest_dir.resolve()
                    for member in tar.getmembers():
                        # Prevent traversal attacks
                        target_path = (resolved_dest / member.name).resolve()
                        if not str(target_path).startswith(str(resolved_dest)):
                            continue  # skip suspicious members
                        tar.extract(member, path=resolved_dest)
                return True
        except Exception:
            pass

        # Try plain gzip decompress (single .tex.gz file)
        try:
            with gzip.open(archive_path, "rb") as gz_in:
                content = gz_in.read()
                out_file = dest_dir / "main.tex"
                with open(out_file, "wb") as f_out:
                    f_out.write(content)
                return True
        except Exception:
            pass

        # Try plain text (sometimes plain uncompressed tex)
        try:
            with open(archive_path, "rb") as f_in:
                data = f_in.read()
            if b"\\documentclass" in data or b"\\begin{document}" in data:
                with open(dest_dir / "main.tex", "wb") as f_out:
                    f_out.write(data)
                return True
        except Exception:
            pass

        return False
