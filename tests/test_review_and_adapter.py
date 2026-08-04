import unittest

from wy_core.contracts import ModerationResult
from wy_cravatar.adapter import CravatarAdapter
from wy_cravatar.shadow import CravatarShadowConnector
from wy_review.store import ReviewStore


def result(decision: str, content_hash: str = "a" * 64) -> ModerationResult:
    return ModerationResult(
        request_id="req",
        content_sha256=content_hash,
        media_type="image",
        decision=decision,
        reasons=("test_reason",),
        error="test error" if decision == "error" else None,
    )


class ReviewAndAdapterTest(unittest.TestCase):
    def test_queue_is_metadata_only_and_deduplicates_pending_content(self) -> None:
        store = ReviewStore()
        first = store.enqueue(result("review"), "avatar-ref:1")
        second = store.enqueue(result("review"), "avatar-ref:2")
        self.assertEqual(first.item_id, second.item_id)
        self.assertEqual(len(store.list_pending()), 1)
        decided = store.decide(first.item_id, "approve", "tester", "safe")
        self.assertEqual(decided.status, "approved")
        self.assertEqual(decided.reviewer, "tester")

    def test_review_items_are_isolated_by_consumer_and_events_are_optimistic(self) -> None:
        store = ReviewStore()
        first = store.enqueue(result("review", "c" * 64), "media://one.png", consumer_id="one")
        second = store.enqueue(result("review", "c" * 64), "media://two.png", consumer_id="two")
        self.assertNotEqual(first.item_id, second.item_id)
        self.assertEqual(len(store.list_pending(consumer_id="one")), 1)
        self.assertEqual(len(store.list_pending(consumer_id="two")), 1)
        decided = store.decide(
            first.item_id,
            "approve",
            "tester",
            consumer_id="one",
            expected_version=first.version,
            request_id="req-review",
            ip_hash="ip-hash",
        )
        self.assertEqual(decided.version, 2)
        event = store.list_events(first.item_id, consumer_id="one")[0]
        self.assertEqual(event.before_status, "pending")
        self.assertEqual(event.after_status, "approved")
        self.assertEqual(event.request_id, "req-review")
        with self.assertRaises(KeyError):
            store.get(first.item_id, consumer_id="two")

    def test_list_items_returns_newest_records_first(self) -> None:
        store = ReviewStore()
        older = store.enqueue(result("review", "1" * 64), "media://older.png", consumer_id="one")
        newer = store.enqueue(result("review", "2" * 64), "media://newer.png", consumer_id="one")
        items = store.list_items(status="pending", consumer_id="one")
        self.assertEqual([item.item_id for item in items], [newer.item_id, older.item_id])

    def test_error_results_enter_held_not_pending(self) -> None:
        store = ReviewStore()
        item = store.enqueue(result("error", "d" * 64), "sha256://d", consumer_id="one")
        self.assertEqual(item.status, "held")
        self.assertEqual(store.list_pending(consumer_id="one"), [])
        self.assertEqual(store.list_items(status="held", consumer_id="one")[0].item_id, item.item_id)

    def test_adapter_modes_never_mutate_in_shadow_or_review(self) -> None:
        block = result("block", "b" * 64)
        self.assertFalse(CravatarAdapter("shadow").translate(block).mutates_avatar)
        review_action = CravatarAdapter("review").translate(block)
        self.assertEqual(review_action.action, "queue_review")
        self.assertFalse(review_action.mutates_avatar)
        self.assertTrue(CravatarAdapter("enforce").translate(block).mutates_avatar)

    def test_shadow_connector_is_disabled_by_default_and_records_only(self) -> None:
        block = result("block", "b" * 64)
        self.assertIsNone(CravatarShadowConnector().submit("avatar-1", block))
        record = CravatarShadowConnector(enabled=True).submit("avatar-1", block)
        self.assertIsNotNone(record)
        self.assertFalse(record.mutates_avatar)
        self.assertEqual(record.action, "record_only")


if __name__ == "__main__":
    unittest.main()
