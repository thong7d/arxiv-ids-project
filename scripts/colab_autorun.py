"""Detached Colab coordinator. A single coordinated network runner owns shared quota.

Existing manifest/pilot evidence is required. Discovery is deliberately explicit
in colab_campaign.py; restarting a worker never repeats discovery automatically.
"""
import argparse
import os
import signal
import time
from pathlib import Path

from ids_arxiv.checkpoint import PROTOCOL
from ids_arxiv.crawler.runner import run_crawling_pipeline
from ids_arxiv.isolation import IsolatedService
from ids_arxiv.storage import atomic_json, utc_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--max-hours", type=float, default=9)
    parser.add_argument("--student-id", default=None)
    parser.add_argument("--log-suffix", default=None)  # legacy command compatibility
    parser.add_argument("--coordinated-network", action="store_true")
    args = parser.parse_args()
    if PROTOCOL >= 4:
        raise SystemExit("Legacy v3 coordinator cannot write protocol-4 data into the old campaign. Use python -m ids_arxiv.team_run.")
    if not args.coordinated_network:
        raise SystemExit("Coordinate all three Colabs first; explicit --coordinated-network is required.")
    if not (Path("/content").is_dir() and os.getenv("COLAB_RELEASE_TAG")):
        raise SystemExit("Final benchmark requires a Google Colab CPU runtime.")
    if os.getenv("COLAB_GPU", "0") not in ("0", ""):
        raise SystemExit("Select CPU runtime.")
    if args.max_hours <= 0:
        raise SystemExit("--max-hours must be positive")
    state_dir = Path(os.environ["IDS_LOCAL_STATE_DIR"])
    progress = state_dir / "progress.json"

    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"Explicit signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    campaign = args.root / "m1-final-v3"
    manifest = campaign / "manifests/papers.parquet"
    with IsolatedService("ids_arxiv.io_worker", timeout=120) as io:
        evidence = io.call({"action": "read_json", "path": str(manifest.with_suffix(".json")), "default": {}})
        gate = io.call({"action": "read_json", "path": str(args.root / "m1-pilot-v3/pilot_gate.json"), "default": {}})
    if (not evidence.get("verified_discovery") or not gate.get("passed")
            or gate.get("summary", {}).get("protocol_version") != 3):
        raise SystemExit("Need verified discovery and a real protocol-3 pilot. Run explicit campaign stages first.")
    config = Path(__file__).resolve().parents[1] / "configs/members.csv"
    try:
        # Includes retry waits. The pipeline exits with a documented next retry
        # instead of burning an entire session sleeping through a long cooldown.
        result = run_crawling_pipeline(
            manifest, campaign / "raw", members_config=config, student_id=args.student_id,
            max_seconds=args.max_hours * 3600,
            expected_manifest_hash=evidence["manifest_sha256"],
        )
        print({"state": result["state"], "verified": result["success_count"],
               "expected": result["selected_publications"], "next_retry_epoch": result["next_retry_epoch"]},
              flush=True)
    except BaseException as error:
        # Never leave "crawling" after SIGINT/SystemExit/unhandled exceptions.
        try:
            import json
            state = json.loads(progress.read_text(encoding="utf-8")) if progress.exists() else {}
            state.update(state="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                         error=type(error).__name__, heartbeat_epoch=time.time(), updated_at=utc_now())
            atomic_json(progress, state)
        finally:
            raise


if __name__ == "__main__":
    main()
