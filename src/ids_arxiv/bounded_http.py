"""Whole HTTP connections end before a runner's UTC turn ends.

The child spools to local SSD; it never writes the corpus. Terminating a child
closes its sockets. Returning a file-backed response keeps parent RAM bounded.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from .network_schedule import configured_window
from .runtime import local_lock, runtime_id

ARXIV_HOSTS = {"export.arxiv.org", "oaipmh.arxiv.org", "arxiv.org"}


class NetworkWindowClosed(requests.RequestException):
    def __init__(self, retry_after):
        super().__init__("Waiting for this runner's arXiv UTC turn")
        self.retry_after = max(1, retry_after)


def scheduled_arxiv(session, url, limiter, *, params=None, headers=None, timeout=(20, 90), extra_delay=0, allow_partial=False):
    if urlparse(url).hostname not in ARXIV_HOSTS or not url.startswith("https://"):
        raise ValueError("Scheduled transport only accepts official HTTPS arXiv endpoints")
    window = configured_window()

    def remaining():
        state = window.status() if window else {"allowed": True, "remaining_seconds": 180}
        if not state["allowed"] or state["remaining_seconds"] < 3:
            following = window.status(time.time() + max(3, state["remaining_seconds"]))
            raise NetworkWindowClosed(following["next_epoch"] - time.time())
        return min(180, state["remaining_seconds"])

    started = time.monotonic()
    budget = remaining()
    with tempfile.TemporaryDirectory(prefix="ids13-http-") as temporary:
        body = Path(temporary) / "body"
        info = Path(temporary) / "response.json"
        payload = {"url": url, "params": params, "headers": {**dict(session.headers), **(headers or {})},
                   "timeout": timeout, "body": str(body), "info": str(info), "budget": budget,
                   "extra_delay": extra_delay, "deadline_epoch": time.time() + budget}
        try:
            completed = subprocess.run([sys.executable, "-m", "ids_arxiv.bounded_http"],
                                       input=json.dumps(payload), text=True, capture_output=True, timeout=budget + 2)
            failed = completed.returncode != 0
        except subprocess.TimeoutExpired:
            failed = True
        partial = failed and allow_partial and info.is_file() and body.is_file() and body.stat().st_size > 0
        if failed and not partial:
            if window:
                following = window.status(time.time() + 1)
                raise NetworkWindowClosed(max(60, following["next_epoch"] - time.time()))
            raise requests.Timeout("Bounded arXiv transfer deadline")
        metadata = json.loads(info.read_text())
        handle, spool = tempfile.mkstemp(prefix="ids13-response-")
        os.close(handle)
        Path(spool).unlink()
        body.replace(spool)
        response = requests.Response()
        response.status_code = metadata["status"]
        response.headers.update(metadata["headers"])
        response.url = metadata["url"]
        response.raw = open(spool, "rb")
        old_close = response.close

        def close():
            try:
                old_close()
            finally:
                response.raw.close()
                Path(spool).unlink(missing_ok=True)
        response.close = close
        fetched = metadata.get("request_started_monotonic", started)
        response.ids_wait_seconds = fetched - started
        response.ids_request_seconds = time.monotonic() - fetched
        return response


def main():
    request = json.loads(sys.stdin.read())
    url = request["url"]
    if urlparse(url).hostname not in ARXIV_HOSTS or not url.startswith("https://"):
        raise SystemExit("Unapproved upstream")
    # The actual network child owns the connection lock, even if its supervisor
    # is interrupted. Its own watchdog closes sockets at the absolute deadline.
    timer = threading.Timer(max(0, request["deadline_epoch"] - time.time()), lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    from .crawler.rate_limiter import arxiv_limiter
    connection = Path(tempfile.gettempdir()) / "ids13-arxiv-connection" / runtime_id()
    with local_lock(connection, timeout=request["budget"]):
        arxiv_limiter.wait(extra_delay=request.get("extra_delay", 0))
        window = configured_window()
        if window and not window.status()["allowed"]:
            raise SystemExit(124)
        started = time.monotonic()
        _fetch(request, started)
    timer.cancel()


def _fetch(request, started):
    with requests.get(request["url"], params=request.get("params"), headers=request["headers"],
                      timeout=tuple(request["timeout"]), stream=True, allow_redirects=False) as response:
        metadata = {"status": response.status_code, "headers": dict(response.headers),
                    "url": response.url, "request_started_monotonic": started}
        Path(request["info"]).write_text(json.dumps(metadata), encoding="utf-8")
        size = 0
        with open(request["body"], "wb") as output:
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 512 * 1024**2:
                    raise ValueError("Response exceeds source transfer budget")
                output.write(chunk)
        headers = dict(response.headers)
        # iter_content has already decoded any HTTP content encoding.
        for name in list(headers):
            if name.lower() in {"content-encoding", "transfer-encoding", "content-length"}:
                del headers[name]
        headers["Content-Length"] = str(size)
        metadata["headers"] = headers
        Path(request["info"]).write_text(json.dumps(metadata), encoding="utf-8")


if __name__ == "__main__":
    main()
