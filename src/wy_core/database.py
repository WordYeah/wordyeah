from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 3


def open_database(database: str) -> sqlite3.Connection:
    """Open the local WordYeah database with durable, low-content metadata tables."""

    if database != ":memory:":
        database_path = Path(database).expanduser()
        database_path.parent.mkdir(parents=True, exist_ok=True)
        database = str(database_path)
    connection = sqlite3.connect(database, timeout=5.0, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if database != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS submissions (
            submission_id TEXT PRIMARY KEY,
            consumer_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            media_type TEXT NOT NULL,
            media_ref TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS model_runs (
            run_id TEXT PRIMARY KEY,
            submission_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            decision TEXT NOT NULL,
            result_json TEXT NOT NULL,
            elapsed_ms REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(submission_id) REFERENCES submissions(submission_id)
        );

        CREATE TABLE IF NOT EXISTS findings (
            finding_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            category TEXT NOT NULL,
            label TEXT NOT NULL,
            score REAL,
            source TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES model_runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS review_items (
            item_id TEXT PRIMARY KEY,
            consumer_id TEXT NOT NULL DEFAULT 'default',
            content_sha256 TEXT NOT NULL,
            media_type TEXT NOT NULL,
            media_ref TEXT NOT NULL,
            decision_hint TEXT NOT NULL,
            reasons_json TEXT NOT NULL,
            findings_json TEXT NOT NULL DEFAULT '[]',
            model_versions_json TEXT NOT NULL DEFAULT '{}',
            top_score REAL,
            request_id TEXT,
            policy_version TEXT NOT NULL DEFAULT 'policy-default',
            status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','held')),
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            reviewer TEXT,
            review_note TEXT,
            reviewed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_review_items_pending
            ON review_items(status, created_at);

        CREATE TABLE IF NOT EXISTS review_events (
            event_id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            note TEXT,
            before_status TEXT,
            after_status TEXT,
            policy_version TEXT,
            request_id TEXT,
            ip_hash TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(item_id) REFERENCES review_items(item_id)
        );

        CREATE TABLE IF NOT EXISTS review_attempts (
            attempt_id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            stage TEXT NOT NULL CHECK(stage IN ('fast_scan','vision_review_1','vision_review_2','human_review')),
            attempt_number INTEGER NOT NULL,
            actor_type TEXT NOT NULL CHECK(actor_type IN ('system','agent','reviewer')),
            provider TEXT,
            model_id TEXT,
            model_version TEXT,
            prompt_version TEXT,
            decision TEXT CHECK(decision IN ('allow','block','review','error')),
            confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            reasons_json TEXT NOT NULL DEFAULT '[]',
            findings_json TEXT NOT NULL DEFAULT '[]',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
            parent_attempt_id TEXT,
            started_at TEXT,
            completed_at TEXT,
            elapsed_ms REAL,
            error TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(item_id) REFERENCES review_items(item_id),
            FOREIGN KEY(parent_attempt_id) REFERENCES review_attempts(attempt_id),
            UNIQUE(item_id, stage, attempt_number)
        );

        CREATE INDEX IF NOT EXISTS idx_review_attempts_item_stage
            ON review_attempts(item_id, stage, attempt_number);

        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            result_json TEXT,
            status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
            consumer_id TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            worker_id TEXT,
            lease_until TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_claim
            ON jobs(status, created_at);

        CREATE TABLE IF NOT EXISTS policy_versions (
            policy_version TEXT PRIMARY KEY,
            profile TEXT NOT NULL,
            policy_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        INSERT OR IGNORE INTO schema_migrations(version) VALUES (1), (2), (3);
        """
    )
    _ensure_columns(
        connection,
        "review_items",
        {
            "consumer_id": "TEXT NOT NULL DEFAULT 'default'",
            "findings_json": "TEXT NOT NULL DEFAULT '[]'",
            "model_versions_json": "TEXT NOT NULL DEFAULT '{}'",
            "top_score": "REAL",
            "request_id": "TEXT",
            "policy_version": "TEXT NOT NULL DEFAULT 'policy-default'",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "stage": "TEXT NOT NULL DEFAULT 'human_required'",
            "final_decision": "TEXT",
            "due_at": "TEXT",
            "assignee": "TEXT",
            "claim_until": "TEXT",
            "quality_sample": "INTEGER NOT NULL DEFAULT 0",
            "arbitration_required": "INTEGER NOT NULL DEFAULT 0",
            "appealed": "INTEGER NOT NULL DEFAULT 0",
            "updated_at": "TEXT",
        },
    )
    _ensure_columns(
        connection,
        "review_events",
        {
            "before_status": "TEXT",
            "after_status": "TEXT",
            "policy_version": "TEXT",
            "request_id": "TEXT",
            "ip_hash": "TEXT",
            "actor_type": "TEXT NOT NULL DEFAULT 'reviewer'",
            "actor_id": "TEXT",
            "before_stage": "TEXT",
            "after_stage": "TEXT",
            "before_decision": "TEXT",
            "after_decision": "TEXT",
            "reason_code": "TEXT",
        },
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_items_consumer_status "
        "ON review_items(consumer_id, status, created_at)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_items_consumer_stage "
        "ON review_items(consumer_id, stage, created_at)"
    )
    connection.commit()
    return connection


def _ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
