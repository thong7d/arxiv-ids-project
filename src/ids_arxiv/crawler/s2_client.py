"""Semantic Scholar references with explicit status and paged responses."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import requests

from ..discovery import to_arxiv_id, to_dir_id
from ..identity import user_agent
from ..storage import utc_now
from .http import RequestFailure, get_response
from .rate_limiter import PoliteRateLimiter, s2_limiter
from .shared_quota import SharedQuota

S2_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:"


class SemanticScholarClient:
    def __init__(self, api_key=None, events=None, deferred=False):
        self.api_key = api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip() or None
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent()
        if self.api_key:
            self.session.headers["x-api-key"] = self.api_key
        self.limiter = (SharedQuota(3.05, "s2", self.api_key or "anonymous")
                        if deferred else (PoliteRateLimiter(1.05) if self.api_key else s2_limiter))
        self.deferred = deferred
        self.events = events
        self.last_status = {"state": "pending", "success": False}
        self.last_all_references = []
        self.all_cache = {}
        self.cache = {}
        self.cache_lock = threading.Lock()
        self.prefetch_pool = None
        self.prefetch_future = None
        self.batch_attempted = set()

    def get_paper_references(self, arxiv_id, max_retries=3):
        aid = to_arxiv_id(arxiv_id)
        self.last_all_references = []
        with self.cache_lock:
            cached = self.cache.pop(aid, None)
            cached_all = self.all_cache.pop(aid, None)
        if cached:
            references, self.last_status = cached
            self.last_all_references = cached_all if cached_all is not None else []
            return references
        if self.deferred and self.prefetch_future and not self.prefetch_future.done():
            # A cached source can finish before the prefetch round trip. Give
            # that single lane a bounded chance, rather than committing an
            # incomplete publication on every fast resume.
            try:
                self.prefetch_future.result(timeout=5)
            except TimeoutError:
                self.last_status = {"state": "deferred", "success": False,
                                    "next_retry_epoch": time.time() + 10,
                                    "reason": "single_s2_lane_busy"}
                return {}
            with self.cache_lock:
                cached = self.cache.pop(aid, None)
                cached_all = self.all_cache.pop(aid, None)
            if cached:
                references, self.last_status = cached
                self.last_all_references = cached_all if cached_all is not None else []
                return references
        if self.deferred and self.limiter.ready_in() > 0:
            self.last_status = {"state": "deferred", "success": False,
                                "next_retry_epoch": time.time() + self.limiter.ready_in()}
            return {}
        refs = {}
        self.last_all_references = []
        offset = 0
        raw_count = 0
        try:
            while True:
                with get_response(
                    self.session,
                    f"{S2_BASE_URL}{to_arxiv_id(arxiv_id)}/references",
                    self.limiter,
                    params={
                        "fields": "title,authors,year,venue,externalIds,publicationDate",
                        "offset": offset,
                        "limit": 1000,
                    },
                    attempts=1 if self.deferred else max_retries + 1,
                    events=self.events,
                    defer_on_rate_limit=self.deferred,
                ) as response:
                    data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                    raise ValueError("Missing Semantic Scholar references page")
                raw = [entry.get("citedPaper") for entry in data.get("data", [])]
                self.last_all_references.extend(raw)
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
                "all_references_retained": True,
                "snapshot_at": utc_now(),
            }
        except RequestFailure as error:
            if self.deferred and error.status_code == 429:
                self.limiter.defer(max(5 if self.api_key else 60, error.retry_after))
            self.last_status = {
                "state": "retryable_error"
                if error.retryable
                else ("not_indexed" if error.status_code == 404 else "rejected"),
                "success": False,
                "http_status": error.status_code,
                "error": str(error),
                "raw_count": raw_count,
                "all_references_retained": False,
                "evidence": error.evidence,
                "next_retry_epoch": time.time() + max(60, error.retry_after) if error.retryable else time.time() + 86400,
            }
        except (ValueError, KeyError) as error:
            self.last_status = {"state": "invalid_response", "success": False, "error": str(error)}
        return refs

    def prefetch(self, ids):
        """One S2 lane overlaps with source downloads; never >1 batch in flight."""
        # Heavy nested-reference batches produced persistent 429s in the live
        # Colab experiment. Keep complete paginated retrieval as the default;
        # batching is an explicit, measurable opt-in, not a correctness dependency.
        if os.getenv("IDS_S2_BATCH_PREFETCH", "0") != "1":
            return False
        if not self.deferred or self.limiter.ready_in() > 0:
            return False
        if self.prefetch_future and not self.prefetch_future.done():
            return False
        with self.cache_lock:
            remaining = [to_arxiv_id(aid) for aid in ids if to_arxiv_id(aid) not in self.cache
                         and to_arxiv_id(aid) not in self.batch_attempted][:20]
            # Missing/truncated batch results must eventually use pagination;
            # repeatedly prefetching the same ID can otherwise starve fallback.
            self.batch_attempted.update(remaining)
        if not remaining:
            return False
        self.prefetch_pool = self.prefetch_pool or ThreadPoolExecutor(max_workers=1, thread_name_prefix="s2-lane")
        self.prefetch_future = self.prefetch_pool.submit(self.get_many_references, remaining)
        return True

    def get_many_references(self, ids):
        """Batch optimization is accepted only when raw referenceCount matches.

        Truncated/missing/oversized records are NOT cached as success; their
        publication falls back to the paginated endpoint on demand.
        """
        ids = [to_arxiv_id(aid) for aid in ids]
        if not ids or len(ids) > 500:
            raise ValueError("Batch must contain 1..500 IDs")
        try:
            with get_response(self.session, "https://api.semanticscholar.org/graph/v1/paper/batch",
                              self.limiter, method="POST", json_body={"ids": ["ARXIV:" + aid for aid in ids]},
                              params={"fields": "referenceCount,references.paperId,references.title,references.authors,references.year,references.venue,references.externalIds,references.publicationDate"},
                              attempts=1, events=self.events, defer_on_rate_limit=self.deferred) as response:
                rows = response.json()
            if not isinstance(rows, list) or len(rows) != len(ids):
                return False
            for aid, row in zip(ids, rows):
                if not isinstance(row, dict) or "references" not in row:
                    continue
                raw = row["references"]
                if not isinstance(raw, list) or row.get("referenceCount") != len(raw):
                    continue
                refs = self._process_references(raw)
                status = {"state": "downloaded" if raw else "empty", "success": True,
                          "raw_count": len(raw), "arxiv_count": len(refs), "source": "s2_batch_verified_count",
                          "all_references_retained": True,
                          "snapshot_at": utc_now()}
                with self.cache_lock:
                    if len(self.cache) < 100:
                        self.cache[aid] = (refs, status)
                        self.all_cache[aid] = raw
            return True
        except RequestFailure as error:
            if self.deferred and error.status_code == 429:
                self.limiter.defer(max(5 if self.api_key else 60, error.retry_after))
            return False
        except (ValueError, KeyError):
            return False

    def _process_references(self, raw_refs):
        processed = {}
        for reference in raw_refs:
            if not isinstance(reference, dict):
                continue
            external = reference.get("externalIds") or {}
            arxiv_id = external.get("ArXiv") or external.get("arxiv")
            if not arxiv_id:
                continue
            pub_date = reference.get("publicationDate")
            processed[to_dir_id(arxiv_id)] = {
                "title": (reference.get("title") or "").strip(),
                "authors": [
                    author["name"].strip()
                    for author in reference.get("authors") or []
                    if isinstance(author, dict) and author.get("name")
                ],
                "submission_date": None,
                "publication_date": pub_date or None,
                "s2_id": reference.get("paperId") or "",
                "venue": reference.get("venue"),
                "year": reference.get("year"),
                "doi": external.get("DOI"),
                "date_source": "unknown",
            }
        return processed
