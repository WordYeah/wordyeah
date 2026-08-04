from __future__ import annotations

import json
from datetime import datetime, timezone
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
    ) -> str:
        if not consumer_id or not media_ref or not policy_profile:
            raise ValueError("consumer_id, media_ref, and policy_profile are required")
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
                  (submission_id, consumer_id, content_sha256, media_type, media_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (submission_id, consumer_id, result.content_sha256, result.media_type, media_ref, now),
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
