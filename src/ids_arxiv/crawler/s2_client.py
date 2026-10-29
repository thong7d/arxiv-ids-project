"""
Semantic Scholar API client for fetching paper references and external arXiv IDs.
"""

import os
from typing import Any, Dict, Optional

import requests

from ..discovery import to_dir_id
from .rate_limiter import s2_limiter

S2_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:"


class SemanticScholarClient:
    """Client for querying Semantic Scholar paper references."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip() or None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "FIT-HCMUS-IDS-Group13/1.0 (contact: thongpham796@gmail.com)"
        })
        if self.api_key:
            self.session.headers["x-api-key"] = self.api_key

    def get_paper_references(self, arxiv_id: str, max_retries: int = 3) -> Dict[str, Any]:
        """
        Query Semantic Scholar for references of a given arXiv ID.
        Returns a dict mapping ref_arxiv_id (in yymm-id format) -> ReferenceItem dict.
        """
        clean_id = arxiv_id.split("v")[0]
        url = f"{S2_BASE_URL}{clean_id}"
        params = {
            "fields": "references,references.externalIds,references.title,references.year,references.authors,references.venue"
        }

        retries = 0
        while retries <= max_retries:
            s2_limiter.wait()
            try:
                resp = self.session.get(url, params=params, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_refs = data.get("references", []) or []
                    return self._process_references(raw_refs)

                elif resp.status_code == 404:
                    # Paper not indexed yet by Semantic Scholar
                    return {}

                elif resp.status_code == 429:
                    retries += 1
                    if not self.api_key:
                        # Without API key, public pool is throttled, don't stall pipeline
                        if retries >= 1:
                            return {}
                        s2_limiter.wait(extra_delay=2.0)
                    else:
                        retry_after = 2.0 * (2 ** (retries - 1))
                        s2_limiter.wait(extra_delay=retry_after)
                    continue

                else:
                    retries += 1
                    continue

            except requests.RequestException:
                retries += 1
                s2_limiter.wait(extra_delay=3.0)

        return {}

    def _process_references(self, raw_refs: list) -> Dict[str, Any]:
        """Extract references that contain an external arXiv ID and format keys."""
        processed: Dict[str, Any] = {}
        for r in raw_refs:
            if not isinstance(r, dict):
                continue

            external_ids = r.get("externalIds") or {}
            ref_arxiv = external_ids.get("ArXiv") or external_ids.get("arxiv")
            if not ref_arxiv:
                continue

            # Format key as yymm-id
            key_id = to_dir_id(ref_arxiv)

            # Authors
            authors_data = r.get("authors") or []
            authors_list = [a.get("name", "").strip() for a in authors_data if isinstance(a, dict) and a.get("name")]

            # Year
            year_val = r.get("year")
            submission_date = f"{year_val}-01-01T00:00:00Z" if year_val else ""

            processed[key_id] = {
                "title": (r.get("title") or "").strip(),
                "authors": authors_list,
                "submission_date": submission_date,
                "s2_id": r.get("paperId") or "",
                "venue": r.get("venue") or None,
                "year": year_val,
            }

        return processed
