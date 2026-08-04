from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from wy_core.contracts import ModerationResult
from wy_core.database import open_database

ReviewStatus = Literal["pending", "approved", "rejected", "held"]
ReviewAction = Literal["approve", "reject", "blacklist", "hold", "retry"]
AvatarAction = Literal["keep", "replace_default", "blacklist"]

SEVERE_BLACKLIST_CATEGORIES = frozenset(
    {"csam", "sexual_minors", "terrorism", "violent_extremism", "illegal_abuse"}
)


class ReviewConflictError(RuntimeError):
    """Raised when a review item changed before an optimistic action committed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    consumer_id: str
    content_sha256: str
    media_type: str
    media_ref: str
    decision_hint: str
    reasons: tuple[str, ...]
    findings: tuple[dict[str, object], ...]
    model_versions: dict[str, str]
    top_score: float | None
    request_id: str | None
    policy_version: str
    status: ReviewStatus
    version: int
    created_at: str
    reviewer: str | None = None
    review_note: str | None = None
    reviewed_at: str | None = None
    stage: str = "human_required"
    final_decision: str | None = None
    avatar_action: AvatarAction | None = None
    due_at: str | None = None
    assignee: str | None = None
    claim_until: str | None = None
    quality_sample: bool = False
    arbitration_required: bool = False
    appealed: bool = False
    updated_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "consumer_id": self.consumer_id,
            "content_sha256": self.content_sha256,
            "media_type": self.media_type,
            "media_ref": self.media_ref,
            "decision_hint": self.decision_hint,
            "reasons": list(self.reasons),
            "findings": [dict(finding) for finding in self.findings],
            "model_versions": dict(self.model_versions),
            "top_score": self.top_score,
            "request_id": self.request_id,
            "policy_version": self.policy_version,
            "status": self.status,
            "version": self.version,
            "created_at": self.created_at,
            "reviewer": self.reviewer,
            "review_note": self.review_note,
            "reviewed_at": self.reviewed_at,
            "stage": self.stage,
            "final_decision": self.final_decision,
            "avatar_action": self.avatar_action,
            "due_at": self.due_at,
            "assignee": self.assignee,
            "claim_until": self.claim_until,
            "quality_sample": self.quality_sample,
            "arbitration_required": self.arbitration_required,
            "appealed": self.appealed,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ReviewEvent:
    event_id: str
    item_id: str
    action: str
    reviewer: str
    note: str | None
    before_status: str | None
    after_status: str | None
    policy_version: str | None
    request_id: str | None
    ip_hash: str | None
    created_at: str
    actor_type: str = "reviewer"
    actor_id: str | None = None
    before_stage: str | None = None
    after_stage: str | None = None
    before_decision: str | None = None
    after_decision: str | None = None
    reason_code: str | None = None
    before_avatar_action: str | None = None
    after_avatar_action: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "item_id": self.item_id,
            "action": self.action,
            "reviewer": self.reviewer,
            "note": self.note,
            "before_status": self.before_status,
            "after_status": self.after_status,
            "policy_version": self.policy_version,
            "request_id": self.request_id,
            "ip_hash": self.ip_hash,
            "created_at": self.created_at,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "before_stage": self.before_stage,
            "after_stage": self.after_stage,
            "before_decision": self.before_decision,
            "after_decision": self.after_decision,
            "reason_code": self.reason_code,
            "before_avatar_action": self.before_avatar_action,
            "after_avatar_action": self.after_avatar_action,
        }


class ReviewStore:
    """SQLite review queue that stores metadata only, never media bytes."""

    def __init__(self, database: str = ":memory:") -> None:
        self.connection = open_database(database)

    def close(self) -> None:
        self.connection.close()

    def enqueue(
        self,
        result: ModerationResult,
        media_ref: str,
        consumer_id: str = "default",
    ) -> ReviewItem:
        if result.decision not in {"review", "block", "error"}:
            raise ValueError("only review, block, or error results enter the review queue")
        if not consumer_id or len(consumer_id) > 128:
            raise ValueError("consumer_id must be between 1 and 128 characters")
        if not media_ref or media_ref.startswith(("http://", "https://", "file://")):
            raise ValueError("media_ref must be a controlled local reference")
        existing = self.connection.execute(
            """
            SELECT * FROM review_items
            WHERE consumer_id = ? AND content_sha256 = ? AND status = 'pending'
            ORDER BY created_at LIMIT 1
            """,
            (consumer_id, result.content_sha256),
        ).fetchone()
        if existing is not None:
            return self._row(existing)

        item_id = uuid4().hex
        now = _now()
        policy_version = result.model_versions.get("policy", "policy-default")
        status = "held" if result.decision == "error" else "pending"
        self.connection.execute(
            """
            INSERT INTO review_items
              (item_id, consumer_id, content_sha256, media_type, media_ref,
               decision_hint, reasons_json, findings_json, model_versions_json,
               top_score, request_id, policy_version, status, version, created_at,
               stage, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                item_id,
                consumer_id,
                result.content_sha256,
                result.media_type,
                media_ref,
                result.decision,
                json.dumps(list(result.reasons), ensure_ascii=False),
                json.dumps(result.to_dict()["findings"], ensure_ascii=False),
                json.dumps(result.model_versions, ensure_ascii=False, sort_keys=True),
                result.top_score,
                result.request_id,
                policy_version,
                status,
                now,
                "fast_scan",
                now,
            ),
        )
        self.connection.commit()
        return self.get(item_id, consumer_id=consumer_id)

    def get(self, item_id: str, consumer_id: str | None = None) -> ReviewItem:
        if consumer_id is None:
            row = self.connection.execute(
                "SELECT * FROM review_items WHERE item_id = ?", (item_id,)
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT * FROM review_items WHERE item_id = ? AND consumer_id = ?",
                (item_id, consumer_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"review item not found: {item_id}")
        return self._row(row)

    def list_items(
        self,
        status: ReviewStatus | None = "pending",
        consumer_id: str | None = None,
        limit: int = 100,
        decision_hint: str | None = None,
    ) -> list[ReviewItem]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if status is not None and status not in {"pending", "approved", "rejected", "held"}:
            raise ValueError("unknown review status")
        clauses: list[str] = []
        parameters: list[object] = []
        if consumer_id is not None:
            clauses.append("consumer_id = ?")
            parameters.append(consumer_id)
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        if decision_hint is not None:
            clauses.append("decision_hint = ?")
            parameters.append(decision_hint)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"SELECT * FROM review_items{where} ORDER BY created_at DESC, item_id DESC LIMIT ?",
            (*parameters, limit),
        ).fetchall()
        return [self._row(row) for row in rows]

    def list_pending(self, limit: int = 100, consumer_id: str | None = None) -> list[ReviewItem]:
        return self.list_items(status="pending", consumer_id=consumer_id, limit=limit)

    def metrics(self, consumer_id: str | None = None) -> dict[str, float | int]:
        parameters: tuple[object, ...] = () if consumer_id is None else (consumer_id,)
        consumer_clause = "" if consumer_id is None else " AND consumer_id = ?"
        pending = self.connection.execute(
            f"""
            SELECT COUNT(*) AS count,
                   COALESCE(AVG((julianday('now') - julianday(created_at)) * 86400), 0) AS age
            FROM review_items
            WHERE status = 'pending'{consumer_clause}
            """,
            parameters,
        ).fetchone()
        event_rows = self.connection.execute(
            f"""
            SELECT action, COUNT(*) AS count
            FROM review_events
            JOIN review_items ON review_items.item_id = review_events.item_id
            WHERE 1 = 1{consumer_clause}
            GROUP BY action
            """,
            parameters,
        ).fetchall()
        metrics: dict[str, float | int] = {
            "pending": int(pending["count"]),
            "pending_age_seconds": round(float(pending["age"]), 3),
            "overturned": 0,
        }
        for row in event_rows:
            action = str(row["action"])
            count = int(row["count"])
            metrics[f"action_{action}"] = count
            if action == "retry":
                metrics["overturned"] = count
        return metrics

    def list_events(self, item_id: str, consumer_id: str | None = None) -> list[ReviewEvent]:
        self.get(item_id, consumer_id=consumer_id)
        rows = self.connection.execute(
            "SELECT * FROM review_events WHERE item_id = ? ORDER BY created_at, event_id",
            (item_id,),
        ).fetchall()
        return [self._event_row(row) for row in rows]

    def list_all_events(
        self, consumer_id: str | None = None, limit: int = 1000
    ) -> list[ReviewEvent]:
        if limit < 1 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        if consumer_id is None:
            rows = self.connection.execute(
                "SELECT * FROM review_events ORDER BY created_at DESC, event_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT review_events.* FROM review_events
                JOIN review_items ON review_items.item_id = review_events.item_id
                WHERE review_items.consumer_id = ?
                ORDER BY review_events.created_at DESC, review_events.event_id DESC
                LIMIT ?
                """,
                (consumer_id, limit),
            ).fetchall()
        return [self._event_row(row) for row in rows]

    def apply_route(
        self,
        item_id: str,
        *,
        stage: str,
        final_decision: str | None,
        reason_code: str,
        actor_id: str = "review-router",
        consumer_id: str | None = None,
    ) -> ReviewItem:
        """Persist a router transition and its audit event atomically."""

        allowed_stages = {
            "fast_scan", "vision_review_1", "vision_review_2", "human_required",
            "auto_approved", "auto_rejected", "model_error",
        }
        if stage not in allowed_stages:
            raise ValueError("unknown review stage")
        if final_decision not in {None, "allow", "block"}:
            raise ValueError("unknown final decision")
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            if consumer_id is None:
                row = cursor.execute(
                    "SELECT * FROM review_items WHERE item_id = ?", (item_id,)
                ).fetchone()
            else:
                row = cursor.execute(
                    "SELECT * FROM review_items WHERE item_id = ? AND consumer_id = ?",
                    (item_id, consumer_id),
                ).fetchone()
            if row is None:
                raise KeyError(f"review item not found: {item_id}")
            now = _now()
            status = row["status"]
            if stage == "auto_approved":
                status = "approved"
            elif stage == "auto_rejected":
                status = "rejected"
            elif stage == "model_error":
                status = "held"
            elif stage == "human_required" and status not in {"approved", "rejected"}:
                status = "pending"
            avatar_action = _route_avatar_action(row, stage)
            if (
                row["stage"] == stage
                and row["final_decision"] == final_decision
                and row["status"] == status
                and row["avatar_action"] == avatar_action
            ):
                self.connection.commit()
                return self._row(row)
            cursor.execute(
                """
                UPDATE review_items
                SET stage = ?, final_decision = ?, status = ?, avatar_action = ?,
                    updated_at = ?, version = version + 1
                WHERE item_id = ?
                """,
                (stage, final_decision, status, avatar_action, now, item_id),
            )
            cursor.execute(
                """
                INSERT INTO review_events
                  (event_id, item_id, action, reviewer, note, before_status, after_status,
                   policy_version, request_id, created_at, actor_type, actor_id,
                   before_stage, after_stage, before_decision, after_decision, reason_code,
                   before_avatar_action, after_avatar_action)
                VALUES (?, ?, 'route', ?, NULL, ?, ?, ?, ?, ?, 'agent', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex, item_id, actor_id, row["status"], status,
                    row["policy_version"], row["request_id"], now, actor_id,
                    row["stage"], stage, row["final_decision"], final_decision, reason_code,
                    row["avatar_action"], avatar_action,
                ),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get(item_id, consumer_id=consumer_id)

    def decide(
        self,
        item_id: str,
        action: ReviewAction,
        reviewer: str,
        note: str = "",
        consumer_id: str | None = None,
        expected_version: int | None = None,
        request_id: str | None = None,
        ip_hash: str | None = None,
    ) -> ReviewItem:
        if action not in {"approve", "reject", "blacklist", "hold", "retry"}:
            raise ValueError("unknown review action")
        if not reviewer or len(reviewer) > 128:
            raise ValueError("reviewer must be between 1 and 128 characters")
        if len(note) > 2000:
            raise ValueError("review note is too long")

        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            if consumer_id is None:
                row = cursor.execute(
                    "SELECT * FROM review_items WHERE item_id = ?", (item_id,)
                ).fetchone()
            else:
                row = cursor.execute(
                    "SELECT * FROM review_items WHERE item_id = ? AND consumer_id = ?",
                    (item_id, consumer_id),
                ).fetchone()
            if row is None:
                raise KeyError(f"review item not found: {item_id}")
            current_version = int(row["version"])
            if expected_version is not None and expected_version != current_version:
                raise ReviewConflictError("review item version is stale")
            before_status = row["status"]
            if action in {"approve", "reject", "blacklist", "hold"}:
                if before_status != "pending":
                    raise ReviewConflictError("review item is no longer pending")
                after_status: ReviewStatus = {
                    "approve": "approved",
                    "reject": "rejected",
                    "blacklist": "rejected",
                    "hold": "held",
                }[action]
                reviewer_value: str | None = reviewer
                note_value: str | None = note
                reviewed_at: str | None = _now()
            else:
                if before_status not in {"held", "rejected"}:
                    raise ReviewConflictError("only held or rejected items can be retried")
                after_status = "pending"
                reviewer_value = None
                note_value = None
                reviewed_at = None

            now = _now()
            avatar_action: AvatarAction | None = None if action == "retry" else {
                "approve": "keep",
                "reject": "replace_default",
                "blacklist": "blacklist",
                "hold": None,
            }[action]
            where = "item_id = ? AND status = ? AND version = ?"
            parameters: list[object] = [
                after_status,
                reviewer_value,
                note_value,
                reviewed_at,
                current_version + 1,
                item_id,
                before_status,
                current_version,
            ]
            if consumer_id is not None:
                where += " AND consumer_id = ?"
                parameters.append(consumer_id)
            updated = cursor.execute(
                f"""
                UPDATE review_items
                SET status = ?, reviewer = ?, review_note = ?, reviewed_at = ?, version = ?,
                    stage = ?, final_decision = ?, avatar_action = ?, updated_at = ?
                WHERE {where}
                """,
                [
                    *parameters[:5],
                    "human_required" if action == "retry" else "human_decided",
                    None if action == "retry" else {"approve": "allow", "reject": "block", "blacklist": "block", "hold": None}[action],
                    avatar_action,
                    now,
                    *parameters[5:],
                ],
            )
            if updated.rowcount != 1:
                raise ReviewConflictError("review item changed during action")
            cursor.execute(
                """
                INSERT INTO review_events
                  (event_id, item_id, action, reviewer, note, before_status, after_status,
                   policy_version, request_id, ip_hash, created_at, actor_type, actor_id,
                   before_stage, after_stage, before_decision, after_decision, reason_code,
                   before_avatar_action, after_avatar_action)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reviewer', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    item_id,
                    action,
                    reviewer,
                    note or None,
                    before_status,
                    after_status,
                    row["policy_version"],
                    request_id or row["request_id"],
                    ip_hash,
                    now,
                    reviewer,
                    row["stage"],
                    "human_required" if action == "retry" else "human_decided",
                    row["final_decision"],
                    None if action == "retry" else {"approve": "allow", "reject": "block", "blacklist": "block", "hold": None}[action],
                    f"human_{action}",
                    row["avatar_action"],
                    avatar_action,
                ),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get(item_id, consumer_id=consumer_id)

    def _row(self, row: sqlite3.Row) -> ReviewItem:
        return ReviewItem(
            item_id=row["item_id"],
            consumer_id=row["consumer_id"],
            content_sha256=row["content_sha256"],
            media_type=row["media_type"],
            media_ref=row["media_ref"],
            decision_hint=row["decision_hint"],
            reasons=tuple(json.loads(row["reasons_json"])),
            findings=tuple(json.loads(row["findings_json"] or "[]")),
            model_versions=dict(json.loads(row["model_versions_json"] or "{}")),
            top_score=row["top_score"],
            request_id=row["request_id"],
            policy_version=row["policy_version"],
            status=row["status"],
            version=int(row["version"]),
            created_at=row["created_at"],
            reviewer=row["reviewer"],
            review_note=row["review_note"],
            reviewed_at=row["reviewed_at"],
            stage=row["stage"],
            final_decision=row["final_decision"],
            avatar_action=row["avatar_action"],
            due_at=row["due_at"],
            assignee=row["assignee"],
            claim_until=row["claim_until"],
            quality_sample=bool(row["quality_sample"]),
            arbitration_required=bool(row["arbitration_required"]),
            appealed=bool(row["appealed"]),
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _event_row(row: sqlite3.Row) -> ReviewEvent:
        return ReviewEvent(
            event_id=row["event_id"],
            item_id=row["item_id"],
            action=row["action"],
            reviewer=row["reviewer"],
            note=row["note"],
            before_status=row["before_status"],
            after_status=row["after_status"],
            policy_version=row["policy_version"],
            request_id=row["request_id"],
            ip_hash=row["ip_hash"],
            created_at=row["created_at"],
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            before_stage=row["before_stage"],
            after_stage=row["after_stage"],
            before_decision=row["before_decision"],
            after_decision=row["after_decision"],
            reason_code=row["reason_code"],
            before_avatar_action=row["before_avatar_action"],
            after_avatar_action=row["after_avatar_action"],
        )


def _route_avatar_action(row: sqlite3.Row, stage: str) -> AvatarAction | None:
    if stage == "auto_approved":
        return "keep"
    if stage != "auto_rejected":
        return row["avatar_action"]
    categories = {
        str(finding.get("category", "")).strip().lower()
        for finding in json.loads(row["findings_json"] or "[]")
        if isinstance(finding, dict)
    }
    reasons = {str(reason).strip().lower() for reason in json.loads(row["reasons_json"] or "[]")}
    return "blacklist" if (categories | reasons) & SEVERE_BLACKLIST_CATEGORIES else "replace_default"
