"""One local, provenance-aware cache; resolve unique arXiv IDs in batches."""

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from ..discovery import parse_atom, to_arxiv_id
from ..storage import atomic_json
from .http import RequestFailure, get_response
from .rate_limiter import arxiv_limiter


class ReferenceDates:
    def __init__(self, path, metadata=None):
        self.path = Path(path)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        # Untyped legacy values are retained as candidates, not silently
        # promoted to verified dates. They can be re-resolved in one batch.
        self.values = loaded if loaded.get("schema_version") == 3 else {"schema_version": 3, "dates": {}}
        self.pending = self.values.setdefault("pending", {})
        for aid, record in (metadata or {}).items():
            date = record.get("submission_date")
            if date:
                self.values["dates"].setdefault(aid, {"date": date, "source": "arxiv_atom_published"})

    def enqueue(self, references):
        """Combine unique missing IDs from adjacent S2 batches before querying."""
        for key, value in references.items():
            aid = to_arxiv_id(key)
            if aid in self.values["dates"]:
                continue
            if value.get("submission_date") and value.get("date_source") in {"arxiv_atom", "arxiv_atom_published"}:
                continue
            if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})", aid):
                self.pending.setdefault(aid, 0)

    def remember(self, references):
        """Reuse already-proven arXiv dates, never S2 publicationDate guesses."""
        for key, value in references.items():
            if value.get("date_source") not in {"arxiv_atom", "arxiv_atom_published"}:
                continue
            try:
                date = value["submission_date"]
                datetime.fromisoformat(date.replace("Z", "+00:00"))
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            self.values["dates"].setdefault(to_arxiv_id(key), {"date": date, "source": value["date_source"]})

    def enrich(self, references, crawler):
        dates = self.values["dates"]
        for key, value in references.items():
            cached = dates.get(to_arxiv_id(key))
            # A known S2 publication date is not evidence of arXiv submission.
            if value.get("date_source") not in {"arxiv_atom", "arxiv_atom_published"}:
                value["submission_date"] = None
            if cached:
                value.update(submission_date=cached["date"], date_source=cached["source"])
        self.enqueue(references)
        missing = sorted({to_arxiv_id(k) for k, v in references.items() if not v.get("submission_date")})
        # Fill batches with backlog too, rather than issuing one sparse request
        # per publication. Bound work so a huge reference list cannot monopolize
        # the paper service; unresolved dates remain explicitly incomplete.
        for _ in range(2):
            now = time.time()
            due = [aid for aid in missing if aid in self.pending and self.pending[aid] <= now]
            due += [aid for aid, next_at in self.pending.items() if next_at <= now and aid not in due and aid not in dates]
            batch = due[:100]
            if not batch:
                break
            for aid in batch:
                self.pending[aid] = now + 300
            try:
                with get_response(crawler.session, "https://export.arxiv.org/api/query", arxiv_limiter,
                                  params={"id_list": ",".join(batch), "max_results": len(batch)},
                                  events=crawler.events, attempts=1) as response:
                    records, _ = parse_atom(response.content)
                for record in records:
                    date = record.get("submission_date")
                    if date and record["arxiv_id"] in batch:
                        datetime.fromisoformat(date.replace("Z", "+00:00"))
                        dates[record["arxiv_id"]] = {"date": date, "source": "arxiv_atom_published"}
                        self.pending.pop(record["arxiv_id"], None)
            except RequestFailure as error:
                for aid in batch:
                    self.pending[aid] = max(now + 300, time.time() + error.retry_after)
                break
            except (ValueError, ET.ParseError):
                break
        for key, value in references.items():
            cached = dates.get(to_arxiv_id(key))
            if cached:
                value.update(submission_date=cached["date"], date_source=cached["source"])
        atomic_json(self.path, self.values)
        return all(v.get("submission_date") and v.get("date_source") in {"arxiv_atom", "arxiv_atom_published"}
                   for v in references.values())
