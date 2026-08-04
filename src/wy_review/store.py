from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from wy_core.contracts import ModerationResult

ReviewStatus = Literal["pending", "approved", "rejected", "held"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    content_sha256: str
    media_type: str
    media_ref: str
    decision_hint: str
    reasons: tuple[str, ...]
    status: ReviewStatus
    created_at: str
    reviewer: str | None = None
    review_note: str | None = None
    reviewed_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "content_sha256": self.content_sha256,
            "media_type": self.media_type,
            "media_ref": self.media_ref,
            "decision_hint": self.decision_hint,
            "reasons": list(self.reasons),
            "status": self.status,
            "created_at": self.created_at,
            "reviewer": self.reviewer,
            "review_note": self.review_note,
            "reviewed_at": self.reviewed_at,
        }


class ReviewStore:
    """SQLite review queue that stores metadata only, never media bytes."""

    def __init__(self, database: str = ":memory:") -> None:
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_items (
                item_id TEXT PRIMARY KEY,
                content_sha256 TEXT NOT NULL,
                media_type TEXT NOT NULL,
                media_ref TEXT NOT NULL,
                decision_hint TEXT NOT NULL,
                reasons_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','held')),
                created_at TEXT NOT NULL,
                reviewer TEXT,
                review_note TEXT,
                reviewed_at TEXT
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_events (
                event_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                action TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(item_id) REFERENCES review_items(item_id)
            )
            """
        )
        self.connection.commit()

    def enqueue(self, result: ModerationResult, media_ref: str) -> ReviewItem:
        if result.decision not in {"review", "block", "error"}:
            raise ValueError("only review, block, or error results enter the review queue")
        existing = self.connection.execute(
            "SELECT * FROM review_items WHERE content_sha256 = ? AND status = 'pending' ORDER BY created_at LIMIT 1",
            (result.content_sha256,),
        ).fetchone()
        if existing is not None:
            return self._row(existing)

        item_id = uuid4().hex
        self.connection.execute(
            """
            INSERT INTO review_items
              (item_id, content_sha256, media_type, media_ref, decision_hint, reasons_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                item_id,
                result.content_sha256,
                result.media_type,
                media_ref,
                result.decision,
                json.dumps(list(result.reasons), ensure_ascii=False),
                _now(),
            ),
        )
        self.connection.commit()
        return self.get(item_id)

    def get(self, item_id: str) -> ReviewItem:
        row = self.connection.execute("SELECT * FROM review_items WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(f"review item not found: {item_id}")
        return self._row(row)

    def list_pending(self, limit: int = 100) -> list[ReviewItem]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        rows = self.connection.execute(
            "SELECT * FROM review_items WHERE status = 'pending' ORDER BY created_at LIMIT ?", (limit,)
        ).fetchall()
        return [self._row(row) for row in rows]

    def decide(self, item_id: str, action: Literal["approve", "reject", "hold"], reviewer: str, note: str = "") -> ReviewItem:
        status: ReviewStatus = {"approve": "approved", "reject": "rejected", "hold": "held"}[action]
        now = _now()
        updated = self.connection.execute(
            """
            UPDATE review_items
            SET status = ?, reviewer = ?, review_note = ?, reviewed_at = ?
            WHERE item_id = ? AND status = 'pending'
            """,
            (status, reviewer, note, now, item_id),
        )
        if updated.rowcount != 1:
            raise ValueError("review item is missing or no longer pending")
        self.connection.execute(
            "INSERT INTO review_events (event_id, item_id, action, reviewer, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uuid4().hex, item_id, action, reviewer, note, now),
        )
        self.connection.commit()
        return self.get(item_id)

    def _row(self, row: sqlite3.Row) -> ReviewItem:
        return ReviewItem(
            item_id=row["item_id"],
            content_sha256=row["content_sha256"],
            media_type=row["media_type"],
            media_ref=row["media_ref"],
            decision_hint=row["decision_hint"],
            reasons=tuple(json.loads(row["reasons_json"])),
            status=row["status"],
            created_at=row["created_at"],
            reviewer=row["reviewer"],
            review_note=row["review_note"],
            reviewed_at=row["reviewed_at"],
        )
