import unittest

from wy_core.contracts import Finding, ModerationResult
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
        self.assertEqual(decided.avatar_action, "keep")
        self.assertEqual(decided.reviewer, "tester")

    def test_source_id_remains_idempotent_after_final_decision(self) -> None:
        store = ReviewStore()
        first = store.enqueue(
            result("review"),
            "media://first.png",
            consumer_id="cravatar",
            source_id="cravatar-job:1",
        )
        store.decide(first.item_id, "approve", "tester", consumer_id="cravatar")
        repeated = store.enqueue(
            result("allow"),
            "media://second.png",
            consumer_id="cravatar",
            source_id="cravatar-job:1",
            force=True,
        )
        self.assertEqual(repeated.item_id, first.item_id)
        self.assertEqual(
            len(store.list_items(status=None, consumer_id="cravatar")), 1
        )

    def test_source_lookup_is_consumer_scoped(self) -> None:
        store = ReviewStore()
        created = store.enqueue(
            result("review"),
            "media://first.png",
            consumer_id="cravatar",
            source_id="upstream:1",
        )
        self.assertEqual(
            store.get_by_source_id("upstream:1", consumer_id="cravatar").item_id,
            created.item_id,
        )
        with self.assertRaises(KeyError):
            store.get_by_source_id("upstream:1", consumer_id="other")
        with self.assertRaises(ValueError):
            store.get_by_source_id("", consumer_id="cravatar")

    def test_reject_replaces_default_while_blacklist_uses_the_ban_state(self) -> None:
        store = ReviewStore()
        ordinary = store.enqueue(result("review", "e" * 64), "media://ordinary.png")
        malicious = store.enqueue(result("review", "f" * 64), "media://malicious.png")
        replaced = store.decide(ordinary.item_id, "reject", "tester")
        blacklisted = store.decide(malicious.item_id, "blacklist", "tester")
        self.assertEqual(replaced.avatar_action, "replace_default")
        self.assertEqual(blacklisted.avatar_action, "blacklist")
        event = store.list_events(malicious.item_id)[0]
        self.assertIsNone(event.before_avatar_action)
        self.assertEqual(event.after_avatar_action, "blacklist")

    def test_auto_reject_blacklists_only_explicit_severe_categories(self) -> None:
        store = ReviewStore()
        ordinary = store.enqueue(result("block", "7" * 64), "media://ordinary.png")
        severe = store.enqueue(
            ModerationResult(
                request_id="req-severe",
                content_sha256="8" * 64,
                media_type="image",
                decision="block",
                reasons=("policy_block",),
                findings=(Finding(category="terrorism", label="match", score=0.99),),
            ),
            "media://severe.png",
        )
        ordinary = store.apply_route(
            ordinary.item_id,
            stage="auto_rejected",
            final_decision="block",
            reason_code="high_confidence_block",
        )
        severe = store.apply_route(
            severe.item_id,
            stage="auto_rejected",
            final_decision="block",
            reason_code="high_confidence_block",
        )
        self.assertEqual(ordinary.avatar_action, "replace_default")
        self.assertEqual(severe.avatar_action, "blacklist")

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

    def test_cursor_page_is_stable_consumer_scoped_and_human_only(self) -> None:
        store = ReviewStore()
        created = [
            store.enqueue(result("review", f"{index:x}" * 64), f"media://{index}.png", consumer_id="one")
            for index in range(1, 4)
        ]
        store.enqueue(result("review", "f" * 64), "media://other.png", consumer_id="two")
        for item in created[:2]:
            store.apply_route(
                item.item_id,
                stage="human_required",
                final_decision=None,
                reason_code="fixture",
                consumer_id="one",
            )
        first, cursor = store.list_items_page(
            consumer_id="one", limit=1, human_only=True
        )
        second, final_cursor = store.list_items_page(
            consumer_id="one", limit=1, human_only=True, cursor=cursor
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertNotEqual(first[0].item_id, second[0].item_id)
        self.assertIsNotNone(cursor)
        self.assertIsNone(final_cursor)
        with self.assertRaises(ValueError):
            store.list_items_page(consumer_id="one", cursor="not-a-cursor")

    def test_quality_samples_stay_out_of_operational_human_queue_until_escalated(self) -> None:
        store = ReviewStore()
        sample = store.enqueue(
            result("review", "a" * 64),
            "media://quality.png",
            consumer_id="one",
        )
        store.connection.execute(
            "UPDATE review_items SET quality_sample = 1 WHERE item_id = ?",
            (sample.item_id,),
        )
        store.connection.commit()

        pending, _ = store.list_items_page(
            consumer_id="one", limit=10, human_only=True
        )
        self.assertEqual(pending, [])

        store.connection.execute(
            "UPDATE review_items SET arbitration_required = 1 WHERE item_id = ?",
            (sample.item_id,),
        )
        store.connection.commit()
        escalated, _ = store.list_items_page(
            consumer_id="one", limit=10, human_only=True
        )
        self.assertEqual([item.item_id for item in escalated], [sample.item_id])

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
        replacement = CravatarAdapter("enforce").translate(block)
        self.assertEqual(replacement.action, "replace_default")
        self.assertTrue(replacement.mutates_avatar)
        blacklist = CravatarAdapter("enforce").translate(block, "blacklist")
        self.assertEqual(blacklist.action, "blacklist")
        self.assertEqual(blacklist.avatar_action, "blacklist")

    def test_shadow_connector_is_disabled_by_default_and_records_only(self) -> None:
        block = result("block", "b" * 64)
        self.assertIsNone(CravatarShadowConnector().submit("avatar-1", block))
        record = CravatarShadowConnector(enabled=True).submit("avatar-1", block)
        self.assertIsNotNone(record)
        self.assertFalse(record.mutates_avatar)
        self.assertEqual(record.action, "record_only")


if __name__ == "__main__":
    unittest.main()
