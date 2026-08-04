from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Mapping, Sequence
from uuid import uuid4

from wy_core.database import open_database


QualityLabel = Literal[
    "false_positive",
    "false_negative",
    "model_disagreement",
    "boundary",
    "rare_category",
    "model_failure",
    "quality_sample",
]
QualityDecisionValue = Literal["allow", "review", "block"]
SampleStatus = Literal["awaiting_reviews", "arbitration_required", "resolved"]

CONTROLLED_QUALITY_LABELS: tuple[QualityLabel, ...] = (
    "false_positive",
    "false_negative",
    "model_disagreement",
    "boundary",
    "rare_category",
    "model_failure",
    "quality_sample",
)
_CONTROLLED_LABEL_SET = frozenset(CONTROLLED_QUALITY_LABELS)
_DECISIONS = frozenset({"allow", "review", "block"})


class QualityConflictError(RuntimeError):
    """Raised when an append-only quality record conflicts with existing data."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required(value: str, field: str, maximum: int = 256) -> str:
    if not value or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be between 1 and {maximum} characters")
    return value


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class LabelVocabulary:
    consumer_id: str
    version: str
    labels: tuple[str, ...]
    actor_id: str
    created_at: str


@dataclass(frozen=True)
class ItemLabelEvent:
    event_id: str
    consumer_id: str
    item_id: str
    label: str
    vocabulary_version: str
    actor_id: str
    policy_version: str | None
    model_versions: dict[str, str]
    request_id: str | None
    note: str | None
    created_at: str


@dataclass(frozen=True)
class QualityDecision:
    decision_id: str
    sample_id: str
    consumer_id: str
    reviewer_id: str
    decision: QualityDecisionValue
    policy_version: str | None
    model_versions: dict[str, str]
    request_id: str | None
    note: str | None
    created_at: str


@dataclass(frozen=True)
class QualitySample:
    sample_id: str
    consumer_id: str
    item_id: str
    content_sha256: str
    media_ref: str
    reason: str
    vocabulary_version: str
    stratum: str | None
    retention_status: str
    status: SampleStatus
    arbitration_required: bool
    final_decision: QualityDecisionValue | None
    policy_version: str | None
    model_versions: dict[str, str]
    request_id: str | None
    created_at: str
    resolved_at: str | None


class QualityStore:
    """Consumer-scoped quality sampling and review state stored in SQLite.

    Only the original ``media_ref`` is retained. This store never reads or
    copies media bytes.
    """

    def __init__(self, database: str = ":memory:") -> None:
        self.connection = open_database(database)
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS quality_label_vocabularies (
                consumer_id TEXT NOT NULL,
                version TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (consumer_id, version)
            );

            CREATE TABLE IF NOT EXISTS quality_label_terms (
                consumer_id TEXT NOT NULL,
                vocabulary_version TEXT NOT NULL,
                label TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                PRIMARY KEY (consumer_id, vocabulary_version, label),
                FOREIGN KEY (consumer_id, vocabulary_version)
                    REFERENCES quality_label_vocabularies(consumer_id, version)
            );

            CREATE TABLE IF NOT EXISTS review_labels (
                event_id TEXT PRIMARY KEY,
                consumer_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                label TEXT NOT NULL,
                vocabulary_version TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                policy_version TEXT,
                model_versions_json TEXT NOT NULL DEFAULT '{}',
                request_id TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (consumer_id, vocabulary_version, label)
                    REFERENCES quality_label_terms(consumer_id, vocabulary_version, label)
            );

            CREATE INDEX IF NOT EXISTS idx_review_labels_consumer_item
                ON review_labels(consumer_id, item_id, created_at, event_id);

            CREATE TABLE IF NOT EXISTS quality_samples (
                sample_id TEXT PRIMARY KEY,
                consumer_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                media_ref TEXT NOT NULL,
                reason TEXT NOT NULL,
                vocabulary_version TEXT NOT NULL,
                stratum TEXT,
                retention_status TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN
                    ('awaiting_reviews','arbitration_required','resolved')),
                arbitration_required INTEGER NOT NULL DEFAULT 0
                    CHECK(arbitration_required IN (0, 1)),
                final_decision TEXT CHECK(final_decision IN ('allow','review','block')),
                policy_version TEXT,
                model_versions_json TEXT NOT NULL DEFAULT '{}',
                request_id TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                UNIQUE (consumer_id, item_id),
                FOREIGN KEY (consumer_id, vocabulary_version, reason)
                    REFERENCES quality_label_terms(consumer_id, vocabulary_version, label)
            );

            CREATE INDEX IF NOT EXISTS idx_quality_samples_consumer_status
                ON quality_samples(consumer_id, status, created_at, sample_id);

            CREATE TABLE IF NOT EXISTS quality_decisions (
                decision_id TEXT PRIMARY KEY,
                sample_id TEXT NOT NULL,
                consumer_id TEXT NOT NULL,
                reviewer_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('allow','review','block')),
                policy_version TEXT,
                model_versions_json TEXT NOT NULL DEFAULT '{}',
                request_id TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (sample_id, reviewer_id),
                FOREIGN KEY (sample_id) REFERENCES quality_samples(sample_id)
            );

            CREATE INDEX IF NOT EXISTS idx_quality_decisions_consumer_sample
                ON quality_decisions(consumer_id, sample_id, created_at, decision_id);

            CREATE TABLE IF NOT EXISTS quality_arbitrations (
                arbitration_id TEXT PRIMARY KEY,
                sample_id TEXT NOT NULL UNIQUE,
                consumer_id TEXT NOT NULL,
                arbitrator_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('allow','review','block')),
                before_status TEXT NOT NULL,
                after_status TEXT NOT NULL,
                policy_version TEXT,
                model_versions_json TEXT NOT NULL DEFAULT '{}',
                request_id TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sample_id) REFERENCES quality_samples(sample_id)
            );
            """
        )
        self.connection.commit()
        self._migrate_review_decision_schema()

    def close(self) -> None:
        self.connection.close()

    def create_vocabulary(
        self,
        *,
        consumer_id: str,
        version: str = "v1",
        actor_id: str = "system",
        labels: Sequence[str] = CONTROLLED_QUALITY_LABELS,
    ) -> LabelVocabulary:
        _required(consumer_id, "consumer_id", 128)
        _required(version, "version", 128)
        _required(actor_id, "actor_id", 128)
        normalized = tuple(dict.fromkeys(labels))
        if not normalized or any(label not in _CONTROLLED_LABEL_SET for label in normalized):
            raise ValueError("vocabulary contains an unknown quality label")
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            existing = cursor.execute(
                """
                SELECT label FROM quality_label_terms
                WHERE consumer_id = ? AND vocabulary_version = ? ORDER BY ordinal
                """,
                (consumer_id, version),
            ).fetchall()
            if existing:
                current = tuple(row["label"] for row in existing)
                if current != normalized:
                    raise QualityConflictError("vocabulary version is immutable")
                self.connection.commit()
                return self.get_vocabulary(consumer_id=consumer_id, version=version)
            created_at = _now()
            cursor.execute(
                """
                INSERT INTO quality_label_vocabularies
                  (consumer_id, version, actor_id, created_at) VALUES (?, ?, ?, ?)
                """,
                (consumer_id, version, actor_id, created_at),
            )
            cursor.executemany(
                """
                INSERT INTO quality_label_terms
                  (consumer_id, vocabulary_version, label, ordinal) VALUES (?, ?, ?, ?)
                """,
                ((consumer_id, version, label, ordinal) for ordinal, label in enumerate(normalized)),
            )
            self.connection.commit()
            return LabelVocabulary(consumer_id, version, normalized, actor_id, created_at)
        except Exception:
            self.connection.rollback()
            raise

    def get_vocabulary(self, *, consumer_id: str, version: str = "v1") -> LabelVocabulary:
        _required(consumer_id, "consumer_id", 128)
        row = self.connection.execute(
            """
            SELECT * FROM quality_label_vocabularies
            WHERE consumer_id = ? AND version = ?
            """,
            (consumer_id, version),
        ).fetchone()
        if row is None:
            raise KeyError(f"quality vocabulary not found: {version}")
        labels = self.connection.execute(
            """
            SELECT label FROM quality_label_terms
            WHERE consumer_id = ? AND vocabulary_version = ? ORDER BY ordinal
            """,
            (consumer_id, version),
        ).fetchall()
        return LabelVocabulary(
            consumer_id=row["consumer_id"],
            version=row["version"],
            labels=tuple(term["label"] for term in labels),
            actor_id=row["actor_id"],
            created_at=row["created_at"],
        )

    def append_item_label(
        self,
        *,
        consumer_id: str,
        item_id: str,
        label: str,
        actor_id: str,
        vocabulary_version: str = "v1",
        policy_version: str | None = None,
        model_versions: Mapping[str, str] | None = None,
        request_id: str | None = None,
        note: str | None = None,
    ) -> ItemLabelEvent:
        _required(consumer_id, "consumer_id", 128)
        _required(item_id, "item_id")
        _required(actor_id, "actor_id", 128)
        self._ensure_item_scope(consumer_id, item_id)
        self._require_label(consumer_id, vocabulary_version, label)
        event = ItemLabelEvent(
            event_id=uuid4().hex,
            consumer_id=consumer_id,
            item_id=item_id,
            label=label,
            vocabulary_version=vocabulary_version,
            actor_id=actor_id,
            policy_version=policy_version,
            model_versions=dict(model_versions or {}),
            request_id=request_id,
            note=note,
            created_at=_now(),
        )
        self.connection.execute(
            """
            INSERT INTO review_labels
              (event_id, consumer_id, item_id, label, vocabulary_version,
               actor_id, policy_version, model_versions_json, request_id, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id, event.consumer_id, event.item_id, event.label,
                event.vocabulary_version, event.actor_id, event.policy_version,
                _json(event.model_versions), event.request_id, event.note, event.created_at,
            ),
        )
        self.connection.commit()
        return event

    add_label = append_item_label

    def list_item_labels(self, *, consumer_id: str, item_id: str) -> list[ItemLabelEvent]:
        _required(consumer_id, "consumer_id", 128)
        _required(item_id, "item_id")
        rows = self.connection.execute(
            """
            SELECT * FROM review_labels
            WHERE consumer_id = ? AND item_id = ? ORDER BY created_at, event_id
            """,
            (consumer_id, item_id),
        ).fetchall()
        return [self._label_row(row) for row in rows]

    def create_sample(
        self,
        *,
        consumer_id: str,
        item_id: str,
        reason: str = "quality_sample",
        vocabulary_version: str = "v1",
        content_sha256: str | None = None,
        media_ref: str | None = None,
        stratum: str | None = None,
        retention_status: str = "active",
        policy_version: str | None = None,
        model_versions: Mapping[str, str] | None = None,
        request_id: str | None = None,
        actor_id: str = "system",
    ) -> QualitySample:
        _required(consumer_id, "consumer_id", 128)
        _required(item_id, "item_id")
        _required(actor_id, "actor_id", 128)
        _required(retention_status, "retention_status", 128)
        self._ensure_item_scope(consumer_id, item_id)
        self._require_label(consumer_id, vocabulary_version, reason)

        review_item = self.connection.execute(
            """
            SELECT content_sha256, media_ref, policy_version, model_versions_json, request_id
            FROM review_items WHERE consumer_id = ? AND item_id = ?
            """,
            (consumer_id, item_id),
        ).fetchone()
        if review_item is not None:
            content_sha256 = content_sha256 or review_item["content_sha256"]
            media_ref = media_ref or review_item["media_ref"]
            policy_version = policy_version or review_item["policy_version"]
            model_versions = model_versions or json.loads(review_item["model_versions_json"])
            request_id = request_id or review_item["request_id"]
        _required(content_sha256 or "", "content_sha256", 256)
        _required(media_ref or "", "media_ref", 2048)

        existing = self.connection.execute(
            """
            SELECT * FROM quality_samples WHERE consumer_id = ? AND item_id = ?
            """,
            (consumer_id, item_id),
        ).fetchone()
        if existing is not None:
            sample = self._sample_row(existing)
            if (
                sample.reason != reason
                or sample.vocabulary_version != vocabulary_version
                or sample.content_sha256 != content_sha256
                or sample.media_ref != media_ref
            ):
                raise QualityConflictError("quality sample already exists with different data")
            return sample

        sample = QualitySample(
            sample_id=uuid4().hex,
            consumer_id=consumer_id,
            item_id=item_id,
            content_sha256=content_sha256 or "",
            media_ref=media_ref or "",
            reason=reason,
            vocabulary_version=vocabulary_version,
            stratum=stratum,
            retention_status=retention_status,
            status="awaiting_reviews",
            arbitration_required=False,
            final_decision=None,
            policy_version=policy_version,
            model_versions=dict(model_versions or {}),
            request_id=request_id,
            created_at=_now(),
            resolved_at=None,
        )
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                INSERT INTO quality_samples
                  (sample_id, consumer_id, item_id, content_sha256, media_ref,
                   reason, vocabulary_version, stratum, retention_status, status,
                   arbitration_required, final_decision, policy_version,
                   model_versions_json, request_id, created_at, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample.sample_id, sample.consumer_id, sample.item_id,
                    sample.content_sha256, sample.media_ref, sample.reason,
                    sample.vocabulary_version, sample.stratum, sample.retention_status,
                    sample.status, 0, None, sample.policy_version,
                    _json(sample.model_versions), sample.request_id, sample.created_at, None,
                ),
            )
            cursor.execute(
                """
                INSERT INTO review_labels
                  (event_id, consumer_id, item_id, label, vocabulary_version,
                   actor_id, policy_version, model_versions_json, request_id, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex, consumer_id, item_id, reason, vocabulary_version,
                    actor_id, policy_version, _json(sample.model_versions), request_id,
                    "quality sample created", sample.created_at,
                ),
            )
            self.connection.commit()
            return sample
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise QualityConflictError(f"could not create quality sample: {exc}") from exc
        except Exception:
            self.connection.rollback()
            raise

    def get_sample(self, *, sample_id: str, consumer_id: str) -> QualitySample:
        _required(sample_id, "sample_id")
        _required(consumer_id, "consumer_id", 128)
        row = self.connection.execute(
            "SELECT * FROM quality_samples WHERE sample_id = ? AND consumer_id = ?",
            (sample_id, consumer_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"quality sample not found: {sample_id}")
        return self._sample_row(row)

    def list_samples(self, *, consumer_id: str, status: SampleStatus | None = None) -> list[QualitySample]:
        _required(consumer_id, "consumer_id", 128)
        if status is not None and status not in {
            "awaiting_reviews", "arbitration_required", "resolved"
        }:
            raise ValueError("unknown quality sample status")
        if status is None:
            rows = self.connection.execute(
                """
                SELECT * FROM quality_samples WHERE consumer_id = ?
                ORDER BY created_at, sample_id
                """,
                (consumer_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM quality_samples WHERE consumer_id = ? AND status = ?
                ORDER BY created_at, sample_id
                """,
                (consumer_id, status),
            ).fetchall()
        return [self._sample_row(row) for row in rows]

    def submit_decision(
        self,
        *,
        sample_id: str,
        consumer_id: str,
        reviewer_id: str,
        decision: QualityDecisionValue,
        policy_version: str | None = None,
        model_versions: Mapping[str, str] | None = None,
        request_id: str | None = None,
        note: str | None = None,
    ) -> QualitySample:
        _required(reviewer_id, "reviewer_id", 128)
        if decision not in _DECISIONS:
            raise ValueError("decision must be allow, review or block")
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            sample_row = cursor.execute(
                "SELECT * FROM quality_samples WHERE sample_id = ? AND consumer_id = ?",
                (sample_id, consumer_id),
            ).fetchone()
            if sample_row is None:
                raise KeyError(f"quality sample not found: {sample_id}")
            sample = self._sample_row(sample_row)
            existing_rows = cursor.execute(
                """
                SELECT * FROM quality_decisions
                WHERE sample_id = ? AND consumer_id = ? ORDER BY created_at, decision_id
                """,
                (sample_id, consumer_id),
            ).fetchall()
            own = next((row for row in existing_rows if row["reviewer_id"] == reviewer_id), None)
            if own is not None:
                if own["decision"] != decision:
                    raise QualityConflictError("reviewer decision is append-only")
                self.connection.commit()
                return sample
            if sample.status != "awaiting_reviews" or len(existing_rows) >= 2:
                raise QualityConflictError("quality sample no longer accepts reviewer decisions")

            cursor.execute(
                """
                INSERT INTO quality_decisions
                  (decision_id, sample_id, consumer_id, reviewer_id, decision,
                   policy_version, model_versions_json, request_id, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex, sample_id, consumer_id, reviewer_id, decision,
                    policy_version or sample.policy_version,
                    _json(dict(model_versions or sample.model_versions)),
                    request_id or sample.request_id, note, _now(),
                ),
            )
            if len(existing_rows) == 1:
                first_decision = existing_rows[0]["decision"]
                if first_decision == decision:
                    status, required, final, resolved_at = "resolved", 0, decision, _now()
                else:
                    status, required, final, resolved_at = "arbitration_required", 1, None, None
                cursor.execute(
                    """
                    UPDATE quality_samples
                    SET status = ?, arbitration_required = ?, final_decision = ?, resolved_at = ?
                    WHERE sample_id = ? AND consumer_id = ?
                    """,
                    (status, required, final, resolved_at, sample_id, consumer_id),
                )
            self.connection.commit()
            return self.get_sample(sample_id=sample_id, consumer_id=consumer_id)
        except Exception:
            self.connection.rollback()
            raise

    decide = submit_decision

    def list_decisions(self, *, sample_id: str, consumer_id: str) -> list[QualityDecision]:
        self.get_sample(sample_id=sample_id, consumer_id=consumer_id)
        rows = self.connection.execute(
            """
            SELECT * FROM quality_decisions
            WHERE sample_id = ? AND consumer_id = ? ORDER BY created_at, decision_id
            """,
            (sample_id, consumer_id),
        ).fetchall()
        return [self._decision_row(row) for row in rows]

    def arbitrate(
        self,
        *,
        sample_id: str,
        consumer_id: str,
        arbitrator_id: str,
        decision: QualityDecisionValue,
        policy_version: str | None = None,
        model_versions: Mapping[str, str] | None = None,
        request_id: str | None = None,
        note: str | None = None,
    ) -> QualitySample:
        _required(arbitrator_id, "arbitrator_id", 128)
        if decision not in _DECISIONS:
            raise ValueError("decision must be allow, review or block")
        cursor = self.connection.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            row = cursor.execute(
                "SELECT * FROM quality_samples WHERE sample_id = ? AND consumer_id = ?",
                (sample_id, consumer_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"quality sample not found: {sample_id}")
            sample = self._sample_row(row)
            if sample.status != "arbitration_required" or not sample.arbitration_required:
                raise QualityConflictError("sample does not require arbitration")
            reviewers = {
                item["reviewer_id"]
                for item in cursor.execute(
                    """
                    SELECT reviewer_id FROM quality_decisions
                    WHERE sample_id = ? AND consumer_id = ?
                    """,
                    (sample_id, consumer_id),
                ).fetchall()
            }
            if arbitrator_id in reviewers:
                raise QualityConflictError("arbitrator must be independent of both reviewers")
            now = _now()
            cursor.execute(
                """
                INSERT INTO quality_arbitrations
                  (arbitration_id, sample_id, consumer_id, arbitrator_id, decision,
                   before_status, after_status, policy_version, model_versions_json,
                   request_id, note, created_at)
                VALUES (?, ?, ?, ?, ?, 'arbitration_required', 'resolved', ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex, sample_id, consumer_id, arbitrator_id, decision,
                    policy_version or sample.policy_version,
                    _json(dict(model_versions or sample.model_versions)),
                    request_id or sample.request_id, note, now,
                ),
            )
            cursor.execute(
                """
                UPDATE quality_samples
                SET status = 'resolved', arbitration_required = 0,
                    final_decision = ?, resolved_at = ?
                WHERE sample_id = ? AND consumer_id = ?
                """,
                (decision, now, sample_id, consumer_id),
            )
            self.connection.commit()
            return self.get_sample(sample_id=sample_id, consumer_id=consumer_id)
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise QualityConflictError(f"could not arbitrate quality sample: {exc}") from exc
        except Exception:
            self.connection.rollback()
            raise

    def report(self, *, consumer_id: str) -> dict[str, object]:
        _required(consumer_id, "consumer_id", 128)
        rows = self.connection.execute(
            """
            SELECT status, final_decision, COUNT(*) AS count
            FROM quality_samples WHERE consumer_id = ?
            GROUP BY status, final_decision
            """,
            (consumer_id,),
        ).fetchall()
        total = sum(int(row["count"]) for row in rows)
        if total == 0:
            return {
                "status": "SKIP",
                "consumer_id": consumer_id,
                "sample_count": 0,
                "reason": "zero_samples",
            }
        status_counts = {name: 0 for name in ("awaiting_reviews", "arbitration_required", "resolved")}
        final_counts = {name: 0 for name in ("allow", "review", "block")}
        for row in rows:
            status_counts[row["status"]] += int(row["count"])
            if row["final_decision"] is not None:
                final_counts[row["final_decision"]] += int(row["count"])
        return {
            "status": "INCOMPLETE",
            "consumer_id": consumer_id,
            "sample_count": total,
            "reason": "requires_representative_corpus_evaluation",
            "samples_by_status": status_counts,
            "final_decisions": final_counts,
        }

    quality_report = report

    def _migrate_review_decision_schema(self) -> None:
        """Preserve quality data while widening decisions to allow/review/block."""

        definitions = {
            row["name"]: row["sql"] or ""
            for row in self.connection.execute(
                """
                SELECT name, sql FROM sqlite_master
                WHERE type = 'table' AND name IN
                  ('quality_samples', 'quality_decisions', 'quality_arbitrations')
                """
            ).fetchall()
        }
        marker = "('allow','review','block')"
        if definitions and all(marker in sql.replace(" ", "") for sql in definitions.values()):
            return
        if len(definitions) != 3:
            raise RuntimeError("quality decision schema is incomplete")

        self.connection.execute("PRAGMA foreign_keys = OFF")
        try:
            cursor = self.connection.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("DROP INDEX IF EXISTS idx_quality_samples_consumer_status")
            cursor.execute("DROP INDEX IF EXISTS idx_quality_decisions_consumer_sample")
            cursor.execute(
                "ALTER TABLE quality_arbitrations RENAME TO quality_arbitrations_legacy"
            )
            cursor.execute("ALTER TABLE quality_decisions RENAME TO quality_decisions_legacy")
            cursor.execute("ALTER TABLE quality_samples RENAME TO quality_samples_legacy")
            cursor.execute(
                """CREATE TABLE quality_samples (
                    sample_id TEXT PRIMARY KEY,
                    consumer_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    media_ref TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    vocabulary_version TEXT NOT NULL,
                    stratum TEXT,
                    retention_status TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('awaiting_reviews','arbitration_required','resolved')),
                    arbitration_required INTEGER NOT NULL DEFAULT 0
                        CHECK(arbitration_required IN (0, 1)),
                    final_decision TEXT CHECK(final_decision IN ('allow','review','block')),
                    policy_version TEXT,
                    model_versions_json TEXT NOT NULL DEFAULT '{}',
                    request_id TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    UNIQUE (consumer_id, item_id),
                    FOREIGN KEY (consumer_id, vocabulary_version, reason)
                        REFERENCES quality_label_terms(consumer_id, vocabulary_version, label)
                )"""
            )
            cursor.execute(
                """CREATE TABLE quality_decisions (
                    decision_id TEXT PRIMARY KEY,
                    sample_id TEXT NOT NULL,
                    consumer_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('allow','review','block')),
                    policy_version TEXT,
                    model_versions_json TEXT NOT NULL DEFAULT '{}',
                    request_id TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE (sample_id, reviewer_id),
                    FOREIGN KEY (sample_id) REFERENCES quality_samples(sample_id)
                )"""
            )
            cursor.execute(
                """CREATE TABLE quality_arbitrations (
                    arbitration_id TEXT PRIMARY KEY,
                    sample_id TEXT NOT NULL UNIQUE,
                    consumer_id TEXT NOT NULL,
                    arbitrator_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('allow','review','block')),
                    before_status TEXT NOT NULL,
                    after_status TEXT NOT NULL,
                    policy_version TEXT,
                    model_versions_json TEXT NOT NULL DEFAULT '{}',
                    request_id TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (sample_id) REFERENCES quality_samples(sample_id)
                )"""
            )

            sample_columns = (
                "sample_id, consumer_id, item_id, content_sha256, media_ref, reason, "
                "vocabulary_version, stratum, retention_status, status, "
                "arbitration_required, final_decision, policy_version, model_versions_json, "
                "request_id, created_at, resolved_at"
            )
            decision_columns = (
                "decision_id, sample_id, consumer_id, reviewer_id, decision, policy_version, "
                "model_versions_json, request_id, note, created_at"
            )
            arbitration_columns = (
                "arbitration_id, sample_id, consumer_id, arbitrator_id, decision, "
                "before_status, after_status, policy_version, model_versions_json, "
                "request_id, note, created_at"
            )
            cursor.execute(
                f"INSERT INTO quality_samples ({sample_columns}) "
                f"SELECT {sample_columns} FROM quality_samples_legacy"
            )
            cursor.execute(
                f"INSERT INTO quality_decisions ({decision_columns}) "
                f"SELECT {decision_columns} FROM quality_decisions_legacy"
            )
            cursor.execute(
                f"INSERT INTO quality_arbitrations ({arbitration_columns}) "
                f"SELECT {arbitration_columns} FROM quality_arbitrations_legacy"
            )
            violations = cursor.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError("quality decision migration failed foreign key check")

            cursor.execute("DROP TABLE quality_arbitrations_legacy")
            cursor.execute("DROP TABLE quality_decisions_legacy")
            cursor.execute("DROP TABLE quality_samples_legacy")
            cursor.execute(
                """CREATE INDEX idx_quality_samples_consumer_status
                ON quality_samples(consumer_id, status, created_at, sample_id)"""
            )
            cursor.execute(
                """CREATE INDEX idx_quality_decisions_consumer_sample
                ON quality_decisions(consumer_id, sample_id, created_at, decision_id)"""
            )
            self.connection.commit()
        except Exception:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise
        finally:
            self.connection.execute("PRAGMA foreign_keys = ON")

    def _ensure_item_scope(self, consumer_id: str, item_id: str) -> None:
        """Reject a cross-consumer reference when the review item exists."""

        row = self.connection.execute(
            "SELECT consumer_id FROM review_items WHERE item_id = ?", (item_id,)
        ).fetchone()
        if row is not None and row["consumer_id"] != consumer_id:
            raise KeyError(f"review item not found: {item_id}")

    def _require_label(self, consumer_id: str, version: str, label: str) -> None:
        if label not in _CONTROLLED_LABEL_SET:
            raise ValueError("unknown quality label")
        row = self.connection.execute(
            """
            SELECT 1 FROM quality_label_terms
            WHERE consumer_id = ? AND vocabulary_version = ? AND label = ?
            """,
            (consumer_id, version, label),
        ).fetchone()
        if row is None:
            raise KeyError(f"quality label not found in vocabulary {version}: {label}")

    @staticmethod
    def _label_row(row: sqlite3.Row) -> ItemLabelEvent:
        return ItemLabelEvent(
            event_id=row["event_id"], consumer_id=row["consumer_id"], item_id=row["item_id"],
            label=row["label"], vocabulary_version=row["vocabulary_version"],
            actor_id=row["actor_id"], policy_version=row["policy_version"],
            model_versions=json.loads(row["model_versions_json"]), request_id=row["request_id"],
            note=row["note"], created_at=row["created_at"],
        )

    @staticmethod
    def _sample_row(row: sqlite3.Row) -> QualitySample:
        return QualitySample(
            sample_id=row["sample_id"], consumer_id=row["consumer_id"], item_id=row["item_id"],
            content_sha256=row["content_sha256"], media_ref=row["media_ref"], reason=row["reason"],
            vocabulary_version=row["vocabulary_version"], stratum=row["stratum"],
            retention_status=row["retention_status"], status=row["status"],
            arbitration_required=bool(row["arbitration_required"]),
            final_decision=row["final_decision"], policy_version=row["policy_version"],
            model_versions=json.loads(row["model_versions_json"]), request_id=row["request_id"],
            created_at=row["created_at"], resolved_at=row["resolved_at"],
        )

    @staticmethod
    def _decision_row(row: sqlite3.Row) -> QualityDecision:
        return QualityDecision(
            decision_id=row["decision_id"], sample_id=row["sample_id"],
            consumer_id=row["consumer_id"], reviewer_id=row["reviewer_id"],
            decision=row["decision"], policy_version=row["policy_version"],
            model_versions=json.loads(row["model_versions_json"]), request_id=row["request_id"],
            note=row["note"], created_at=row["created_at"],
        )
