from __future__ import annotations

import unittest
import sqlite3
import tempfile
from pathlib import Path

from wy_review.quality import (
    CONTROLLED_QUALITY_LABELS,
    QualityConflictError,
    QualityStore,
)


def _downgrade_quality_checks(database: Path) -> None:
    connection = sqlite3.connect(database)
    definitions = {
        row[0]: row[1]
        for row in connection.execute(
            """SELECT name, sql FROM sqlite_master
            WHERE type = 'table' AND name IN
              ('quality_samples', 'quality_decisions', 'quality_arbitrations')"""
        )
    }
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("DROP INDEX idx_quality_samples_consumer_status")
    connection.execute("DROP INDEX idx_quality_decisions_consumer_sample")
    for table in ("quality_arbitrations", "quality_decisions", "quality_samples"):
        connection.execute(f"ALTER TABLE {table} RENAME TO {table}_current")
    for table in ("quality_samples", "quality_decisions", "quality_arbitrations"):
        old_definition = definitions[table].replace(
            "('allow','review','block')", "('allow','block')"
        )
        connection.execute(old_definition)
        connection.execute(f"INSERT INTO {table} SELECT * FROM {table}_current")
    for table in ("quality_arbitrations", "quality_decisions", "quality_samples"):
        connection.execute(f"DROP TABLE {table}_current")
    connection.execute(
        """CREATE INDEX idx_quality_samples_consumer_status
        ON quality_samples(consumer_id, status, created_at, sample_id)"""
    )
    connection.execute(
        """CREATE INDEX idx_quality_decisions_consumer_sample
        ON quality_decisions(consumer_id, sample_id, created_at, decision_id)"""
    )
    connection.commit()
    connection.close()


class QualityStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = QualityStore()
        self.store.create_vocabulary(consumer_id="consumer-a", version="2026-08")
        self.store.create_vocabulary(consumer_id="consumer-b", version="2026-08")

    def tearDown(self) -> None:
        self.store.close()

    def create_sample(self, consumer_id: str = "consumer-a", item_id: str = "item-1"):
        return self.store.create_sample(
            consumer_id=consumer_id,
            item_id=item_id,
            content_sha256=("a" if consumer_id == "consumer-a" else "b") * 64,
            media_ref=f"media://original/{item_id}.png",
            reason="quality_sample",
            vocabulary_version="2026-08",
            policy_version="policy-4",
            model_versions={"vision": "model-2"},
            request_id=f"request-{item_id}",
            actor_id="sampler",
        )

    def test_vocabulary_is_versioned_controlled_and_immutable(self) -> None:
        vocabulary = self.store.get_vocabulary(
            consumer_id="consumer-a", version="2026-08"
        )
        self.assertEqual(vocabulary.labels, CONTROLLED_QUALITY_LABELS)
        with self.assertRaises(ValueError):
            self.store.create_vocabulary(
                consumer_id="consumer-a", version="bad", labels=("free_text",)
            )
        with self.assertRaises(QualityConflictError):
            self.store.create_vocabulary(
                consumer_id="consumer-a",
                version="2026-08",
                labels=("false_positive",),
            )

    def test_item_labels_are_append_only_audit_events(self) -> None:
        first = self.store.append_item_label(
            consumer_id="consumer-a",
            item_id="item-1",
            label="boundary",
            vocabulary_version="2026-08",
            actor_id="reviewer-1",
            policy_version="policy-4",
            model_versions={"vision": "model-2"},
            request_id="request-1",
        )
        second = self.store.append_item_label(
            consumer_id="consumer-a",
            item_id="item-1",
            label="model_disagreement",
            vocabulary_version="2026-08",
            actor_id="reviewer-2",
        )
        events = self.store.list_item_labels(consumer_id="consumer-a", item_id="item-1")
        self.assertEqual([event.event_id for event in events], [first.event_id, second.event_id])
        self.assertEqual(events[0].policy_version, "policy-4")
        self.assertEqual(events[0].model_versions, {"vision": "model-2"})
        self.assertEqual(events[0].request_id, "request-1")
        self.assertEqual(
            self.store.list_item_labels(consumer_id="consumer-b", item_id="item-1"), []
        )

    def test_sample_keeps_original_media_reference_without_media_copy(self) -> None:
        sample = self.create_sample()
        self.assertEqual(sample.media_ref, "media://original/item-1.png")
        columns = {
            row["name"]
            for row in self.store.connection.execute("PRAGMA table_info(quality_samples)")
        }
        self.assertNotIn("media_bytes", columns)
        labels = self.store.list_item_labels(consumer_id="consumer-a", item_id="item-1")
        self.assertEqual(labels[-1].label, "quality_sample")

    def test_matching_independent_reviews_resolve_without_arbitration(self) -> None:
        sample = self.create_sample()
        first = self.store.submit_decision(
            sample_id=sample.sample_id,
            consumer_id="consumer-a",
            reviewer_id="reviewer-1",
            decision="allow",
        )
        self.assertEqual(first.status, "awaiting_reviews")
        resolved = self.store.submit_decision(
            sample_id=sample.sample_id,
            consumer_id="consumer-a",
            reviewer_id="reviewer-2",
            decision="allow",
        )
        self.assertEqual(resolved.status, "resolved")
        self.assertFalse(resolved.arbitration_required)
        self.assertEqual(resolved.final_decision, "allow")
        self.assertEqual(len(self.store.list_decisions(
            sample_id=sample.sample_id, consumer_id="consumer-a"
        )), 2)

    def test_matching_review_decisions_preserve_boundary_ground_truth(self) -> None:
        sample = self.create_sample(item_id="boundary-item")
        self.store.submit_decision(
            sample_id=sample.sample_id,
            consumer_id="consumer-a",
            reviewer_id="reviewer-1",
            decision="review",
        )
        resolved = self.store.submit_decision(
            sample_id=sample.sample_id,
            consumer_id="consumer-a",
            reviewer_id="reviewer-2",
            decision="review",
        )
        self.assertEqual(resolved.status, "resolved")
        self.assertEqual(resolved.final_decision, "review")
        self.assertEqual(
            self.store.report(consumer_id="consumer-a")["final_decisions"]["review"],
            1,
        )

    def test_old_two_state_database_migrates_without_losing_quality_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.sqlite3"
            old = QualityStore(str(database))
            old.create_vocabulary(consumer_id="consumer-a", version="2026-08")
            sample = old.create_sample(
                consumer_id="consumer-a",
                item_id="legacy-item",
                content_sha256="c" * 64,
                media_ref="media://original/legacy-item.png",
                reason="quality_sample",
                vocabulary_version="2026-08",
            )
            old.submit_decision(
                sample_id=sample.sample_id,
                consumer_id="consumer-a",
                reviewer_id="legacy-reviewer-1",
                decision="allow",
            )
            old.submit_decision(
                sample_id=sample.sample_id,
                consumer_id="consumer-a",
                reviewer_id="legacy-reviewer-2",
                decision="allow",
            )
            old.close()

            connection = sqlite3.connect(database)
            connection.executescript(
                """
                PRAGMA foreign_keys = OFF;
                DROP INDEX idx_quality_samples_consumer_status;
                DROP INDEX idx_quality_decisions_consumer_sample;
                ALTER TABLE quality_arbitrations RENAME TO quality_arbitrations_current;
                ALTER TABLE quality_decisions RENAME TO quality_decisions_current;
                ALTER TABLE quality_samples RENAME TO quality_samples_current;
                CREATE TABLE quality_samples (
                    sample_id TEXT PRIMARY KEY, consumer_id TEXT NOT NULL,
                    item_id TEXT NOT NULL, content_sha256 TEXT NOT NULL,
                    media_ref TEXT NOT NULL, reason TEXT NOT NULL,
                    vocabulary_version TEXT NOT NULL, stratum TEXT,
                    retention_status TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('awaiting_reviews','arbitration_required','resolved')),
                    arbitration_required INTEGER NOT NULL DEFAULT 0
                        CHECK(arbitration_required IN (0, 1)),
                    final_decision TEXT CHECK(final_decision IN ('allow','block')),
                    policy_version TEXT, model_versions_json TEXT NOT NULL DEFAULT '{}',
                    request_id TEXT, created_at TEXT NOT NULL, resolved_at TEXT,
                    UNIQUE (consumer_id, item_id),
                    FOREIGN KEY (consumer_id, vocabulary_version, reason)
                        REFERENCES quality_label_terms(consumer_id, vocabulary_version, label)
                );
                CREATE TABLE quality_decisions (
                    decision_id TEXT PRIMARY KEY, sample_id TEXT NOT NULL,
                    consumer_id TEXT NOT NULL, reviewer_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('allow','block')),
                    policy_version TEXT, model_versions_json TEXT NOT NULL DEFAULT '{}',
                    request_id TEXT, note TEXT, created_at TEXT NOT NULL,
                    UNIQUE (sample_id, reviewer_id),
                    FOREIGN KEY (sample_id) REFERENCES quality_samples(sample_id)
                );
                CREATE TABLE quality_arbitrations (
                    arbitration_id TEXT PRIMARY KEY, sample_id TEXT NOT NULL UNIQUE,
                    consumer_id TEXT NOT NULL, arbitrator_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('allow','block')),
                    before_status TEXT NOT NULL, after_status TEXT NOT NULL,
                    policy_version TEXT, model_versions_json TEXT NOT NULL DEFAULT '{}',
                    request_id TEXT, note TEXT, created_at TEXT NOT NULL,
                    FOREIGN KEY (sample_id) REFERENCES quality_samples(sample_id)
                );
                INSERT INTO quality_samples SELECT * FROM quality_samples_current;
                INSERT INTO quality_decisions SELECT * FROM quality_decisions_current;
                INSERT INTO quality_arbitrations SELECT * FROM quality_arbitrations_current;
                DROP TABLE quality_arbitrations_current;
                DROP TABLE quality_decisions_current;
                DROP TABLE quality_samples_current;
                CREATE INDEX idx_quality_samples_consumer_status
                    ON quality_samples(consumer_id, status, created_at, sample_id);
                CREATE INDEX idx_quality_decisions_consumer_sample
                    ON quality_decisions(consumer_id, sample_id, created_at, decision_id);
                PRAGMA foreign_keys = ON;
                """
            )
            connection.close()

            migrated = QualityStore(str(database))
            try:
                preserved = migrated.get_sample(
                    sample_id=sample.sample_id, consumer_id="consumer-a"
                )
                self.assertEqual(preserved.final_decision, "allow")
                self.assertEqual(
                    len(migrated.list_decisions(
                        sample_id=sample.sample_id, consumer_id="consumer-a"
                    )),
                    2,
                )
                boundary = migrated.create_sample(
                    consumer_id="consumer-a",
                    item_id="post-migration-boundary",
                    content_sha256="d" * 64,
                    media_ref="media://original/post-migration-boundary.png",
                    reason="quality_sample",
                    vocabulary_version="2026-08",
                )
                for reviewer in ("reviewer-1", "reviewer-2"):
                    resolved = migrated.submit_decision(
                        sample_id=boundary.sample_id,
                        consumer_id="consumer-a",
                        reviewer_id=reviewer,
                        decision="review",
                    )
                self.assertEqual(resolved.final_decision, "review")
                self.assertEqual(
                    migrated.connection.execute("PRAGMA foreign_key_check").fetchall(), []
                )
                self.assertEqual(
                    migrated.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1
                )
            finally:
                migrated.close()

    def test_failed_old_schema_migration_rolls_back_without_deleting_source_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "invalid-quality.sqlite3"
            old = QualityStore(str(database))
            old.create_vocabulary(consumer_id="consumer-a", version="2026-08")
            sample = old.create_sample(
                consumer_id="consumer-a",
                item_id="legacy-valid-item",
                content_sha256="e" * 64,
                media_ref="media://original/legacy-valid-item.png",
                reason="quality_sample",
                vocabulary_version="2026-08",
            )
            old.close()
            _downgrade_quality_checks(database)

            raw = sqlite3.connect(database)
            raw.execute(
                """INSERT INTO quality_decisions
                (decision_id, sample_id, consumer_id, reviewer_id, decision,
                 model_versions_json, created_at)
                VALUES ('orphan', 'missing-sample', 'consumer-a', 'reviewer',
                        'allow', '{}', '2026-08-05T00:00:00Z')"""
            )
            raw.commit()
            raw.close()

            with self.assertRaisesRegex(RuntimeError, "foreign key check"):
                QualityStore(str(database))

            inspected = sqlite3.connect(database)
            try:
                definitions = dict(
                    inspected.execute(
                        """SELECT name, sql FROM sqlite_master
                        WHERE type = 'table' AND name LIKE 'quality_%'"""
                    ).fetchall()
                )
                self.assertIn("('allow','block')", definitions["quality_decisions"])
                self.assertNotIn("quality_decisions_legacy", definitions)
                self.assertEqual(
                    inspected.execute(
                        "SELECT item_id FROM quality_samples WHERE sample_id = ?",
                        (sample.sample_id,),
                    ).fetchone()[0],
                    "legacy-valid-item",
                )
                self.assertEqual(
                    inspected.execute(
                        "SELECT sample_id FROM quality_decisions WHERE decision_id = 'orphan'"
                    ).fetchone()[0],
                    "missing-sample",
                )
            finally:
                inspected.close()

    def test_disagreement_requires_arbitration_and_arbitration_converges(self) -> None:
        sample = self.create_sample()
        self.store.decide(
            sample_id=sample.sample_id,
            consumer_id="consumer-a",
            reviewer_id="reviewer-1",
            decision="allow",
        )
        divided = self.store.decide(
            sample_id=sample.sample_id,
            consumer_id="consumer-a",
            reviewer_id="reviewer-2",
            decision="block",
        )
        self.assertEqual(divided.status, "arbitration_required")
        self.assertTrue(divided.arbitration_required)
        self.assertIsNone(divided.final_decision)
        with self.assertRaises(QualityConflictError):
            self.store.arbitrate(
                sample_id=sample.sample_id,
                consumer_id="consumer-a",
                arbitrator_id="reviewer-1",
                decision="block",
            )
        resolved = self.store.arbitrate(
            sample_id=sample.sample_id,
            consumer_id="consumer-a",
            arbitrator_id="arbitrator",
            decision="block",
            request_id="arbitration-request",
        )
        self.assertEqual(resolved.status, "resolved")
        self.assertFalse(resolved.arbitration_required)
        self.assertEqual(resolved.final_decision, "block")

    def test_all_sample_operations_are_consumer_isolated(self) -> None:
        sample_a = self.create_sample("consumer-a", "shared-item")
        sample_b = self.create_sample("consumer-b", "shared-item")
        self.assertNotEqual(sample_a.sample_id, sample_b.sample_id)
        with self.assertRaises(KeyError):
            self.store.get_sample(sample_id=sample_a.sample_id, consumer_id="consumer-b")
        with self.assertRaises(KeyError):
            self.store.submit_decision(
                sample_id=sample_a.sample_id,
                consumer_id="consumer-b",
                reviewer_id="reviewer-b",
                decision="allow",
            )
        self.assertEqual(self.store.list_samples(consumer_id="consumer-a"), [sample_a])
        self.assertEqual(self.store.list_samples(consumer_id="consumer-b"), [sample_b])

    def test_same_reviewer_cannot_supply_two_independent_decisions(self) -> None:
        sample = self.create_sample()
        self.store.submit_decision(
            sample_id=sample.sample_id,
            consumer_id="consumer-a",
            reviewer_id="reviewer-1",
            decision="allow",
        )
        with self.assertRaises(QualityConflictError):
            self.store.submit_decision(
                sample_id=sample.sample_id,
                consumer_id="consumer-a",
                reviewer_id="reviewer-1",
                decision="block",
            )

    def test_zero_sample_report_is_skip_and_consumer_scoped(self) -> None:
        self.assertEqual(
            self.store.report(consumer_id="consumer-a"),
            {
                "status": "SKIP",
                "consumer_id": "consumer-a",
                "sample_count": 0,
                "reason": "zero_samples",
            },
        )
        self.create_sample("consumer-a")
        self.assertEqual(self.store.report(consumer_id="consumer-a")["status"], "INCOMPLETE")
        self.assertEqual(self.store.report(consumer_id="consumer-b")["status"], "SKIP")

    def test_sample_listing_has_bounded_pagination(self) -> None:
        for index in range(5):
            self.create_sample(item_id=f"page-{index}")
        page = self.store.list_samples(
            consumer_id="consumer-a", limit=2, offset=2
        )
        self.assertEqual([sample.item_id for sample in page], ["page-2", "page-3"])
        with self.assertRaises(ValueError):
            self.store.list_samples(consumer_id="consumer-a", limit=201)


if __name__ == "__main__":
    unittest.main()
