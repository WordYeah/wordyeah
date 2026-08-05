from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Mapping
from uuid import uuid4

from .contracts import ModerationResult
from .database import open_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResultStore:
    """Persist moderation metadata and findings without storing image bytes."""

    def __init__(self, database: str = ":memory:") -> None:
        self.connection = open_database(database)

    def close(self) -> None:
        self.connection.close()

    def record(
        self,
        result: ModerationResult,
        consumer_id: str,
        media_ref: str,
        policy_profile: str,
        *,
        source_id: str | None = None,
        source_ref: str | None = None,
        source_metadata: Mapping[str, object] | None = None,
    ) -> str:
        if not consumer_id or not media_ref or not policy_profile:
            raise ValueError("consumer_id, media_ref, and policy_profile are required")
        if source_id:
            existing = self.connection.execute(
                """
                SELECT runs.run_id
                FROM model_runs AS runs
                JOIN submissions AS submissions ON submissions.submission_id = runs.submission_id
                WHERE submissions.consumer_id = ? AND submissions.source_id = ?
                ORDER BY runs.created_at LIMIT 1
                """,
                (consumer_id, source_id),
            ).fetchone()
            if existing is not None:
                return str(existing["run_id"])
        submission_id = uuid4().hex
        run_id = uuid4().hex
        now = _now()
        model_version = result.model_versions.get("media.nsfw", "unknown")
        policy_version = result.model_versions.get("policy", "policy-default")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                """
                INSERT INTO submissions
                  (submission_id, consumer_id, source_id, source_ref, source_metadata_json,
                   content_sha256, media_type, media_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    consumer_id,
                    source_id,
                    source_ref,
                    json.dumps(dict(source_metadata or {}), ensure_ascii=False, sort_keys=True),
                    result.content_sha256,
                    result.media_type,
                    media_ref,
                    now,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO model_runs
                  (run_id, submission_id, model_version, decision, result_json, elapsed_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    submission_id,
                    model_version,
                    result.decision,
                    json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True),
                    result.elapsed_ms,
                    now,
                ),
            )
            for finding in result.findings:
                self.connection.execute(
                    """
                    INSERT INTO findings
                      (finding_id, run_id, category, label, score, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (uuid4().hex, run_id, finding.category, finding.label, finding.score, finding.source),
                )
            self.connection.execute(
                """
                INSERT OR IGNORE INTO policy_versions
                  (policy_version, profile, policy_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    policy_version,
                    policy_profile,
                    json.dumps(
                        {"profile": policy_profile, "model_versions": result.model_versions},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return run_id

    def count_runs(self, consumer_id: str | None = None) -> int:
        if consumer_id is None:
            row = self.connection.execute("SELECT COUNT(*) AS count FROM model_runs").fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM model_runs AS runs
                JOIN submissions AS submissions ON submissions.submission_id = runs.submission_id
                WHERE submissions.consumer_id = ?
                """,
                (consumer_id,),
            ).fetchone()
        return int(row["count"])

    def decision_summary(self, consumer_id: str) -> dict[str, int]:
        if not consumer_id:
            raise ValueError("consumer_id is required")
        row = self.connection.execute(
            """
            SELECT
              COUNT(*) AS total,
              COALESCE(SUM(CASE WHEN runs.decision = 'allow' THEN 1 ELSE 0 END), 0) AS allow_count,
              COALESCE(SUM(CASE WHEN runs.decision = 'review' THEN 1 ELSE 0 END), 0) AS review_count,
              COALESCE(SUM(CASE WHEN runs.decision = 'block' THEN 1 ELSE 0 END), 0) AS block_count,
              COALESCE(SUM(CASE WHEN runs.decision = 'error' THEN 1 ELSE 0 END), 0) AS error_count
            FROM model_runs AS runs
            JOIN submissions AS submissions ON submissions.submission_id = runs.submission_id
            WHERE submissions.consumer_id = ?
            """,
            (consumer_id,),
        ).fetchone()
        return {
            "total": int(row["total"]),
            "allow": int(row["allow_count"]),
            "review": int(row["review_count"]),
            "block": int(row["block_count"]),
            "error": int(row["error_count"]),
        }

    def daily_volume(self, consumer_id: str, *, since_date: str) -> dict[str, int]:
        if not consumer_id or not since_date:
            raise ValueError("consumer_id and since_date are required")
        rows = self.connection.execute(
            """
            SELECT substr(submissions.created_at, 1, 10) AS day, COUNT(*) AS count
            FROM model_runs AS runs
            JOIN submissions AS submissions ON submissions.submission_id = runs.submission_id
            WHERE submissions.consumer_id = ?
              AND substr(submissions.created_at, 1, 10) >= ?
            GROUP BY substr(submissions.created_at, 1, 10)
            ORDER BY day
            """,
            (consumer_id, since_date),
        ).fetchall()
        return {str(row["day"]): int(row["count"]) for row in rows}
