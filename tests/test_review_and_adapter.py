import unittest

from wy_core.contracts import ModerationResult
from wy_cravatar.adapter import CravatarAdapter
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

    def test_adapter_modes_never_mutate_in_shadow_or_review(self) -> None:
        block = result("block", "b" * 64)
        self.assertFalse(CravatarAdapter("shadow").translate(block).mutates_avatar)
        review_action = CravatarAdapter("review").translate(block)
        self.assertEqual(review_action.action, "queue_review")
        self.assertFalse(review_action.mutates_avatar)
        self.assertTrue(CravatarAdapter("enforce").translate(block).mutates_avatar)


if __name__ == "__main__":
    unittest.main()
