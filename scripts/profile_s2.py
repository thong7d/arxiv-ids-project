"""Bounded S2 experiment for owned IDs only; run while the owned crawler is stopped."""

import argparse
import hashlib
import json
import os
import time

import requests

from ids_arxiv.crawler.http import RequestFailure, get_response
from ids_arxiv.crawler.s2_client import SemanticScholarClient
from ids_arxiv.crawler.shared_quota import SharedQuota
from ids_arxiv.discovery import load_members
from ids_arxiv.identity import user_agent


def probe(variant, ids, members_path):
    owner = next(member for member in load_members(members_path) if member.student_id == "23120364")
    if not ids or len(ids) > 2 or any(not owner.contains(aid) for aid in ids):
        raise ValueError("This experiment permits only 1..2 IDs in 23120364's assigned range")
    key = os.environ["SEMANTIC_SCHOLAR_API_KEY"]
    limiter = SharedQuota(3.05, "s2", key)
    remaining = limiter.ready_in()
    if remaining > 0:
        return {"variant": variant, "deferred": True, "wait_seconds": remaining, "http_requests": 0}
    events = []
    started = time.monotonic()
    result = {"variant": variant, "ids": ids}
    if variant == "batch2":
        client = SemanticScholarClient(events=events.append, deferred=True)
        result["returned"] = client.get_many_references(ids)
        result["complete_publications"] = len(client.cache)
        result["arxiv_counts"] = {aid: len(refs) for aid, (refs, status) in client.cache.items()}
        result["raw_counts"] = {aid: status["raw_count"] for aid, (refs, status) in client.cache.items()}
    else:
        session = requests.Session()
        session.headers.update({"x-api-key": key, "User-Agent": user_agent()})
        limit = int(variant.removeprefix("paged"))
        try:
            with get_response(session, f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{ids[0]}/references",
                              limiter, params={"fields": "title,authors,year,venue,externalIds,publicationDate", "limit": limit, "offset": 0},
                              timeout=(10, 25), attempts=1, events=events.append, defer_on_rate_limit=True) as response:
                body = response.content
                data = response.json()
            complete = isinstance(data, dict) and isinstance(data.get("data"), list) and data.get("next") is None
            result.update(complete_publications=int(complete), raw_count=len(data.get("data", [])),
                          body_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest(), has_next=data.get("next") is not None)
        except RequestFailure as error:
            result.update(complete_publications=0, error=str(error), http_status=error.status_code)
        finally:
            session.close()
    elapsed = time.monotonic() - started
    result.update(elapsed_seconds=elapsed, events=events, http_requests=len(events),
                  completed_publications_per_second=result["complete_publications"] / max(elapsed, 1e-9))
    # Never print headers, credentials or raw bibliography content.
    return result


if __name__ == "__main__":
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=["batch2", "paged1000", "paged100"])
    parser.add_argument("--ids", nargs="+", default=["2508.17872", "2508.17873"])
    args = parser.parse_args()
    print(json.dumps(probe(args.variant, args.ids, Path(__file__).resolve().parents[1] / "configs/members.csv")))
