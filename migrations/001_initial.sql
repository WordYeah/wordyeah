-- WordYeah schema version 1. The executable bootstrap mirrors this schema in
-- src/wy_core/database.py so an installed package does not depend on cwd.
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
    content_sha256 TEXT NOT NULL,
    media_type TEXT NOT NULL,
    media_ref TEXT NOT NULL,
    decision_hint TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reviewer TEXT,
    review_note TEXT,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS review_events (
    event_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(item_id) REFERENCES review_items(item_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT,
    status TEXT NOT NULL,
    consumer_id TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    worker_id TEXT,
    lease_until TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_versions (
    policy_version TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);
