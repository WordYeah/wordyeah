-- Avatar disposition and route event audit fields for schema version 4.
ALTER TABLE review_items ADD COLUMN avatar_action TEXT;
ALTER TABLE review_events ADD COLUMN before_avatar_action TEXT;
ALTER TABLE review_events ADD COLUMN after_avatar_action TEXT;
UPDATE review_items SET avatar_action = 'keep'
WHERE avatar_action IS NULL AND status = 'approved';
UPDATE review_items SET avatar_action = 'replace_default'
WHERE avatar_action IS NULL AND status = 'rejected';
INSERT OR IGNORE INTO schema_migrations(version) VALUES (4);
