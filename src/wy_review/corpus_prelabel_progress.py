"""Read-only health and progress evidence for a private corpus prelabel drain."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping

from wy_jobs.vision import VisionReviewJobPayload

from .corpus_ai_prelabels import is_corpus_ai_prelabel_context
from .quality_evaluation import evaluate_quality_database


def audit_corpus_prelabel_progress(
    database: str | Path,
    *,
    consumer_id: str,
    batch_id: str = "corpus-primary-v1",
    expect_human_truth_untouched: bool = True,
    now: datetime | None = None,
) -> dict[str, object]:
    """Inspect one frozen corpus and its proposal jobs without writing SQLite."""

    if not consumer_id or len(consumer_id) > 128:
        raise ValueError("consumer_id must be between 1 and 128 characters")
    if not batch_id or len(batch_id) > 128:
        raise ValueError("batch_id must be between 1 and 128 characters")
    database_path = _database_path(database)
    observed_at = _utc(now or datetime.now(UTC))

    connection = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        selected, selected_count, missing_review_links = _selected_samples(
            connection, consumer_id, batch_id
        )
        human_decision_count = int(
            connection.execute(
                """SELECT COUNT(*) FROM quality_decisions
                WHERE consumer_id = ? AND sample_id IN (
                    SELECT sample_id FROM quality_review_batch_items
                    WHERE consumer_id = ? AND batch_id = ?
                )""",
                (consumer_id, consumer_id, batch_id),
            ).fetchone()[0]
        )
        human_resolved_count = int(
            connection.execute(
                """SELECT COUNT(*) FROM quality_samples
                WHERE consumer_id = ? AND final_decision IS NOT NULL
                  AND sample_id IN (
                    SELECT sample_id FROM quality_review_batch_items
                    WHERE consumer_id = ? AND batch_id = ?
                  )""",
                (consumer_id, consumer_id, batch_id),
            ).fetchone()[0]
        )
        rows = connection.execute(
            """SELECT job_id, kind, payload_json, result_json, status, attempts,
                      worker_id, lease_until, error_kind, updated_at
            FROM jobs
            WHERE consumer_id = ? AND kind IN ('vision_review_1', 'vision_review_2')
            ORDER BY created_at, job_id""",
            (consumer_id,),
        ).fetchall()
    finally:
        connection.close()

    jobs: list[dict[str, object]] = []
    malformed_candidate_jobs: list[str] = []
    for row in rows:
        raw_payload = row["payload_json"]
        try:
            value = json.loads(raw_payload)
            if not isinstance(value, Mapping):
                raise ValueError("payload is not an object")
            payload = VisionReviewJobPayload.from_mapping(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            if "quality_ai_prelabel" in str(raw_payload):
                malformed_candidate_jobs.append(row["job_id"])
            continue
        if not is_corpus_ai_prelabel_context(payload.context):
            if "quality_ai_prelabel" in payload.context:
                malformed_candidate_jobs.append(row["job_id"])
            continue
        jobs.append({"row": row, "payload": payload})

    status_counts: Counter[str] = Counter()
    stage_counts: dict[str, Counter[str]] = defaultdict(Counter)
    worker_rows: list[dict[str, object]] = []
    stale_leases: list[str] = []
    missing_leases: list[str] = []
    unlinked_jobs: list[str] = []
    kind_stage_mismatches: list[str] = []
    malformed_result_jobs: list[str] = []
    successful_groups: Counter[tuple[str, str]] = Counter()
    attempt_owners: dict[str, list[str]] = defaultdict(list)
    recent_successes: list[datetime] = []

    for job in jobs:
        row = job["row"]
        payload = job["payload"]
        assert isinstance(row, sqlite3.Row)
        assert isinstance(payload, VisionReviewJobPayload)
        status = str(row["status"])
        status_counts[status] += 1
        stage_counts[payload.stage][status] += 1
        sample_id = selected.get(payload.item_id)
        if sample_id is None:
            unlinked_jobs.append(row["job_id"])
        if row["kind"] != payload.stage:
            kind_stage_mismatches.append(row["job_id"])

        if status == "running":
            lease = _parse_time(row["lease_until"])
            remaining = (lease - observed_at).total_seconds() if lease else None
            if lease is None:
                missing_leases.append(row["job_id"])
            elif remaining <= 0:
                stale_leases.append(row["job_id"])
            worker_rows.append(
                {
                    "job_id": row["job_id"],
                    "worker_id": row["worker_id"],
                    "stage": payload.stage,
                    "attempts": int(row["attempts"]),
                    "lease_until": row["lease_until"],
                    "lease_remaining_seconds": (
                        round(remaining, 1) if remaining is not None else None
                    ),
                }
            )

        if status != "succeeded":
            continue
        updated_at = _parse_time(row["updated_at"])
        if updated_at is not None:
            recent_successes.append(updated_at)
        if sample_id is not None:
            successful_groups[(sample_id, payload.stage)] += 1
        attempt_id = _result_attempt_id(row["result_json"])
        if attempt_id is None:
            malformed_result_jobs.append(row["job_id"])
        else:
            attempt_owners[attempt_id].append(row["job_id"])

    active_count = status_counts["queued"] + status_counts["running"]
    duplicate_success_groups = [
        {"sample_id": sample_id, "stage": stage, "count": count}
        for (sample_id, stage), count in sorted(successful_groups.items())
        if count > 1
    ]
    duplicate_attempt_ids = [
        {"attempt_id": attempt_id, "job_ids": owners}
        for attempt_id, owners in sorted(attempt_owners.items())
        if len(owners) > 1
    ]
    evaluation_error: str | None = None
    try:
        evaluation = evaluate_quality_database(
            database_path, consumer_id=consumer_id, batch_id=batch_id
        )
        prediction_count = int(evaluation["ai_prediction_count"])
    except (AssertionError, sqlite3.Error, ValueError) as exc:
        evaluation_error = f"{type(exc).__name__}: {exc}"
        prediction_count = 0
    completed_15m = _recent_count(recent_successes, observed_at, 15)
    completed_60m = _recent_count(recent_successes, observed_at, 60)
    eta = _eta(active_count, completed_60m, observed_at)
    human_truth_untouched = human_decision_count == 0 and human_resolved_count == 0
    integrity_ok = not any(
        (
            malformed_candidate_jobs,
            missing_review_links,
            stale_leases,
            missing_leases,
            unlinked_jobs,
            kind_stage_mismatches,
            malformed_result_jobs,
            duplicate_success_groups,
            duplicate_attempt_ids,
            evaluation_error,
        )
    )
    truth_ok = human_truth_untouched or not expect_human_truth_untouched
    prediction_complete = selected_count > 0 and prediction_count == selected_count
    if not integrity_ok or not truth_ok:
        status = "DEGRADED"
    elif prediction_complete and active_count == 0:
        status = "COMPLETE"
    elif active_count == 0:
        status = "STALLED"
    else:
        status = "HEALTHY"

    return {
        "kind": "wordyeah_corpus_prelabel_progress",
        "status": status,
        "observed_at": observed_at.isoformat(),
        "consumer_id": consumer_id,
        "batch_id": batch_id,
        "selected_count": selected_count,
        "ai_prediction_count": prediction_count,
        "prediction_coverage_percent": round(
            prediction_count * 100 / selected_count, 2
        ) if selected_count else 0.0,
        "prediction_complete": prediction_complete,
        "human_truth": {
            "expected_untouched": expect_human_truth_untouched,
            "untouched": human_truth_untouched,
            "decision_count": human_decision_count,
            "resolved_count": human_resolved_count,
        },
        "jobs": {
            "total": len(jobs),
            "active": active_count,
            "by_status": dict(sorted(status_counts.items())),
            "by_stage": {
                stage: dict(sorted(counts.items()))
                for stage, counts in sorted(stage_counts.items())
            },
            "workers": worker_rows,
        },
        "throughput": {
            "succeeded_last_15_minutes": completed_15m,
            "succeeded_last_60_minutes": completed_60m,
            "jobs_per_minute_last_60_minutes": round(completed_60m / 60, 3),
            **eta,
        },
        "integrity": {
            "ok": integrity_ok,
            "malformed_candidate_job_ids": malformed_candidate_jobs,
            "missing_review_link_sample_ids": missing_review_links,
            "stale_lease_job_ids": stale_leases,
            "missing_lease_job_ids": missing_leases,
            "unlinked_job_ids": unlinked_jobs,
            "kind_stage_mismatch_job_ids": kind_stage_mismatches,
            "malformed_result_job_ids": malformed_result_jobs,
            "duplicate_success_groups": duplicate_success_groups,
            "duplicate_attempt_ids": duplicate_attempt_ids,
            "evaluation_error": evaluation_error,
        },
        "database_mode": "read_only",
        "mutates_quality_decisions": False,
        "mutates_avatar": False,
    }


def _database_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("database must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("database must be a regular file")
    return resolved


def _selected_samples(
    connection: sqlite3.Connection, consumer_id: str, batch_id: str
) -> tuple[dict[str, str], int, list[str]]:
    batch = connection.execute(
        """SELECT 1 FROM quality_review_batches
        WHERE consumer_id = ? AND batch_id = ?""",
        (consumer_id, batch_id),
    ).fetchone()
    if batch is None:
        raise KeyError(f"quality review batch not found: {batch_id}")
    rows = connection.execute(
        """SELECT sample.sample_id, review.item_id AS review_item_id
        FROM quality_review_batch_items AS item
        JOIN quality_samples AS sample
          ON sample.consumer_id = item.consumer_id
         AND sample.sample_id = item.sample_id
        LEFT JOIN review_items AS review
          ON review.consumer_id = sample.consumer_id
         AND review.source_id = sample.item_id
        WHERE item.consumer_id = ? AND item.batch_id = ?
        ORDER BY item.ordinal""",
        (consumer_id, batch_id),
    ).fetchall()
    selected = {
        row["review_item_id"]: row["sample_id"]
        for row in rows
        if row["review_item_id"] is not None
    }
    missing = [
        row["sample_id"] for row in rows if row["review_item_id"] is None
    ]
    return selected, len(rows), missing


def _result_attempt_id(raw: object) -> str | None:
    try:
        result = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError:
        return None
    if not isinstance(result, Mapping) or not isinstance(result.get("attempt"), Mapping):
        return None
    attempt_id = result["attempt"].get("attempt_id")
    return attempt_id if isinstance(attempt_id, str) and attempt_id else None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _recent_count(values: list[datetime], now: datetime, minutes: int) -> int:
    start = now - timedelta(minutes=minutes)
    return sum(start <= value <= now for value in values)


def _eta(active_count: int, completed_60m: int, now: datetime) -> dict[str, object]:
    if active_count == 0:
        return {
            "eta_scope": "currently_enqueued_jobs_only",
            "eta_minutes": 0.0,
            "estimated_current_queue_empty_at": now.isoformat(),
        }
    if completed_60m < 2:
        return {
            "eta_scope": "currently_enqueued_jobs_only",
            "eta_minutes": None,
            "estimated_current_queue_empty_at": None,
        }
    minutes = active_count / (completed_60m / 60)
    return {
        "eta_scope": "currently_enqueued_jobs_only",
        "eta_minutes": round(minutes, 1),
        "estimated_current_queue_empty_at": (
            now + timedelta(minutes=minutes)
        ).isoformat(),
    }
