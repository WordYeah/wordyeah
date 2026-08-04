from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "benchmark_review_queue.py"
SPEC = importlib.util.spec_from_file_location("benchmark_review_queue", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_short_run_is_smoke_not_acceptance_pass(tmp_path: Path) -> None:
    report = MODULE.run_benchmark(
        database=str(tmp_path / "queue.sqlite3"),
        duration_seconds=0.05,
        target_rate=20,
        consumer_id="fixture",
        required_duration_seconds=900,
    )
    assert report["status"] == "SMOKE"
    assert report["duration_gate_met"] is False
    assert report["completed"] > 0
    assert report["active_jobs_after_run"] == 0


def test_invalid_parameters_fail_closed(tmp_path: Path) -> None:
    try:
        MODULE.run_benchmark(
            database=str(tmp_path / "queue.sqlite3"),
            duration_seconds=0,
            target_rate=1,
            consumer_id="fixture",
        )
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("zero duration was accepted")
