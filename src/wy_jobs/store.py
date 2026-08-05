from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal
from uuid import uuid4

from wy_core.database import open_database

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def retry_delay_seconds(attempt: int, *, base_seconds: float = 1.0, cap_seconds: float = 300.0) -> float:
    """Return deterministic capped exponential backoff for a 1-based attempt."""

    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    if base_seconds <= 0 or cap_seconds <= 0:
        raise ValueError("backoff values must be positive")
    return min(cap_seconds, base_seconds * (2 ** (attempt - 1)))


@dataclass(frozen=True)
class Job:
    job_id: str
    kind: str
    payload: dict[str, Any]
    result: dict[str, Any] | None
    status: JobStatus
    consumer_id: str
    attempts: int
    max_attempts: int
    worker_id: str | None
    lease_until: str | None
    error: str | None
    created_at: str
    updated_at: str
    idempotency_key: str | None = None
    available_at: str | None = None
    error_kind: str | None = None
    retryable: bool | None = None
    dead_lettered_at: str | None = None

    @property
    def dead_lettered(self) -> bool:
        return self.status == "failed" and self.dead_lettered_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "payload": self.payload,
            "result": self.result,
            "status": self.status,
            "consumer_id": self.consumer_id,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "worker_id": self.worker_id,
            "lease_until": self.lease_until,
            "error": self.error,
            "idempotency_key": self.idempotency_key,
            "available_at": self.available_at,
            "error_kind": self.error_kind,
            "retryable": self.retryable,
            "dead_lettered": self.dead_lettered,
            "dead_lettered_at": self.dead_lettered_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobStore:
    """SQLite durable queue with idempotent enqueue, backoff, and lease recovery."""

    def __init__(self, database: str = ":memory:") -> None:
        self.connection = open_database(database)
        self._ensure_queue_columns()

    def _ensure_queue_columns(self) -> None:
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(jobs)")}
        additions = {
            "idempotency_key": "TEXT",
            "available_at": "TEXT",
            "error_kind": "TEXT",
            "retryable": "INTEGER",
            "dead_lettered_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                self.connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
        self.connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency "
            "ON jobs(consumer_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_available "
            "ON jobs(status, available_at, created_at)"
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        consumer_id: str,
        max_attempts: int = 3,
        *,
        idempotency_key: str | None = None,
        available_at: datetime | str | None = None,
    ) -> Job:
        if not kind or len(kind) > 64:
            raise ValueError("job kind must be between 1 and 64 characters")
        if not consumer_id or len(consumer_id) > 128:
            raise ValueError("consumer_id must be between 1 and 128 characters")
        if max_attempts < 1 or max_attempts > 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if idempotency_key is not None and (not idempotency_key or len(idempotency_key) > 255):
            raise ValueError("idempotency_key must be between 1 and 255 characters")
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        available_text = _stamp(available_at) if isinstance(available_at, datetime) else available_at
        now = _stamp()
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = cursor.execute(
                    "SELECT * FROM jobs WHERE consumer_id = ? AND idempotency_key = ?",
                    (consumer_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    job = self._row(existing)
                    if (
                        job.kind != kind
                        or json.dumps(job.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) != payload_json
                        or job.max_attempts != max_attempts
                    ):
                        raise ValueError("job idempotency key already contains different data")
                    self.connection.commit()
                    return job
            job_id = uuid4().hex
            cursor.execute(
                """
                INSERT INTO jobs
                  (job_id, kind, payload_json, status, consumer_id, max_attempts,
                   idempotency_key, available_at, created_at, updated_at)
                VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)
                """,
                (job_id, kind, payload_json, consumer_id, max_attempts, idempotency_key, available_text, now, now),
            )
            self.connection.commit()
            return self.get(job_id)
        except sqlite3.IntegrityError:
            self.connection.rollback()
            if idempotency_key is None:
                raise
            existing = self.connection.execute(
                "SELECT * FROM jobs WHERE consumer_id = ? AND idempotency_key = ?",
                (consumer_id, idempotency_key),
            ).fetchone()
            if existing is None:
                raise
            job = self._row(existing)
            if job.kind != kind or job.payload != payload or job.max_attempts != max_attempts:
                raise ValueError("job idempotency key already contains different data")
            return job
        except Exception:
            self.connection.rollback()
            raise

    def get(self, job_id: str) -> Job:
        row = self.connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"job not found: {job_id}")
        return self._row(row)

    def count_active(self, consumer_id: str | None = None) -> int:
        if consumer_id is None:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE consumer_id = ? AND status IN ('queued', 'running')",
                (consumer_id,),
            ).fetchone()
        return int(row["count"])

    def claim(
        self,
        worker_id: str,
        lease_seconds: int = 120,
        *,
        kinds: Iterable[str] | None = None,
        consumer_id: str | None = None,
        context_marker: str | None = None,
    ) -> Job | None:
        if not worker_id:
            raise ValueError("worker_id is required")
        if lease_seconds < 1 or lease_seconds > 86400:
            raise ValueError("lease_seconds must be between 1 and 86400")
        selected_kinds = tuple(dict.fromkeys(kinds or ()))
        if any(not kind for kind in selected_kinds):
            raise ValueError("job kinds must not be empty")
        if consumer_id is not None and (not consumer_id or len(consumer_id) > 128):
            raise ValueError("consumer_id must be between 1 and 128 characters")
        if context_marker is not None and (
            not context_marker
            or len(context_marker) > 256
            or any(ord(char) < 32 for char in context_marker)
        ):
            raise ValueError(
                "context_marker must be printable and between 1 and 256 characters"
            )
        now = _now()
        now_text = _stamp(now)
        lease_text = _stamp(now + timedelta(seconds=lease_seconds))
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                UPDATE jobs
                SET status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END,
                    worker_id = NULL, lease_until = NULL,
                    available_at = CASE WHEN attempts >= max_attempts THEN available_at ELSE ? END,
                    error = 'worker lease expired', error_kind = 'lease_expired', retryable = 1,
                    dead_lettered_at = CASE WHEN attempts >= max_attempts THEN ? ELSE NULL END,
                    updated_at = ?
                WHERE status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?
                """,
                (now_text, now_text, now_text, now_text),
            )
            parameters: list[object] = [now_text]
            where = "status = 'queued' AND (available_at IS NULL OR available_at <= ?)"
            if selected_kinds:
                where += f" AND kind IN ({','.join('?' for _ in selected_kinds)})"
                parameters.extend(selected_kinds)
            if consumer_id is not None:
                where += " AND consumer_id = ?"
                parameters.append(consumer_id)
            if context_marker is not None:
                where += (
                    " AND instr(COALESCE(json_extract(payload_json, '$.context'), ''), ?) > 0"
                )
                parameters.append(context_marker)
            row = cursor.execute(
                f"SELECT * FROM jobs WHERE {where} ORDER BY COALESCE(available_at, created_at), created_at LIMIT 1",
                parameters,
            ).fetchone()
            if row is None:
                self.connection.commit()
                return None
            updated = cursor.execute(
                """
                UPDATE jobs
                SET status = 'running', worker_id = ?, lease_until = ?, attempts = attempts + 1,
                    error = NULL, error_kind = NULL, retryable = NULL, dead_lettered_at = NULL,
                    updated_at = ?
                WHERE job_id = ? AND status = 'queued'
                """,
                (worker_id, lease_text, now_text, row["job_id"]),
            )
            if updated.rowcount != 1:
                self.connection.rollback()
                return None
            self.connection.commit()
            return self.get(row["job_id"])
        except Exception:
            self.connection.rollback()
            raise

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int = 120) -> Job:
        if lease_seconds < 1 or lease_seconds > 86400:
            raise ValueError("lease_seconds must be between 1 and 86400")
        now = _now()
        updated = self.connection.execute(
            "UPDATE jobs SET lease_until = ?, updated_at = ? "
            "WHERE job_id = ? AND status = 'running' AND worker_id = ?",
            (_stamp(now + timedelta(seconds=lease_seconds)), _stamp(now), job_id, worker_id),
        )
        if updated.rowcount != 1:
            self.connection.commit()
            raise ValueError("job is missing or not owned by worker")
        self.connection.commit()
        return self.get(job_id)

    def complete(self, job_id: str, worker_id: str, result: dict[str, Any]) -> Job:
        updated = self.connection.execute(
            """
            UPDATE jobs
            SET status = 'succeeded', result_json = ?, worker_id = NULL, lease_until = NULL,
                error = NULL, error_kind = NULL, retryable = NULL, dead_lettered_at = NULL, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND worker_id = ?
            """,
            (json.dumps(result, ensure_ascii=False), _stamp(), job_id, worker_id),
        )
        if updated.rowcount != 1:
            self.connection.commit()
            raise ValueError("job is missing or not owned by worker")
        self.connection.commit()
        return self.get(job_id)

    def fail(
        self,
        job_id: str,
        worker_id: str,
        error: str,
        *,
        error_kind: str = "worker_error",
        retryable: bool = True,
        retry_after_seconds: float | None = None,
        backoff_base_seconds: float = 1.0,
        backoff_cap_seconds: float = 300.0,
    ) -> Job:
        row = self.get(job_id)
        should_retry = retryable and row.attempts < row.max_attempts
        now = _now()
        if should_retry:
            delay = retry_after_seconds
            if delay is None:
                delay = retry_delay_seconds(
                    row.attempts, base_seconds=backoff_base_seconds, cap_seconds=backoff_cap_seconds
                )
            if delay < 0:
                raise ValueError("retry_after_seconds cannot be negative")
            available_at = _stamp(now + timedelta(seconds=delay))
        else:
            available_at = row.available_at
        updated = self.connection.execute(
            """
            UPDATE jobs
            SET status = ?, error = ?, error_kind = ?, retryable = ?, available_at = ?,
                dead_lettered_at = ?, worker_id = NULL, lease_until = NULL, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND worker_id = ?
            """,
            (
                "queued" if should_retry else "failed",
                error[:2000],
                error_kind[:128],
                1 if retryable else 0,
                available_at,
                None if should_retry else _stamp(now),
                _stamp(now),
                job_id,
                worker_id,
            ),
        )
        if updated.rowcount != 1:
            self.connection.commit()
            raise ValueError("job is missing or not owned by worker")
        self.connection.commit()
        return self.get(job_id)

    def cancel(self, job_id: str) -> Job:
        updated = self.connection.execute(
            "UPDATE jobs SET status = 'cancelled', worker_id = NULL, lease_until = NULL, updated_at = ? "
            "WHERE job_id = ? AND status = 'queued'",
            (_stamp(), job_id),
        )
        if updated.rowcount != 1:
            self.connection.commit()
            return self.get(job_id)
        self.connection.commit()
        return self.get(job_id)

    def _row(self, row: sqlite3.Row) -> Job:
        keys = set(row.keys())
        return Job(
            job_id=row["job_id"],
            kind=row["kind"],
            payload=json.loads(row["payload_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            status=row["status"],
            consumer_id=row["consumer_id"],
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            worker_id=row["worker_id"],
            lease_until=row["lease_until"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            idempotency_key=row["idempotency_key"] if "idempotency_key" in keys else None,
            available_at=row["available_at"] if "available_at" in keys else None,
            error_kind=row["error_kind"] if "error_kind" in keys else None,
            retryable=bool(row["retryable"]) if "retryable" in keys and row["retryable"] is not None else None,
            dead_lettered_at=row["dead_lettered_at"] if "dead_lettered_at" in keys else None,
        )
