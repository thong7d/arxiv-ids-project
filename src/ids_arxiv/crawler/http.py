"""Bounded, observable HTTP retries; never log request headers or secrets."""

import random
import time

import requests

from ..storage import utc_now
from .rate_limiter import retry_after_seconds


class RequestFailure(RuntimeError):
    def __init__(self, message, status_code=None, retryable=True):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def get_response(
    session, url, limiter, *, params=None, stream=False, attempts=4, events=None, timeout=(20, 90),
    headers=None, success_statuses=(200,),
):
    backoff = 0.0
    for attempt in range(attempts):
        wait_started = time.monotonic()
        limiter.wait(extra_delay=backoff)
        started = time.monotonic()
        event = {
            "timestamp": utc_now(),
            "url": url,
            "attempt": attempt + 1,
            "wait_seconds": started - wait_started,
        }
        try:
            response = session.get(url, params=params, timeout=timeout, stream=stream, headers=headers)
            event["http_status"] = response.status_code
            event["request_seconds"] = time.monotonic() - started
            if events:
                events(event)
            if response.status_code in success_statuses:
                return response
            retryable = response.status_code in {408, 429, 500, 502, 503, 504}
            backoff = max(
                retry_after_seconds(response.headers.get("Retry-After")),
                min(120.0, 2 ** (attempt + 1)) + random.random(),
                60.0 if response.status_code == 429 else 0.0,
            )
            response.close()
            if not retryable or attempt == attempts - 1:
                raise RequestFailure(
                    f"HTTP {response.status_code}", response.status_code, retryable
                )
        except requests.RequestException as error:
            event.update(error=type(error).__name__, request_seconds=time.monotonic() - started)
            if events:
                events(event)
            if attempt == attempts - 1:
                raise RequestFailure(type(error).__name__) from error
            backoff = min(120.0, 2 ** (attempt + 1)) + random.random()
    raise RequestFailure("Retry budget exhausted")
