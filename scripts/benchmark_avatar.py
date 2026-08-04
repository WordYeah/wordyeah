#!/usr/bin/env python3
"""Benchmark the avatar service paths without contacting external services."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from wy_api.app import ApiSettings, create_app
from wy_core.result_store import ResultStore
from wy_jobs.store import JobStore
from wy_jobs.worker import Job, JobWorker
from wy_media.falconsai import FalconsaiClassifier
from wy_media.service import MediaModerationService
from wy_review.store import ReviewStore


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
    return round(ordered[index], 3)


def summarize(name: str, durations: list[float], errors: int, started: float) -> dict[str, Any]:
    total_seconds = max(time.perf_counter() - started, 1e-9)
    return {
        "path": name,
        "sample_count": len(durations),
        "errors": errors,
        "p50_ms": percentile(durations, 0.50),
        "p95_ms": percentile(durations, 0.95),
        "p99_ms": percentile(durations, 0.99),
        "throughput_per_second": round(len(durations) / total_seconds, 3),
    }


def image_content_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(path.suffix.lower(), "image/png")


def run_samples(
    name: str,
    payloads: list[tuple[str, bytes]],
    callback: Callable[[str, bytes], bool],
) -> dict[str, Any]:
    durations: list[float] = []
    errors = 0
    started = time.perf_counter()
    for ref, payload in payloads:
        item_started = time.perf_counter()
        try:
            if not callback(ref, payload):
                errors += 1
        except Exception:
            errors += 1
        durations.append((time.perf_counter() - item_started) * 1000)
    return summarize(name, durations, errors, started)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-dir", default="artifacts/fixtures")
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    if args.requests < 1 or args.requests > 1000:
        raise SystemExit("--requests must be between 1 and 1000")

    fixture_root = Path(args.fixture_dir).expanduser().resolve()
    files = sorted(
        path
        for path in fixture_root.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    )
    if not files:
        raise SystemExit(f"no supported image fixtures found: {fixture_root}")
    selected = [files[index % len(files)] for index in range(args.requests)]
    payloads = [(path.name, path.read_bytes()) for path in selected]

    classifier = FalconsaiClassifier(model_path=args.model_path, device=args.device)
    classifier.warmup()
    service = MediaModerationService(classifier)
    report: dict[str, Any] = {
        "kind": "wordyeah_avatar_service_benchmark",
        "model": classifier.model_version,
        "device": classifier.device_name,
        "fixture_count": len(files),
        "sample_count": len(payloads),
        "external_model_calls": False,
        "paths": [],
    }

    report["paths"].append(
        run_samples(
            "api-only-domain",
            payloads,
            lambda _ref, payload: service.moderate_image(payload).decision != "error",
        )
    )

    try:
        from fastapi.testclient import TestClient
    except ImportError as exc:  # pragma: no cover - optional API extra
        raise SystemExit(f"api benchmark requires the api extra: {exc}") from exc

    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "api.sqlite3")
        settings = ApiSettings(
            database_path=database,
            media_root=fixture_root,
            model_path=args.model_path,
            device=args.device,
        )
        api_app = create_app(settings=settings, service=MediaModerationService(classifier))
        with TestClient(api_app) as client:
            report["paths"].append(
                run_samples(
                    "api-plus-sqlite",
                    payloads,
                    lambda path, payload: client.post(
                        "/v1/moderate/image",
                        content=payload,
                        headers={"Content-Type": image_content_type(Path(path))},
                    ).status_code == 200,
                )
            )
        api_results = ResultStore(database)
        report["api_result_runs"] = api_results.count_runs("default")
        api_results.close()

    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "worker.sqlite3")
        jobs = JobStore(database)
        results = ResultStore(database)
        reviews = ReviewStore(database)
        for path, _payload in payloads:
            jobs.enqueue("moderate_image", {"media_ref": f"media://{path}"}, "benchmark")
        worker_service = MediaModerationService(classifier)

        def handle(job: Job) -> dict[str, Any]:
            path = (fixture_root / str(job.payload["media_ref"]).removeprefix("media://")).resolve()
            result = worker_service.moderate_image(path.read_bytes())
            results.record(result, job.consumer_id, job.payload["media_ref"], "avatar-default")
            if result.decision in {"review", "block", "error"}:
                reviews.enqueue(result, job.payload["media_ref"], consumer_id=job.consumer_id)
            return result.to_dict()

        report["paths"].append(
            run_samples(
                "api-plus-worker",
                payloads,
                lambda _ref, _payload: JobWorker(jobs, worker_id="benchmark-worker").run_once(handle)
                is not None,
            )
        )
        report["worker_result_runs"] = results.count_runs("benchmark")
        report["worker_pending_reviews"] = len(reviews.list_pending(consumer_id="benchmark"))
        reviews.close()
        results.close()
        jobs.close()

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024
    report["max_rss_mb"] = round(rss_mb, 3)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
