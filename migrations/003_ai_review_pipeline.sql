-- AI-first review stages and append-only model/reviewer attempts for schema v3.
ALTER TABLE review_items ADD COLUMN stage TEXT NOT NULL DEFAULT 'human_required';
ALTER TABLE review_items ADD COLUMN final_decision TEXT;
ALTER TABLE review_items ADD COLUMN due_at TEXT;
ALTER TABLE review_items ADD COLUMN assignee TEXT;
ALTER TABLE review_items ADD COLUMN claim_until TEXT;
ALTER TABLE review_items ADD COLUMN quality_sample INTEGER NOT NULL DEFAULT 0;
ALTER TABLE review_items ADD COLUMN arbitration_required INTEGER NOT NULL DEFAULT 0;
ALTER TABLE review_items ADD COLUMN appealed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE review_items ADD COLUMN updated_at TEXT;
ALTER TABLE review_events ADD COLUMN actor_type TEXT NOT NULL DEFAULT 'reviewer';
ALTER TABLE review_events ADD COLUMN actor_id TEXT;
ALTER TABLE review_events ADD COLUMN before_stage TEXT;
ALTER TABLE review_events ADD COLUMN after_stage TEXT;
ALTER TABLE review_events ADD COLUMN before_decision TEXT;
ALTER TABLE review_events ADD COLUMN after_decision TEXT;
ALTER TABLE review_events ADD COLUMN reason_code TEXT;

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

CREATE INDEX IF NOT EXISTS idx_review_items_consumer_stage
    ON review_items(consumer_id, stage, created_at);
CREATE INDEX IF NOT EXISTS idx_review_attempts_item_stage
    ON review_attempts(item_id, stage, attempt_number);
INSERT OR IGNORE INTO schema_migrations(version) VALUES (3);
