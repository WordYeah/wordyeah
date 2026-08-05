from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from wy_core.config import load_policy_config
from wy_core.result_store import ResultStore
from wy_media.falconsai import FalconsaiClassifier
from wy_media.failover import build_primary_vision_provider
from wy_media.g2a import G2AConfig, G2AVisionProvider
from wy_media.ollama import OllamaConfig, OllamaVisionProvider
from wy_media.service import MediaModerationService
from wy_media.vision_provider import AdvancedVisionProvider
from wy_media.vision_worker import VisionReviewWorker
from wy_review.attempt_store import ReviewAttemptStore
from wy_review.store import ReviewStore

from .store import Job, JobStore
from .vision import VISION_JOB_KINDS
from .worker import JobWorker


_G2A_ENV_NAMES = (
    "ENABLED",
    "ENDPOINT",
    "API_KEY",
    "MODEL",
    "MODEL_VERSION",
    "TIMEOUT_SECONDS",
    "PROMPT_VERSION",
    "MAX_IMAGE_BYTES",
    "ALLOW_PRIVATE_HTTP",
)


class VisionProviderDisabledError(RuntimeError):
    """Raised before opening stores when advanced vision is not enabled."""


def _secondary_g2a_config(env: Mapping[str, str] | None = None) -> G2AConfig:
    values = os.environ if env is None else env
    secondary = {
        f"WORDYEAH_G2A_{name}": values[f"WORDYEAH_G2A_SECONDARY_{name}"]
        for name in _G2A_ENV_NAMES
        if f"WORDYEAH_G2A_SECONDARY_{name}" in values
    }
    return G2AConfig.from_env(secondary)


def _vision_providers(
    env: Mapping[str, str] | None = None,
) -> dict[str, AdvancedVisionProvider]:
    primary = build_primary_vision_provider(env)
    if not primary.enabled:
        raise VisionProviderDisabledError(
            "advanced vision is disabled; enable G2A Web or local Ollama"
        )
    secondary_g2a = G2AVisionProvider(_secondary_g2a_config(env))
    if secondary_g2a.enabled:
        secondary: AdvancedVisionProvider = secondary_g2a
    else:
        primary_ollama = OllamaConfig.from_env(env)
        secondary = OllamaVisionProvider(
            OllamaConfig.from_env(
                env,
                secondary=True,
                inherit_enabled=primary_ollama.enabled,
            )
        )
    return {
        "primary": primary,
        "secondary": secondary,
    }


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


def _run_vision(args: argparse.Namespace) -> None:
    # Validate provider configuration before opening any database handles. Error
    # messages intentionally never include configuration objects or secrets.
    providers = _vision_providers()
    store = JobStore(args.database)
    attempt_store: ReviewAttemptStore | None = None
    review_store: ReviewStore | None = None
    try:
        attempt_store = ReviewAttemptStore(args.database)
        review_store = ReviewStore(args.database)
        worker = VisionReviewWorker(
            job_store=store,
            attempt_store=attempt_store,
            review_store=review_store,
            providers=providers,
            media_root=Path(args.media_root),
            worker_id=args.worker_id,
            consumer_id=args.consumer_id,
            context_marker=args.vision_context_marker,
            exclude_context_marker=args.vision_exclude_context_marker,
            job_kinds=(args.vision_stage,) if args.vision_stage else VISION_JOB_KINDS,
        )
        processed = 0
        while True:
            job = worker.run_once()
            if job is not None:
                processed += 1
            if args.once:
                return
            if args.vision_max_jobs is not None:
                if job is None or processed >= args.vision_max_jobs:
                    return
                continue
            if job is None:
                time.sleep(max(args.poll_interval, 0.05))
    finally:
        if review_store is not None:
            review_store.close()
        if attempt_store is not None:
            attempt_store.close()
        store.close()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run one or more WordYeah avatar jobs")
    parser.add_argument("--database", default="./var/wordyeah.sqlite3")
    parser.add_argument("--media-root", default="./var/media")
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--policy-path", default="./config/policy.avatar.example.json")
    parser.add_argument("--worker-id", default="")
    parser.add_argument(
        "--consumer-id",
        help="claim only jobs for this consumer (vision worker only)",
    )
    parser.add_argument(
        "--vision-context-marker",
        help="claim only vision jobs whose controlled context contains this marker",
    )
    parser.add_argument(
        "--vision-exclude-context-marker",
        help="claim only vision jobs whose controlled context does not contain this marker",
    )
    parser.add_argument(
        "--vision-stage",
        choices=VISION_JOB_KINDS,
        help="claim only one advanced-vision stage (requires --vision)",
    )
    parser.add_argument(
        "--vision-max-jobs",
        type=int,
        help="process at most this many currently available vision jobs, then exit",
    )
    parser.add_argument(
        "--vision",
        action="store_true",
        help="process queued advanced-vision review jobs instead of fast-scan jobs",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args(argv)

    if args.vision_max_jobs is not None and args.vision_max_jobs < 1:
        parser.error("--vision-max-jobs must be at least 1")
    if args.once and args.vision_max_jobs is not None:
        parser.error("--once and --vision-max-jobs cannot be combined")

    if args.vision:
        try:
            _run_vision(args)
        except VisionProviderDisabledError as exc:
            parser.error(str(exc))
        return

    if (
        args.consumer_id
        or args.vision_context_marker
        or args.vision_exclude_context_marker
        or args.vision_stage
        or args.vision_max_jobs is not None
    ):
        parser.error(
            "--consumer-id, --vision-context-marker, --vision-exclude-context-marker, "
            "--vision-stage, and --vision-max-jobs require --vision"
        )

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
            if args.once:
                return
            if job is None:
                time.sleep(max(args.poll_interval, 0.05))
                continue
            time.sleep(max(args.poll_interval, 0.05))
    finally:
        review_store.close()
        store.close()
        result_store.close()


if __name__ == "__main__":
    main()
