-- Durable advanced-vision queue fields for schema version 5.
ALTER TABLE jobs ADD COLUMN idempotency_key TEXT;
ALTER TABLE jobs ADD COLUMN available_at TEXT;
ALTER TABLE jobs ADD COLUMN error_kind TEXT;
ALTER TABLE jobs ADD COLUMN retryable INTEGER;
ALTER TABLE jobs ADD COLUMN dead_lettered_at TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency
    ON jobs(consumer_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_available
    ON jobs(status, available_at, created_at);
INSERT OR IGNORE INTO schema_migrations(version) VALUES (5);
