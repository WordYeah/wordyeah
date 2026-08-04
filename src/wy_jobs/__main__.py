from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from wy_core.config import load_policy_config
from wy_core.result_store import ResultStore
from wy_media.falconsai import FalconsaiClassifier
from wy_media.service import MediaModerationService
from wy_review.store import ReviewStore

from .store import Job, JobStore
from .worker import JobWorker


def _safe_media_path(media_root: Path, media_ref: str) -> Path:
    if not media_ref.startswith("media://"):
        raise ValueError("media_ref must use media://")
    relative = media_ref.removeprefix("media://")
    if not relative or relative.startswith("/"):
        raise ValueError("media_ref must be a relative media reference")
    root = media_root.expanduser().resolve()
    path = (root / relative).resolve()
    if root != path and root not in path.parents:
        raise ValueError("media_ref escapes media root")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one or more WordYeah avatar jobs")
    parser.add_argument("--database", default="./var/wordyeah.sqlite3")
    parser.add_argument("--media-root", default="./var/media")
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--policy-path", default="./config/policy.avatar.example.json")
    parser.add_argument("--worker-id", default="")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args()

    policy_config = load_policy_config(args.policy_path)
    store = JobStore(args.database)
    review_store = ReviewStore(args.database)
    result_store = ResultStore(args.database)
    service = MediaModerationService(
        FalconsaiClassifier(args.model_path, args.device),
        policy=policy_config.media_policy,
        policy_version=policy_config.policy_version,
    )
    service.warmup()
    media_root = Path(args.media_root)

    def handle(job: Job) -> dict[str, Any]:
        path = _safe_media_path(media_root, str(job.payload["media_ref"]))
        image_bytes = path.read_bytes()
        result = service.moderate_image(image_bytes)
        result_store.record(result, job.consumer_id, job.payload["media_ref"], policy_config.profile)
        if result.decision in {"review", "block", "error"}:
            review_store.enqueue(result, job.payload["media_ref"], consumer_id=job.consumer_id)
        return result.to_dict()

    worker = JobWorker(store, args.worker_id)
    try:
        while True:
            job = worker.run_once(handle)
            if args.once or job is None:
                return
            time.sleep(max(args.poll_interval, 0.05))
    finally:
        review_store.close()
        store.close()
        result_store.close()


if __name__ == "__main__":
    main()
