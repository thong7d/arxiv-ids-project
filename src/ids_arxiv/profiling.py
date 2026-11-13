"""Low-overhead, exclusive stage timings; cache/retry samples stay distinguishable."""

import functools
import time
from collections import defaultdict


class StageClock:
    def __init__(self, stage="overhead", clock=None):
        self.clock = clock or time.monotonic
        self.started = self.last = self.clock()
        self.stage = stage
        self.seconds = defaultdict(float)

    def switch(self, stage):
        now = self.clock()
        self.seconds[self.stage] += max(0, now - self.last)
        self.stage, self.last = stage, now

    def finish(self):
        self.switch("finished")
        return {key: round(value, 6) for key, value in self.seconds.items() if key != "finished"}


def profile_paper(function):
    @functools.wraps(function)
    def wrapped(arxiv_id, output_dir, arxiv_crawler, s2_client, *args, **kwargs):
        timer = StageClock()
        previous = getattr(arxiv_crawler, "progress", None)
        def progress(stage, **extra):
            timer.switch("source" if stage == "download_source" else stage)
            if previous:
                previous(stage, **extra)
        arxiv_crawler.progress = progress
        try:
            result = function(arxiv_id, output_dir, arxiv_crawler, s2_client, *args, **kwargs)
            result["paper_stage_seconds"] = timer.finish()
            return result
        finally:
            if previous is None:
                del arxiv_crawler.progress
            else:
                arxiv_crawler.progress = previous
    return wrapped


def distribution(values):
    values = sorted(float(value) for value in values)
    if not values:
        return {"n": 0, "mean_s": None, "p50_s": None, "p95_s": None, "total_s": 0}
    def quantile(fraction):
        position = (len(values) - 1) * fraction
        lower = int(position)
        return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)
    return {"n": len(values), "mean_s": sum(values) / len(values), "p50_s": quantile(.5),
            "p95_s": quantile(.95), "total_s": sum(values)}


def summarize_attempts(rows):
    rows = [row for row in rows if row.get("kind") == "paper_attempt"]
    stages = defaultdict(list)
    for row in rows:
        for name, seconds in row.get("stage_seconds", {}).items():
            stages[name].append(seconds)
        # Nested worker stages are a breakdown, not additive to coordinator time.
        for name, seconds in ({} if row.get("cache_hit") else row.get("paper_stage_seconds", {})).items():
            stages["worker/" + name].append(seconds)
    wall = sum(row.get("elapsed_seconds", 0) for row in rows)
    return {"attempts": len(rows), "successful_attempts": sum(bool(row.get("success")) for row in rows),
            "latency": distribution([row["elapsed_seconds"] for row in rows]),
            "cache_latency": distribution([row["elapsed_seconds"] for row in rows if row.get("cache_hit")]),
            "work_latency": distribution([row["elapsed_seconds"] for row in rows if not row.get("cache_hit")]),
            "attempts_per_hour_active": 3600 * len(rows) / wall if wall else None,
            "stages": {name: distribution(values) for name, values in stages.items()},
            "note": "Attempt latency includes cache/I/O/network waits/retries; excludes queue idle and startup. Nested worker/* is not additive. Not cold benchmark or unique-paper ETA."}
