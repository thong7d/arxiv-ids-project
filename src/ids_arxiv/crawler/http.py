"""Bounded, observable HTTP retries; never log request headers or secrets."""

import os
import random
import time
from hashlib import sha256
from urllib.parse import urlparse

import requests

from ..bounded_http import ARXIV_HOSTS, NetworkWindowClosed, scheduled_arxiv
from ..storage import utc_now
from .rate_limiter import retry_after_seconds


class RequestFailure(RuntimeError):
    def __init__(self, message, status_code=None, retryable=True, retry_after=0, evidence=None):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after = retry_after
        self.evidence = evidence


def get_response(
    session, url, limiter, *, params=None, stream=False, attempts=4, events=None, timeout=(20, 90),
    headers=None, success_statuses=(200,),
    defer_on_rate_limit=False, method="GET", json_body=None,
):
    backoff = 0.0
    for attempt in range(attempts):
        wait_started = time.monotonic()
        scheduled = os.environ.get("IDS_NETWORK_MODE") in {"independent_utc", "exclusive"} and urlparse(url).hostname in ARXIV_HOSTS
        if not scheduled:
            limiter.wait(extra_delay=backoff)
        started = time.monotonic()
        event = {
            "timestamp": utc_now(),
            "url": url,
            "attempt": attempt + 1,
            "wait_seconds": started - wait_started,
        }
        try:
            if scheduled:
                response = scheduled_arxiv(session, url, limiter, params=params, headers=headers,
                                           timeout=timeout, extra_delay=backoff, allow_partial=stream)
                event.update(wait_seconds=response.ids_wait_seconds, request_seconds=response.ids_request_seconds)
            elif method == "GET":
                response = session.get(url, params=params, timeout=timeout, stream=stream, headers=headers)
            else:
                response = session.request(method, url, params=params, json=json_body,
                                           timeout=timeout, stream=stream, headers=headers)
            event["http_status"] = response.status_code
            if not scheduled:
                event["request_seconds"] = time.monotonic() - started
            if response.status_code >= 400:
                event["retry_after_seconds"] = retry_after_seconds(response.headers.get("Retry-After"))
            if events:
                events(event)
            if response.status_code != 429 and response.status_code < 500:
                reset = getattr(limiter, "reset_backoff", None)
                if callable(reset):
                    reset()
            if response.status_code in success_statuses:
                return response
            retryable = response.status_code in {408, 429, 500, 502, 503, 504}
            floor = 60.0
            limited = getattr(limiter, "rate_limited", None)
            if response.status_code == 429 and callable(limited):
                shared = limited(retry_after_seconds(response.headers.get("Retry-After")))
                if isinstance(shared, (int, float)):
                    floor = shared
            backoff = max(
                retry_after_seconds(response.headers.get("Retry-After")),
                min(120.0, 2 ** (attempt + 1)) + random.random(),
                floor if response.status_code == 429 else 0.0,
            )
            # Share the circuit across endpoints/processes, including single-
            # attempt date queries whose caller deliberately does not retry.
            if response.status_code == 429 and hasattr(limiter, "defer"):
                limiter.defer(backoff)
            response.close()
            if response.status_code == 429 and defer_on_rate_limit:
                raise RequestFailure("HTTP 429; deferred instead of blocking other stages", 429, True, backoff)
            if not retryable or attempt == attempts - 1:
                raise RequestFailure(
                    f"HTTP {response.status_code}", response.status_code, retryable, backoff,
                    evidence={"url": url, "http_status": response.status_code,
                              "checked_at": event["timestamp"],
                              "response_sha256": sha256(response.content).hexdigest()
                              if not stream and isinstance(response.content, (bytes, bytearray)) else None},
                )
        except NetworkWindowClosed as error:
            event.update(kind="network_window_wait", error=type(error).__name__, retry_after_seconds=error.retry_after)
            if events:
                events(event)
            raise RequestFailure("arXiv UTC window deferred", retry_after=error.retry_after) from error
        except requests.RequestException as error:
            event.update(error=type(error).__name__, request_seconds=time.monotonic() - started)
            if events:
                events(event)
            if attempt == attempts - 1:
                raise RequestFailure(type(error).__name__) from error
            backoff = min(120.0, 2 ** (attempt + 1)) + random.random()
    raise RequestFailure("Retry budget exhausted")
