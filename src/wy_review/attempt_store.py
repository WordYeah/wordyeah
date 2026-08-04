from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from wy_core.database import open_database


ReviewStage = Literal["fast_scan", "vision_review_1", "vision_review_2", "human_review"]
AttemptActor = Literal["system", "agent", "reviewer"]
AttemptDecision = Literal["allow", "block", "review", "error"]
AttemptStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]

_STAGES = frozenset({"fast_scan", "vision_review_1", "vision_review_2", "human_review"})
_ACTOR_TYPES = frozenset({"system", "agent", "reviewer"})
_DECISIONS = frozenset({"allow", "block", "review", "error"})
_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})


class AttemptConflictError(RuntimeError):
    """Raised when an idempotency key is reused for different attempt data."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ReviewAttempt:
    attempt_id: str
    item_id: str
    stage: ReviewStage
    attempt_number: int
    actor_type: AttemptActor
    provider: str | None
    model_id: str | None
    model_version: str | None
    prompt_version: str | None
    decision: AttemptDecision | None
    confidence: float | None
    reasons: tuple[str, ...]
    findings: tuple[dict[str, object], ...]
    evidence: tuple[dict[str, object], ...]
    status: AttemptStatus
    parent_attempt_id: str | None
    started_at: str | None
    completed_at: str | None
    elapsed_ms: float | None
    error: str | None
    created_at: str

    @property
    def idempotency_key(self) -> tuple[str, ReviewStage, int]:
        return (self.item_id, self.stage, self.attempt_number)

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "item_id": self.item_id,
            "stage": self.stage,
            "attempt_number": self.attempt_number,
            "actor_type": self.actor_type,
            "provider": self.provider,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "decision": self.decision,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "findings": [dict(finding) for finding in self.findings],
            "evidence": [dict(item) for item in self.evidence],
            "status": self.status,
            "parent_attempt_id": self.parent_attempt_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "created_at": self.created_at,
        }


class ReviewAttemptStore:
    """Append-only persistence for schema-v3 review attempts.

    An attempt is inserted once as a complete snapshot. Reusing
    ``(item_id, stage, attempt_number)`` with the same snapshot is an
    idempotent read; reusing it with different data is a conflict. No update or
    delete operation is exposed.
    """

    def __init__(self, database: str = ":memory:") -> None:
        self.connection = open_database(database)
        version = self.connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
        if int(version) < 3:
            self.connection.close()
            raise RuntimeError("review attempt storage requires schema version 3")

    def close(self) -> None:
        self.connection.close()

    def append_attempt(
        self,
        *,
        item_id: str,
        stage: ReviewStage,
        attempt_number: int,
        actor_type: AttemptActor = "agent",
        provider: str | None = None,
        model_id: str | None = None,
        model_version: str | None = None,
        prompt_version: str | None = None,
        decision: AttemptDecision | None = None,
        confidence: float | None = None,
        reasons: Sequence[str] = (),
        findings: Sequence[Mapping[str, object]] = (),
        evidence: Sequence[Mapping[str, object]] = (),
        status: AttemptStatus = "succeeded",
        parent_attempt_id: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        elapsed_ms: float | None = None,
        error: str | None = None,
        attempt_id: str | None = None,
        created_at: str | None = None,
    ) -> ReviewAttempt:
        self._validate(
            item_id=item_id,
            stage=stage,
            attempt_number=attempt_number,
            actor_type=actor_type,
            decision=decision,
            confidence=confidence,
            status=status,
            elapsed_ms=elapsed_ms,
        )
        generated_id = uuid5(
            NAMESPACE_URL, f"wordyeah:review-attempt:{item_id}:{stage}:{attempt_number}"
        ).hex
        proposed = ReviewAttempt(
            attempt_id=attempt_id or generated_id,
            item_id=item_id,
            stage=stage,
            attempt_number=attempt_number,
            actor_type=actor_type,
            provider=provider,
            model_id=model_id,
            model_version=model_version,
            prompt_version=prompt_version,
            decision=decision,
            confidence=confidence,
            reasons=tuple(reasons),
            findings=tuple(dict(finding) for finding in findings),
            evidence=tuple(dict(item) for item in evidence),
            status=status,
            parent_attempt_id=parent_attempt_id,
            started_at=started_at,
            completed_at=completed_at,
            elapsed_ms=elapsed_ms,
            error=error,
            created_at=created_at or _now(),
        )

        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            existing_row = cursor.execute(
                """
                SELECT * FROM review_attempts
                WHERE item_id = ? AND stage = ? AND attempt_number = ?
                """,
                proposed.idempotency_key,
            ).fetchone()
            if existing_row is not None:
                existing = self._row(existing_row)
                if not self._same_snapshot(existing, proposed, ignore_generated_fields=True):
                    raise AttemptConflictError(
                        "review attempt idempotency key already contains different data"
                    )
                self.connection.commit()
                return existing

            cursor.execute(
                """
                INSERT INTO review_attempts
                  (attempt_id, item_id, stage, attempt_number, actor_type, provider,
                   model_id, model_version, prompt_version, decision, confidence,
                   reasons_json, findings_json, evidence_json, status,
                   parent_attempt_id, started_at, completed_at, elapsed_ms, error,
                   created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposed.attempt_id,
                    proposed.item_id,
                    proposed.stage,
                    proposed.attempt_number,
                    proposed.actor_type,
                    proposed.provider,
                    proposed.model_id,
                    proposed.model_version,
                    proposed.prompt_version,
                    proposed.decision,
                    proposed.confidence,
                    _canonical_json(proposed.reasons),
                    _canonical_json(proposed.findings),
                    _canonical_json(proposed.evidence),
                    proposed.status,
                    proposed.parent_attempt_id,
                    proposed.started_at,
                    proposed.completed_at,
                    proposed.elapsed_ms,
                    proposed.error,
                    proposed.created_at,
                ),
            )
            self.connection.commit()
            return proposed
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise AttemptConflictError(f"could not append review attempt: {exc}") from exc
        except Exception:
            self.connection.rollback()
            raise

    def append(self, attempt: ReviewAttempt) -> ReviewAttempt:
        return self.append_attempt(**attempt.to_dict())

    def get(self, attempt_id: str) -> ReviewAttempt:
        row = self.connection.execute(
            "SELECT * FROM review_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"review attempt not found: {attempt_id}")
        return self._row(row)

    def get_for_stage(
        self, item_id: str, stage: ReviewStage, attempt_number: int
    ) -> ReviewAttempt:
        row = self.connection.execute(
            """
            SELECT * FROM review_attempts
            WHERE item_id = ? AND stage = ? AND attempt_number = ?
            """,
            (item_id, stage, attempt_number),
        ).fetchone()
        if row is None:
            raise KeyError(f"review attempt not found: {item_id}/{stage}/{attempt_number}")
        return self._row(row)

    def list_attempts(
        self, item_id: str, stage: ReviewStage | None = None
    ) -> list[ReviewAttempt]:
        if stage is not None and stage not in _STAGES:
            raise ValueError("unknown review stage")
        if stage is None:
            rows = self.connection.execute(
                """
                SELECT * FROM review_attempts WHERE item_id = ?
                ORDER BY created_at, attempt_id
                """,
                (item_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM review_attempts WHERE item_id = ? AND stage = ?
                ORDER BY attempt_number
                """,
                (item_id, stage),
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_recent(self, limit: int = 200) -> list[ReviewAttempt]:
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        rows = self.connection.execute(
            "SELECT * FROM review_attempts ORDER BY created_at DESC, attempt_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def next_attempt_number(self, item_id: str, stage: ReviewStage) -> int:
        if stage not in _STAGES:
            raise ValueError("unknown review stage")
        row = self.connection.execute(
            "SELECT COALESCE(MAX(attempt_number), 0) FROM review_attempts WHERE item_id = ? AND stage = ?",
            (item_id, stage),
        ).fetchone()
        return int(row[0]) + 1

    @staticmethod
    def _validate(
        *,
        item_id: str,
        stage: str,
        attempt_number: int,
        actor_type: str,
        decision: str | None,
        confidence: float | None,
        status: str,
        elapsed_ms: float | None,
    ) -> None:
        if not item_id:
            raise ValueError("item_id is required")
        if stage not in _STAGES:
            raise ValueError("unknown review stage")
        if attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")
        if actor_type not in _ACTOR_TYPES:
            raise ValueError("unknown attempt actor type")
        if decision is not None and decision not in _DECISIONS:
            raise ValueError("unknown attempt decision")
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if status not in _STATUSES:
            raise ValueError("unknown attempt status")
        if elapsed_ms is not None and elapsed_ms < 0:
            raise ValueError("elapsed_ms cannot be negative")

    @staticmethod
    def _same_snapshot(
        existing: ReviewAttempt,
        proposed: ReviewAttempt,
        *,
        ignore_generated_fields: bool,
    ) -> bool:
        left = existing.to_dict()
        right = proposed.to_dict()
        if ignore_generated_fields:
            left.pop("attempt_id")
            left.pop("created_at")
            right.pop("attempt_id")
            right.pop("created_at")
        return _canonical_json(left) == _canonical_json(right)

    @staticmethod
    def _row(row: sqlite3.Row) -> ReviewAttempt:
        return ReviewAttempt(
            attempt_id=row["attempt_id"],
            item_id=row["item_id"],
            stage=row["stage"],
            attempt_number=int(row["attempt_number"]),
            actor_type=row["actor_type"],
            provider=row["provider"],
            model_id=row["model_id"],
            model_version=row["model_version"],
            prompt_version=row["prompt_version"],
            decision=row["decision"],
            confidence=row["confidence"],
            reasons=tuple(json.loads(row["reasons_json"])),
            findings=tuple(json.loads(row["findings_json"])),
            evidence=tuple(json.loads(row["evidence_json"])),
            status=row["status"],
            parent_attempt_id=row["parent_attempt_id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            elapsed_ms=row["elapsed_ms"],
            error=row["error"],
            created_at=row["created_at"],
        )


# Short alias for callers that already live in the review package.
AttemptStore = ReviewAttemptStore
