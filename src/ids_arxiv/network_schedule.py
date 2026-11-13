"""Deterministic UTC turns: independent Colabs need no coordinator service."""

import os
import time
from dataclasses import dataclass

RUNNERS = ("23120364", "23120358", "23120345")


@dataclass(frozen=True)
class NetworkWindow:
    runner_id: str
    slot_seconds: int = 600
    guard_seconds: int = 10

    def __post_init__(self):
        if self.runner_id not in RUNNERS or self.slot_seconds < 60 or not 1 <= self.guard_seconds < self.slot_seconds / 4:
            raise ValueError("Invalid fixed team schedule")

    def status(self, now=None):
        now = time.time() if now is None else now
        period = len(RUNNERS) * self.slot_seconds
        base = (now // period) * period
        start = base + RUNNERS.index(self.runner_id) * self.slot_seconds + self.guard_seconds
        end = base + (RUNNERS.index(self.runner_id) + 1) * self.slot_seconds - self.guard_seconds
        allowed = start <= now < end
        next_at = start if now < start else (now if allowed else start + period)
        return {"allowed": allowed, "next_epoch": next_at, "deadline_epoch": end,
                "remaining_seconds": max(0, end - now) if allowed else 0,
                "runner_id": self.runner_id}


def configured_window():
    mode = os.environ.get("IDS_NETWORK_MODE", "legacy")
    if mode == "independent_utc":
        return NetworkWindow(os.environ["IDS_RUNNER_ID"])
    if mode in {"legacy", "exclusive"}:
        return None
    raise ValueError("Unknown network mode; refusing network access")
