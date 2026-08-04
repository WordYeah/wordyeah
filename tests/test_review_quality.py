from __future__ import annotations

import unittest

from wy_review.quality import (
    CONTROLLED_QUALITY_LABELS,
    QualityConflictError,
    QualityStore,
)


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


if __name__ == "__main__":
    unittest.main()
