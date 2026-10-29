"""
Rate limiter module ensuring polite crawling etiquette for arXiv and Semantic Scholar APIs.
"""

import threading
import time
from typing import Optional


class PoliteRateLimiter:
    """
    Enforces minimum interval between consecutive requests to a specific domain.
    Thread-safe and supports Retry-After headers.
    """

    def __init__(self, min_interval_seconds: float = 3.0):
        self.min_interval = min_interval_seconds
        self.last_request_time: float = 0.0
        self._lock = threading.Lock()

    def wait(self, extra_delay: Optional[float] = None) -> None:
        with self._lock:
            now = time.time()
            elapsed = now - self.last_request_time
            delay = self.min_interval

            if extra_delay is not None and extra_delay > delay:
                delay = extra_delay

            if elapsed < delay:
                time.sleep(delay - elapsed)

            self.last_request_time = time.time()


# Global singletons for centralized rate limiting across pipeline
arxiv_limiter = PoliteRateLimiter(min_interval_seconds=3.0)
s2_limiter = PoliteRateLimiter(min_interval_seconds=1.2)  # safe for unauthenticated / free key
