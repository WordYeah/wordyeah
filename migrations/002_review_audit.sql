-- Review queue isolation and optimistic audit fields for schema version 2.
-- The executable bootstrap also adds these columns for existing local DBs.
ALTER TABLE review_items ADD COLUMN consumer_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE review_items ADD COLUMN findings_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE review_items ADD COLUMN model_versions_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE review_items ADD COLUMN top_score REAL;
ALTER TABLE review_items ADD COLUMN request_id TEXT;
ALTER TABLE review_items ADD COLUMN policy_version TEXT NOT NULL DEFAULT 'policy-default';
ALTER TABLE review_items ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE review_events ADD COLUMN before_status TEXT;
ALTER TABLE review_events ADD COLUMN after_status TEXT;
ALTER TABLE review_events ADD COLUMN policy_version TEXT;
ALTER TABLE review_events ADD COLUMN request_id TEXT;
ALTER TABLE review_events ADD COLUMN ip_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_review_items_consumer_status
    ON review_items(consumer_id, status, created_at);
INSERT OR IGNORE INTO schema_migrations(version) VALUES (2);
