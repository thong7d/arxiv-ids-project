"""
Rate limiter module ensuring polite crawling etiquette for arXiv and Semantic Scholar APIs.
"""

import threading
import time
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional


def retry_after_seconds(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(
                0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            )
        except (TypeError, ValueError, OverflowError):
            return 0.0


class PoliteRateLimiter:
    """
    Enforces minimum interval between consecutive requests to a specific domain.
    Thread-safe and supports Retry-After headers.
    """

    def __init__(
        self,
        min_interval_seconds: float = 3.0,
        max_requests: Optional[int] = None,
        window_seconds: float = 300.0,
    ):
        self.min_interval = min_interval_seconds
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.last_request_time = None
        self._requests = deque()
        self._lock = threading.Lock()

    def wait(self, extra_delay: Optional[float] = None) -> None:
        with self._lock:
            now = time.monotonic()
            while self._requests and self._requests[0] <= now - self.window_seconds:
                self._requests.popleft()
            delay = (
                0.0
                if self.last_request_time is None
                else max(0.0, self.min_interval - (now - self.last_request_time))
            )
            if self.max_requests and len(self._requests) >= self.max_requests:
                delay = max(delay, self._requests[0] + self.window_seconds - now)
            delay = max(delay, extra_delay or 0.0)
            if delay:
                time.sleep(delay)
            now = time.monotonic()
            while self._requests and self._requests[0] <= now - self.window_seconds:
                self._requests.popleft()
            self.last_request_time = now
            self._requests.append(now)


# Global singletons for centralized rate limiting across pipeline
arxiv_limiter = PoliteRateLimiter(min_interval_seconds=3.0)
s2_limiter = PoliteRateLimiter(1.05, max_requests=100)
