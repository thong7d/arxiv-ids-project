"""Authoritative withdrawal evidence; never turn a missing source into success."""

import hashlib
import re
from html.parser import HTMLParser

from ..storage import utc_now
from .http import RequestFailure, get_response
from .rate_limiter import arxiv_limiter


class VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def classify_withdrawal(html, arxiv_id, version):
    parser = VisibleHTML()
    parser.feed(html)
    text = " ".join(" ".join(parser.parts).split())
    withdrawn = bool(re.search(r"this paper has been withdrawn", text, re.I))
    no_pdf = bool(re.search(r"no PDF available", text, re.I))
    version_match = bool(re.search(rf"arXiv:\s*{re.escape(arxiv_id)}v{version}\b", text, re.I))
    return {"withdrawn_banner": withdrawn, "no_pdf_available": no_pdf,
            "version_identity_confirmed": version_match,
            "verified": withdrawn and no_pdf and version_match}


def verify_withdrawal(session, arxiv_id, version, events=None):
    url = f"https://arxiv.org/abs/{arxiv_id}v{int(version)}"
    evidence = {"arxiv_id": arxiv_id, "version": int(version), "url": url,
                "checked_at": utc_now(), "verified": False, "data_download_success": False}
    try:
        with get_response(session, url, arxiv_limiter, timeout=(10, 25), attempts=1,
                          defer_on_rate_limit=True, events=events) as response:
            content = response.content
            evidence.update(http_status=response.status_code,
                            response_sha256=hashlib.sha256(content).hexdigest(),
                            **classify_withdrawal(content.decode("utf-8", errors="replace"), arxiv_id, int(version)))
    except RequestFailure as error:
        evidence.update(http_status=error.status_code, retryable=error.retryable,
                        error=str(error))
    return evidence
