#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from wy_jobs.store import JobStore


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * fraction), len(ordered) - 1)]


def run_benchmark(
    *,
    database: str,
    duration_seconds: float,
    target_rate: float,
    consumer_id: str,
    required_duration_seconds: float = 900.0,
) -> dict[str, object]:
    if duration_seconds <= 0 or target_rate <= 0 or required_duration_seconds <= 0:
        raise ValueError("durations and target rate must be positive")
    store = JobStore(database)
    enqueue_latencies: list[float] = []
    cycle_latencies: list[float] = []
    completed = 0
    started = time.perf_counter()
    next_submission = started
    active_jobs_after_run = 0
    try:
        while True:
            now = time.perf_counter()
            if now - started >= duration_seconds:
                break
            if now < next_submission:
                time.sleep(min(next_submission - now, 0.01))
                continue
            sequence = completed + 1
            began = time.perf_counter()
            store.enqueue(
                "benchmark",
                {"sequence": sequence},
                consumer_id,
                idempotency_key=f"benchmark:{sequence}",
            )
            enqueue_latencies.append((time.perf_counter() - began) * 1000)
            job = store.claim("benchmark-worker", lease_seconds=30, kinds=("benchmark",))
            if job is None:
                raise RuntimeError("benchmark job could not be claimed")
            store.complete(job.job_id, "benchmark-worker", {"ok": True})
            cycle_latencies.append((time.perf_counter() - began) * 1000)
            completed += 1
            next_submission += 1 / target_rate
        elapsed = time.perf_counter() - started
        active_jobs_after_run = store.count_active(consumer_id)
    finally:
        store.close()

    throughput = completed / elapsed if elapsed else 0.0
    sustained = elapsed >= required_duration_seconds
    rate_met = throughput >= target_rate * 0.95
    return {
        "status": "PASS" if sustained and rate_met else "FAIL" if sustained else "SMOKE",
        "completed": completed,
        "elapsed_seconds": elapsed,
        "target_rate_per_second": target_rate,
        "throughput_per_second": throughput,
        "required_duration_seconds": required_duration_seconds,
        "duration_gate_met": sustained,
        "rate_gate_met": rate_met,
        "enqueue_p95_ms": percentile(enqueue_latencies, 0.95),
        "cycle_p95_ms": percentile(cycle_latencies, 0.95),
        "active_jobs_after_run": active_jobs_after_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the durable review job queue")
    parser.add_argument("--database")
    parser.add_argument("--duration", type=float, default=900.0)
    parser.add_argument("--required-duration", type=float, default=900.0)
    parser.add_argument("--target-rate", type=float, required=True)
    parser.add_argument("--consumer", default="benchmark")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.database:
        report = run_benchmark(
            database=args.database,
            duration_seconds=args.duration,
            target_rate=args.target_rate,
            consumer_id=args.consumer,
            required_duration_seconds=args.required_duration,
        )
    else:
        with tempfile.TemporaryDirectory() as directory:
            report = run_benchmark(
                database=str(Path(directory) / "queue.sqlite3"),
                duration_seconds=args.duration,
                target_rate=args.target_rate,
                consumer_id=args.consumer,
                required_duration_seconds=args.required_duration,
            )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["status"] in {"PASS", "SMOKE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
