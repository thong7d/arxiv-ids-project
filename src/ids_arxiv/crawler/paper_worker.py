"""Persistent local-disk paper service; its supervisor owns the wall-clock deadline."""

import json
import time
from pathlib import Path

from ..checkpoint import read_json
from ..isolation import serve
from ..storage import atomic_json, utc_now
from .arxiv_client import ArxivCrawler
from .reference_dates import ReferenceDates
from .s2_client import SemanticScholarClient

context = {}


def handle(request):
    if request["action"] == "init":
        root = Path(request["root"])
        root.mkdir(parents=True, exist_ok=True)
        metadata = json.loads(Path(request["metadata"]).read_text()) if request.get("metadata") else {}
        metadata.update(read_json(root / "atom-metadata-cache.json", {}))

        def event(value):
            with (root / "http-events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=True) + "\n")

        def progress(stage, **extra):
            atomic_json(root / "activity.json", {"stage": stage, "activity_epoch": time.time(),
                                                "timestamp": utc_now(), **extra})
        crawler = ArxivCrawler(metadata_cache=metadata, events=event)
        crawler.progress = progress
        crawler.reference_dates = ReferenceDates(root / "reference-dates.json", metadata)
        context.update(root=root, crawler=crawler, s2=SemanticScholarClient(events=event, deferred=True))
        return {"ready": True, "s2_key_present": bool(context["s2"].api_key)}
    if request["action"] == "metadata_batch":
        result = context["crawler"].prefetch_metadata(request["ids"])
        if result["updated"]:
            atomic_json(context["root"] / "atom-metadata-cache.json", context["crawler"].metadata_cache)
        return result
    if request["action"] == "prefetch":
        return context["s2"].prefetch(request["ids"])
    if request["action"] == "paper":
        from .runner import crawl_paper
        with context["s2"].cache_lock:
            for references, status in context["s2"].cache.values():
                if status.get("success"):
                    context["crawler"].reference_dates.enqueue(references)
        return crawl_paper(request["arxiv_id"], Path(request["output"]),
                           context["crawler"], context["s2"], resume=request.get("resume", True))
    raise ValueError("Unsupported paper action")


if __name__ == "__main__":
    serve(handle)
