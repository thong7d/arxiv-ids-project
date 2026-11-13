"""Cross-process pacing on one runtime. Not a distributed/multi-Colab quota claim."""

import hashlib
import json
import tempfile
import time
from pathlib import Path

from ..runtime import local_lock, runtime_id
from ..storage import atomic_json


class SharedQuota:
    def __init__(self, interval, service, credential=""):
        digest = hashlib.sha256(credential.encode()).hexdigest()[:16]
        directory = Path(tempfile.gettempdir()) / "ids13-quota" / runtime_id()
        self.path = directory / f"{service}-{digest}.json"
        self.lock = self.path.with_suffix(".lock")
        self.interval = interval
        self.service = service
        self.retry_floor = 5.0 if service == "s2" and credential != "anonymous" else 60.0

    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def ready_in(self):
        with local_lock(self.lock):
            return max(0, self._load().get("cooldown", 0) - time.monotonic())

    def defer(self, seconds):
        with local_lock(self.lock):
            state = self._load()
            state["cooldown"] = max(state.get("cooldown", 0), time.monotonic() + seconds)
            atomic_json(self.path, state)

    def rate_limited(self, retry_after=0):
        """Adaptive shared backoff, always honoring a server Retry-After."""
        with local_lock(self.lock):
            state = self._load()
            failures = min(10, state.get("consecutive_429", 0) + 1)
            delay = max(retry_after, min(120, self.retry_floor * 2 ** (failures - 1)))
            state.update(consecutive_429=failures,
                         cooldown=max(state.get("cooldown", 0), time.monotonic() + delay))
            atomic_json(self.path, state)
            return max(delay, state["cooldown"] - time.monotonic())

    def reset_backoff(self):
        # Do not erase an existing cooldown from another in-flight request.
        with local_lock(self.lock):
            state = self._load()
            if state.get("consecutive_429"):
                state["consecutive_429"] = 0
                atomic_json(self.path, state)

    def wait(self, extra_delay=0):
        earliest = time.monotonic() + (extra_delay or 0)
        while True:
            with local_lock(self.lock):
                state = self._load()
                slot = max(earliest, time.monotonic(), state.get("next", 0), state.get("cooldown", 0))
                state["next"] = slot + self.interval
                atomic_json(self.path, state)
            time.sleep(max(0, slot - time.monotonic()))
            # Another process may have opened a circuit while this one slept.
            if self.ready_in() <= 0:
                return
            earliest = time.monotonic()
