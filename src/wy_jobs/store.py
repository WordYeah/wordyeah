from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from wy_core.database import open_database

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobStore:
    """SQLite durable queue with lease-based recovery."""

    def __init__(self, database: str = ":memory:") -> None:
        self.connection = open_database(database)

    def close(self) -> None:
        self.connection.close()

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        consumer_id: str,
        max_attempts: int = 3,
    ) -> Job:
        if not kind or len(kind) > 64:
            raise ValueError("job kind must be between 1 and 64 characters")
        if not consumer_id or len(consumer_id) > 128:
            raise ValueError("consumer_id must be between 1 and 128 characters")
        if max_attempts < 1 or max_attempts > 10:
            raise ValueError("max_attempts must be between 1 and 10")
        job_id = uuid4().hex
        now = _stamp()
        self.connection.execute(
            """
            INSERT INTO jobs
              (job_id, kind, payload_json, status, consumer_id, max_attempts, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (job_id, kind, json.dumps(payload, ensure_ascii=False), consumer_id, max_attempts, now, now),
        )
        self.connection.commit()
        return self.get(job_id)

    def get(self, job_id: str) -> Job:
        row = self.connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"job not found: {job_id}")
        return self._row(row)

    def count_active(self, consumer_id: str | None = None) -> int:
        """Count queued or leased jobs before admitting more work."""

        if consumer_id is None:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT COUNT(*) AS count FROM jobs
                WHERE consumer_id = ? AND status IN ('queued', 'running')
                """,
                (consumer_id,),
            ).fetchone()
        return int(row["count"])

    def claim(self, worker_id: str, lease_seconds: int = 120) -> Job | None:
        if not worker_id:
            raise ValueError("worker_id is required")
        if lease_seconds < 1 or lease_seconds > 86400:
            raise ValueError("lease_seconds must be between 1 and 86400")
        now = _now()
        now_text = _stamp(now)
        lease_text = _stamp(now + timedelta(seconds=lease_seconds))
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                UPDATE jobs
                SET status = CASE WHEN attempts + 1 >= max_attempts THEN 'failed' ELSE 'queued' END,
                    worker_id = NULL, lease_until = NULL,
                    error = CASE WHEN attempts + 1 >= max_attempts THEN 'lease_expired' ELSE error END,
                    updated_at = ?
                WHERE status = 'running' AND lease_until IS NOT NULL AND lease_until <= ?
                """,
                (now_text, now_text),
            )
            row = cursor.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                self.connection.commit()
                return None
            updated = cursor.execute(
                """
                UPDATE jobs
                SET status = 'running', worker_id = ?, lease_until = ?, attempts = attempts + 1, updated_at = ?
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
        now = _now()
        updated = self.connection.execute(
            """
            UPDATE jobs SET lease_until = ?, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND worker_id = ?
            """,
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
            SET status = 'succeeded', result_json = ?, worker_id = NULL, lease_until = NULL, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND worker_id = ?
            """,
            (json.dumps(result, ensure_ascii=False), _stamp(), job_id, worker_id),
        )
        if updated.rowcount != 1:
            self.connection.commit()
            raise ValueError("job is missing or not owned by worker")
        self.connection.commit()
        return self.get(job_id)

    def fail(self, job_id: str, worker_id: str, error: str) -> Job:
        row = self.get(job_id)
        next_status = "queued" if row.attempts < row.max_attempts else "failed"
        updated = self.connection.execute(
            """
            UPDATE jobs
            SET status = ?, error = ?, worker_id = NULL, lease_until = NULL, updated_at = ?
            WHERE job_id = ? AND status = 'running' AND worker_id = ?
            """,
            (next_status, error[:2000], _stamp(), job_id, worker_id),
        )
        if updated.rowcount != 1:
            self.connection.commit()
            raise ValueError("job is missing or not owned by worker")
        self.connection.commit()
        return self.get(job_id)

    def cancel(self, job_id: str) -> Job:
        updated = self.connection.execute(
            """
            UPDATE jobs SET status = 'cancelled', worker_id = NULL, lease_until = NULL, updated_at = ?
            WHERE job_id = ? AND status = 'queued'
            """,
            (_stamp(), job_id),
        )
        if updated.rowcount != 1:
            self.connection.commit()
            return self.get(job_id)
        self.connection.commit()
        return self.get(job_id)

    def _row(self, row: sqlite3.Row) -> Job:
        result = json.loads(row["result_json"]) if row["result_json"] else None
        return Job(
            job_id=row["job_id"],
            kind=row["kind"],
            payload=json.loads(row["payload_json"]),
            result=result,
            status=row["status"],
            consumer_id=row["consumer_id"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            worker_id=row["worker_id"],
            lease_until=row["lease_until"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
