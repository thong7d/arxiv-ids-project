"""Semantic Scholar references with explicit status and paged responses."""

import os

import requests

from ..discovery import to_arxiv_id, to_dir_id
from .http import RequestFailure, get_response
from .rate_limiter import PoliteRateLimiter, s2_limiter

S2_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:"


class SemanticScholarClient:
    def __init__(self, api_key=None, events=None):
        self.api_key = api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip() or None
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "FIT-HCMUS-IDS-Group13/2.0"
        if self.api_key:
            self.session.headers["x-api-key"] = self.api_key
        self.limiter = PoliteRateLimiter(1.05) if self.api_key else s2_limiter
        self.events = events
        self.last_status = {"state": "pending", "success": False}

    def get_paper_references(self, arxiv_id, max_retries=3):
        refs = {}
        offset = 0
        raw_count = 0
        try:
            while True:
                with get_response(
                    self.session,
                    f"{S2_BASE_URL}{to_arxiv_id(arxiv_id)}/references",
                    self.limiter,
                    params={
                        "fields": "title,authors,year,venue,externalIds",
                        "offset": offset,
                        "limit": 1000,
                    },
                    attempts=max_retries + 1,
                    events=self.events,
                ) as response:
                    data = response.json()
                raw = [entry.get("citedPaper") for entry in data.get("data", [])]
                raw_count += len(raw)
                refs.update(self._process_references(raw))
                next_offset = data.get("next")
                if next_offset is None:
                    break
                if int(next_offset) <= offset:
                    raise ValueError("Non-advancing Semantic Scholar pagination")
                offset = int(next_offset)
            self.last_status = {
                "state": "downloaded" if raw_count else "empty",
                "success": True,
                "raw_count": raw_count,
                "arxiv_count": len(refs),
                "error": None,
            }
        except RequestFailure as error:
            self.last_status = {
                "state": "retryable_error"
                if error.retryable
                else ("not_indexed" if error.status_code == 404 else "rejected"),
                "success": False,
                "http_status": error.status_code,
                "error": str(error),
                "raw_count": raw_count,
            }
        except (ValueError, KeyError) as error:
            self.last_status = {"state": "invalid_response", "success": False, "error": str(error)}
        return refs

    def _process_references(self, raw_refs):
        processed = {}
        for reference in raw_refs:
            if not isinstance(reference, dict):
                continue
            external = reference.get("externalIds") or {}
            arxiv_id = external.get("ArXiv") or external.get("arxiv")
            if not arxiv_id:
                continue
            processed[to_dir_id(arxiv_id)] = {
                "title": (reference.get("title") or "").strip(),
                "authors": [
                    author["name"].strip()
                    for author in reference.get("authors") or []
                    if isinstance(author, dict) and author.get("name")
                ],
                "submission_date": None,  # year is not a submission date
                "s2_id": reference.get("paperId") or "",
                "venue": reference.get("venue"),
                "year": reference.get("year"),
                "doi": external.get("DOI"),
                "date_source": "unknown",
            }
        return processed
