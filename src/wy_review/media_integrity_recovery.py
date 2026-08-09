from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import dataclass, replace
from pathlib import Path

from wy_jobs.store import JobStore
from wy_jobs.vision import VisionReviewJobPayload, enqueue_vision_review


class MediaIntegrityRecoveryError(RuntimeError):
    """Raised when legacy vision jobs cannot be recovered safely."""


@dataclass(frozen=True)
class _Candidate:
    job_id: str
    source_status: str
    consumer_id: str
    max_attempts: int
    payload: VisionReviewJobPayload
    media_sha256: str
    attempt_number: int


def recover_legacy_vision_media_hashes(
    *,
    database: str | Path,
    media_root: str | Path,
    consumer_id: str,
    apply: bool = False,
    limit: int | None = None,
    excluded_context_marker: str = "quality_ai_prelabel=true",
) -> dict[str, object]:
    """Replace queued legacy jobs with integrity-bound equivalents.

    The source/content hash remains unchanged.  Only the hash of the controlled,
    normalized media file is added to a new job; the legacy queued job is kept
    as a cancelled audit record.
    """

    if not consumer_id or len(consumer_id) > 128:
        raise ValueError("consumer_id must be between 1 and 128 characters")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    database_path = _regular_database(database)
    root = Path(media_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("media_root must be a directory")

    candidates, states, running_jobs = _plan(
        database_path,
        root,
        consumer_id=consumer_id,
        limit=limit,
        excluded_context_marker=excluded_context_marker,
    )
    if apply and stat.S_IMODE(database_path.stat().st_mode) != 0o600:
        raise MediaIntegrityRecoveryError(
            "apply requires a private database with mode 0600"
        )
    if apply and running_jobs:
        raise MediaIntegrityRecoveryError(
            "apply requires the normal vision lane to have zero running jobs"
        )
    before = _decision_snapshot(database_path, consumer_id)
    report: dict[str, object] = {
        "kind": "wordyeah_legacy_vision_media_recovery",
        "status": "DRY_RUN" if not apply else "APPLIED",
        "consumer_id": consumer_id,
        "selected_jobs": sum(states.values()),
        "repairable_jobs": len(candidates),
        "running_jobs": running_jobs,
        "states": dict(sorted(states.items())),
        "jobs_cancelled": 0,
        "jobs_created": 0,
        "failed_sources_requeued": 0,
        "decision_state_before": before,
        "decision_state_after": dict(before),
        "production_write": False,
        "mutates_avatar": False,
        "counts_toward_ground_truth": False,
    }
    if not apply:
        return report
    store = JobStore(str(database_path))
    created = cancelled = failed_sources_requeued = 0
    try:
        for candidate in candidates:
            replacement = replace(
                candidate.payload,
                request_id=_recovery_request_id(
                    candidate.payload, candidate.attempt_number
                ),
                media_sha256=candidate.media_sha256,
                attempt_number=candidate.attempt_number,
            )
            if candidate.source_status == "queued":
                _, _, was_created = store.supersede_queued(
                    candidate.job_id,
                    kind=replacement.stage,
                    payload=replacement.to_dict(),
                    consumer_id=candidate.consumer_id,
                    max_attempts=candidate.max_attempts,
                    idempotency_key=replacement.idempotency_key,
                    reason="superseded by integrity-bound controlled media job",
                    error_kind="media_integrity_superseded",
                )
                if was_created:
                    created += 1
                cancelled += 1
            else:
                existing = store.connection.execute(
                    "SELECT job_id FROM jobs WHERE consumer_id = ? AND idempotency_key = ?",
                    (candidate.consumer_id, replacement.idempotency_key),
                ).fetchone()
                enqueue_vision_review(
                    store,
                    replacement,
                    candidate.consumer_id,
                    max_attempts=candidate.max_attempts,
                )
                if existing is None:
                    created += 1
                failed_sources_requeued += 1
    finally:
        store.close()

    after = _decision_snapshot(database_path, consumer_id)
    if before != after:
        raise MediaIntegrityRecoveryError(
            "human or final decision state changed during media recovery"
        )
    report.update(
        {
            "jobs_cancelled": cancelled,
            "jobs_created": created,
            "failed_sources_requeued": failed_sources_requeued,
            "decision_state_after": after,
        }
    )
    return report


def _plan(
    database: Path,
    media_root: Path,
    *,
    consumer_id: str,
    limit: int | None,
    excluded_context_marker: str,
) -> tuple[list[_Candidate], dict[str, int], int]:
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    candidates: list[_Candidate] = []
    states: dict[str, int] = {}
    try:
        connection.execute("PRAGMA query_only = ON")
        running_jobs = int(
            connection.execute(
                """SELECT COUNT(*) FROM jobs
                WHERE consumer_id = ? AND status = 'running'
                  AND kind IN ('vision_review_1', 'vision_review_2')
                  AND instr(
                    COALESCE(json_extract(payload_json, '$.context'), ''), ?
                  ) = 0""",
                (consumer_id, excluded_context_marker),
            ).fetchone()[0]
        )
        rows = connection.execute(
            """
            SELECT job_id, status, consumer_id, max_attempts, payload_json
            FROM jobs
            WHERE consumer_id = ?
              AND (
                status = 'queued'
                OR (
                  status = 'failed' AND error_kind = 'worker_error'
                  AND error LIKE 'AttemptConflictError:%'
                )
              )
              AND kind IN ('vision_review_1', 'vision_review_2')
              AND instr(COALESCE(json_extract(payload_json, '$.context'), ''), ?) = 0
            ORDER BY COALESCE(available_at, created_at), created_at
            """,
            (consumer_id, excluded_context_marker),
        ).fetchall()
        if limit is not None:
            rows = rows[:limit]
        for row in rows:
            try:
                payload = VisionReviewJobPayload.from_mapping(
                    json.loads(row["payload_json"])
                )
                try:
                    actual = _controlled_media_sha256(media_root, payload.media_ref)
                except FileNotFoundError:
                    state = "missing_media"
                else:
                    max_attempt = int(
                        connection.execute(
                            """SELECT COALESCE(MAX(attempt_number), 0)
                            FROM review_attempts
                            WHERE item_id = ? AND stage = ?""",
                            (payload.item_id, payload.stage),
                        ).fetchone()[0]
                    )
                    next_attempt = max(max_attempt + 1, payload.attempt_number)
                    attempt_conflict = payload.attempt_number <= max_attempt
                    media_hash = payload.media_sha256 or actual
                    already_recovered = False
                    if attempt_conflict:
                        already_recovered = (
                            connection.execute(
                                """SELECT 1 FROM jobs
                                WHERE consumer_id = ?
                                  AND status IN ('queued', 'running', 'succeeded')
                                  AND json_extract(payload_json, '$.item_id') = ?
                                  AND json_extract(payload_json, '$.stage') = ?
                                  AND json_extract(payload_json, '$.attempt_number') = ?
                                  AND json_extract(payload_json, '$.media_sha256') = ?
                                LIMIT 1""",
                                (
                                    str(row["consumer_id"]),
                                    payload.item_id,
                                    payload.stage,
                                    next_attempt,
                                    media_hash,
                                ),
                            ).fetchone()
                            is not None
                        )
                    if attempt_conflict and already_recovered:
                        state = "attempt_conflict_already_recovered"
                    elif attempt_conflict:
                        state = "repairable_attempt_conflict"
                    elif payload.media_sha256 is not None:
                        state = "already_integrity_bound"
                    elif actual == payload.content_sha256:
                        state = "legacy_hash_matches"
                    else:
                        state = "repairable_hash_mismatch"
                    if state in {
                        "repairable_attempt_conflict",
                        "repairable_hash_mismatch",
                    }:
                        candidates.append(
                            _Candidate(
                                job_id=str(row["job_id"]),
                                source_status=str(row["status"]),
                                consumer_id=str(row["consumer_id"]),
                                max_attempts=int(row["max_attempts"]),
                                payload=payload,
                                media_sha256=media_hash,
                                attempt_number=next_attempt,
                            )
                        )
            except (OSError, TypeError, ValueError):
                state = "invalid_payload"
            states[state] = states.get(state, 0) + 1
    finally:
        connection.close()
    return candidates, states, running_jobs


def _controlled_media_sha256(root: Path, media_ref: str) -> str:
    if not media_ref.startswith("media://"):
        raise ValueError("media_ref must use media://")
    relative = Path(media_ref.removeprefix("media://"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("media_ref escapes media_root")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("media_ref contains a symlink")
    descriptor = os.open(current, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    digest = hashlib.sha256()
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("media_ref must resolve to a regular file")
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _recovery_request_id(
    payload: VisionReviewJobPayload, attempt_number: int
) -> str:
    digest = hashlib.sha256(payload.request_id.encode("utf-8")).hexdigest()[:16]
    return (
        f"{payload.item_id[:56]}:{payload.stage}:{attempt_number}:"
        f"media-recovery:{digest}"
    )


def _decision_snapshot(database: Path, consumer_id: str) -> dict[str, int]:
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        return {
            "quality_decisions": int(
                connection.execute(
                    "SELECT COUNT(*) FROM quality_decisions WHERE consumer_id = ?",
                    (consumer_id,),
                ).fetchone()[0]
            )
            if "quality_decisions" in tables
            else 0,
            "resolved_quality_samples": int(
                connection.execute(
                    """SELECT COUNT(*) FROM quality_samples
                    WHERE consumer_id = ? AND final_decision IS NOT NULL""",
                    (consumer_id,),
                ).fetchone()[0]
            )
            if "quality_samples" in tables
            else 0,
            "final_review_decisions": int(
                connection.execute(
                    """SELECT COUNT(*) FROM review_items
                    WHERE consumer_id = ? AND final_decision IS NOT NULL""",
                    (consumer_id,),
                ).fetchone()[0]
            )
            if "review_items" in tables
            else 0,
        }
    finally:
        connection.close()


def _regular_database(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("database must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("database must be a regular file")
    return resolved
