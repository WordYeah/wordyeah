from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wy_core.database import open_database
from wy_review.attempt_store import AttemptConflictError, ReviewAttempt, ReviewAttemptStore
from wy_review.router import ReviewRouter, RouterConfig


def _insert_item(database: str, item_id: str = "item-1") -> None:
    connection = open_database(database)
    connection.execute(
        """
        INSERT INTO review_items
          (item_id, content_sha256, media_type, media_ref, decision_hint,
           reasons_json, status, created_at)
        VALUES (?, ?, 'image', 'controlled://preview', 'review', '[]', 'pending', ?)
        """,
        (item_id, "a" * 64, "2026-08-04T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()


def _attempt(
    stage: str,
    decision: str | None,
    confidence: float | None,
    *,
    number: int = 1,
    status: str = "succeeded",
) -> ReviewAttempt:
    return ReviewAttempt(
        attempt_id=f"{stage}-{number}",
        item_id="item-1",
        stage=stage,  # type: ignore[arg-type]
        attempt_number=number,
        actor_type="agent",
        provider=None,
        model_id="fixture-model",
        model_version="1",
        prompt_version="avatar-v1",
        decision=decision,  # type: ignore[arg-type]
        confidence=confidence,
        reasons=(),
        findings=(),
        evidence=(),
        status=status,  # type: ignore[arg-type]
        parent_attempt_id=None,
        started_at=None,
        completed_at=None,
        elapsed_ms=None,
        error="unavailable" if status == "failed" else None,
        created_at="2026-08-04T00:00:00+00:00",
    )


class ReviewAttemptStoreTests(unittest.TestCase):
    def test_attempt_reads_and_writes_are_consumer_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "review.sqlite3")
            _insert_item(database)
            store = ReviewAttemptStore(database)
            store.append_attempt(
                item_id="item-1",
                consumer_id="default",
                stage="fast_scan",
                attempt_number=1,
                decision="review",
                confidence=0.5,
            )
            with self.assertRaises(KeyError):
                store.list_attempts("item-1", consumer_id="other")
            with self.assertRaises(KeyError):
                store.append_attempt(
                    item_id="item-1",
                    consumer_id="other",
                    stage="vision_review_1",
                    attempt_number=1,
                )
            self.assertEqual(len(store.list_recent(consumer_id="default")), 1)
            self.assertEqual(store.list_recent(consumer_id="other"), [])
            store.close()

    def test_append_is_idempotent_for_item_stage_and_attempt_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "review.sqlite3")
            _insert_item(database)
            store = ReviewAttemptStore(database)
            first = store.append_attempt(
                item_id="item-1",
                stage="fast_scan",
                attempt_number=1,
                model_id="local-fast",
                model_version="1",
                prompt_version="avatar-v1",
                decision="review",
                confidence=0.55,
                reasons=("boundary",),
                findings=({"category": "avatar", "score": 0.55},),
            )
            repeated = store.append_attempt(
                item_id="item-1",
                stage="fast_scan",
                attempt_number=1,
                model_id="local-fast",
                model_version="1",
                prompt_version="avatar-v1",
                decision="review",
                confidence=0.55,
                reasons=("boundary",),
                findings=({"score": 0.55, "category": "avatar"},),
            )

            self.assertEqual(repeated, first)
            self.assertEqual(len(store.list_attempts("item-1")), 1)
            store.close()

    def test_idempotency_key_cannot_overwrite_an_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "review.sqlite3")
            _insert_item(database)
            store = ReviewAttemptStore(database)
            store.append_attempt(
                item_id="item-1",
                stage="vision_review_1",
                attempt_number=1,
                decision="allow",
                confidence=0.95,
            )
            with self.assertRaises(AttemptConflictError):
                store.append_attempt(
                    item_id="item-1",
                    stage="vision_review_1",
                    attempt_number=1,
                    decision="block",
                    confidence=0.95,
                )
            self.assertEqual(store.list_attempts("item-1")[0].decision, "allow")
            store.close()

    def test_retry_is_a_new_append_only_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "review.sqlite3")
            _insert_item(database)
            store = ReviewAttemptStore(database)
            failed = store.append_attempt(
                item_id="item-1",
                stage="vision_review_1",
                attempt_number=1,
                decision="error",
                status="failed",
                error="timeout",
            )
            retried = store.append_attempt(
                item_id="item-1",
                stage="vision_review_1",
                attempt_number=2,
                decision="allow",
                confidence=0.96,
                parent_attempt_id=failed.attempt_id,
            )
            self.assertNotEqual(retried.attempt_id, failed.attempt_id)
            self.assertEqual([item.attempt_number for item in store.list_attempts("item-1")], [1, 2])
            store.close()


class ReviewRouterTests(unittest.TestCase):
    def test_fast_scan_uses_configured_risk_thresholds(self) -> None:
        router = ReviewRouter(RouterConfig(allow_threshold=0.2, reject_threshold=0.8))
        fast = _attempt("fast_scan", "review", 0.5)
        self.assertEqual(router.route([fast], risk_score=0.1).state, "auto_approved")
        self.assertEqual(router.route([fast], risk_score=0.9).state, "auto_rejected")
        self.assertEqual(router.route([fast], risk_score=0.5).state, "vision_review_1")

    def test_low_confidence_first_review_routes_to_independent_second_review(self) -> None:
        router = ReviewRouter()
        result = router.route(
            [_attempt("fast_scan", "review", 0.5), _attempt("vision_review_1", "allow", 0.7)]
        )
        self.assertEqual(result.state, "vision_review_2")
        self.assertEqual(result.next_stage, "vision_review_2")

    def test_second_review_disagreement_requires_human(self) -> None:
        router = ReviewRouter()
        result = router.route(
            [
                _attempt("fast_scan", "review", 0.5),
                _attempt("vision_review_1", "allow", 0.95),
                _attempt("vision_review_2", "block", 0.98),
            ]
        )
        self.assertEqual(result.state, "human_required")
        self.assertEqual(result.reason, "vision_review_disagreement")

    def test_agreeing_second_review_can_auto_decide(self) -> None:
        router = ReviewRouter()
        result = router.route(
            [
                _attempt("fast_scan", "review", 0.5),
                _attempt("vision_review_1", "allow", 0.7),
                _attempt("vision_review_2", "allow", 0.97),
            ]
        )
        self.assertEqual(result.state, "auto_approved")
        self.assertEqual(result.final_decision, "allow")

    def test_policy_can_force_a_category_to_human_review(self) -> None:
        router = ReviewRouter(
            RouterConfig(human_required_categories=frozenset({"minor_identity"}))
        )
        result = router.route(
            [_attempt("fast_scan", "allow", 0.99)], categories=("minor_identity",)
        )
        self.assertEqual(result.state, "human_required")

    def test_model_failure_retries_then_exhausts(self) -> None:
        router = ReviewRouter(RouterConfig(max_attempts_per_stage=2))
        first = _attempt("fast_scan", "error", None, status="failed")
        retry = router.route([first])
        self.assertTrue(retry.retry)
        self.assertEqual(retry.next_stage, "fast_scan")

        second = _attempt("fast_scan", "error", None, number=2, status="failed")
        exhausted = router.route([first, second])
        self.assertEqual(exhausted.state, "model_error")
        self.assertEqual(exhausted.next_stage, "human_review")


if __name__ == "__main__":
    unittest.main()
