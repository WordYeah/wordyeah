from __future__ import annotations

import hashlib
import json
import socket
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from wy_core.database import open_database
from wy_jobs.store import JobStore, retry_delay_seconds
from wy_jobs.vision import VisionReviewJobPayload, enqueue_vision_review
from wy_media.g2a import G2AConfig, G2AVisionProvider, HttpResponse
from wy_media.vision_worker import VisionReviewWorker
from wy_review.attempt_store import ReviewAttemptStore
from wy_review.router import ReviewRouter, RouterConfig
from wy_review.store import ReviewStore


def response(decision: str, confidence: float) -> HttpResponse:
    return HttpResponse(
        200,
        json.dumps(
            {
                "decision": decision,
                "confidence": confidence,
                "reasons": [f"fixture_{decision}"],
                "findings": [],
                "evidence": [],
            }
        ).encode(),
    )


def provider(model: str, transport) -> G2AVisionProvider:
    return G2AVisionProvider(
        G2AConfig(
            enabled=True,
            endpoint="https://g2a.invalid/v1/chat/completions",
            api_key="fixture-key",
            model_id=model,
            prompt_version=f"prompt-{model}",
        ),
        transport=transport,
    )


class VisionWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = str(root / "wordyeah.sqlite3")
        self.media_root = root / "media"
        self.media_root.mkdir()
        self.image = b"mock-image-without-network"
        (self.media_root / "avatar.png").write_bytes(self.image)
        self.digest = hashlib.sha256(self.image).hexdigest()
        connection = open_database(self.database)
        connection.execute(
            """
            INSERT INTO review_items
              (item_id, consumer_id, content_sha256, media_type, media_ref,
               decision_hint, reasons_json, status, policy_version, top_score, created_at)
            VALUES ('item-1', 'consumer-a', ?, 'image', 'media://avatar.png',
                    'review', '[]', 'pending', 'policy-v1', 0.5, ?)
            """,
            (self.digest, "2026-08-05T00:00:00+00:00"),
        )
        connection.commit()
        connection.close()
        self.jobs = JobStore(self.database)
        self.attempts = ReviewAttemptStore(self.database)
        self.reviews = ReviewStore(self.database)
        self.attempts.append_attempt(
            item_id="item-1",
            stage="fast_scan",
            attempt_number=1,
            decision="review",
            confidence=0.5,
            status="succeeded",
        )

    def tearDown(self) -> None:
        self.jobs.close()
        self.attempts.close()
        self.reviews.close()
        self.temp.cleanup()

    def payload(self, **changes: object) -> VisionReviewJobPayload:
        values: dict[str, object] = {
            "item_id": "item-1",
            "media_ref": "media://avatar.png",
            "media_type": "image/png",
            "stage": "vision_review_1",
            "attempt_number": 1,
            "request_id": "item-1:vision_review_1:1",
            "policy_version": "policy-v1",
            "content_sha256": self.digest,
            "provider_slot": "primary",
        }
        values.update(changes)
        return VisionReviewJobPayload(**values)  # type: ignore[arg-type]

    def worker(self, primary_transport, secondary_transport=None, **changes) -> VisionReviewWorker:
        providers = {"primary": provider("primary-model", primary_transport)}
        if secondary_transport is not None:
            providers["secondary"] = provider("secondary-model", secondary_transport)
        values = {
            "job_store": self.jobs,
            "attempt_store": self.attempts,
            "review_store": self.reviews,
            "providers": providers,
            "media_root": self.media_root,
            "worker_id": "vision-test",
        }
        values.update(changes)
        return VisionReviewWorker(**values)

    def test_payload_key_and_enqueue_are_stable(self) -> None:
        first_payload = self.payload(categories=("violence", "adult"))
        repeated_payload = self.payload(categories=("adult", "violence"))
        self.assertEqual(first_payload.idempotency_key, repeated_payload.idempotency_key)
        first = enqueue_vision_review(self.jobs, first_payload, "consumer-a")
        repeated = enqueue_vision_review(self.jobs, first_payload, "consumer-a")
        self.assertEqual(first.job_id, repeated.job_id)
        with self.assertRaisesRegex(ValueError, "different data"):
            enqueue_vision_review(self.jobs, repeated_payload, "consumer-a")

    def test_allow_converges_without_network(self) -> None:
        job = enqueue_vision_review(self.jobs, self.payload(), "consumer-a")
        finished = self.worker(lambda _r, _t: response("allow", 0.98)).run_once()
        self.assertEqual(finished.job_id, job.job_id)
        self.assertEqual(finished.status, "succeeded")
        self.assertEqual(self.reviews.get("item-1").stage, "auto_approved")

    def test_block_converges_without_network(self) -> None:
        enqueue_vision_review(self.jobs, self.payload(), "consumer-a")
        finished = self.worker(lambda _r, _t: response("block", 0.98)).run_once()
        self.assertEqual(finished.status, "succeeded")
        self.assertEqual(self.reviews.get("item-1").stage, "auto_rejected")

    def test_low_confidence_first_review_enqueues_independent_second_review(self) -> None:
        enqueue_vision_review(self.jobs, self.payload(), "consumer-a")
        worker = self.worker(
            lambda _r, _t: response("allow", 0.70),
            lambda _r, _t: response("block", 0.99),
        )
        first = worker.run_once()
        self.assertEqual(first.status, "succeeded")
        second = worker.run_once()
        self.assertEqual(second.kind, "vision_review_2")
        self.assertEqual(second.status, "succeeded")
        self.assertEqual(self.reviews.get("item-1").stage, "human_required")
        recorded = self.attempts.list_attempts("item-1")
        self.assertEqual([item.stage for item in recorded], ["fast_scan", "vision_review_1", "vision_review_2"])
        self.assertNotEqual(recorded[1].model_id, recorded[2].model_id)

    def test_timeout_retries_with_backoff_then_succeeds_as_new_attempt(self) -> None:
        calls = 0

        def transport(_request, _timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise socket.timeout("fixture timeout")
            return response("allow", 0.99)

        job = enqueue_vision_review(self.jobs, self.payload(), "consumer-a", max_attempts=3)
        worker = self.worker(transport, backoff_base_seconds=0.001, backoff_cap_seconds=0.001)
        first = worker.run_once()
        self.assertEqual(first.status, "queued")
        self.assertEqual(first.error_kind, "timeout")
        self.assertTrue(first.retryable)
        time.sleep(0.005)
        second = worker.run_once()
        self.assertEqual(second.job_id, job.job_id)
        self.assertEqual(second.status, "succeeded")
        vision_attempts = self.attempts.list_attempts("item-1", "vision_review_1")
        self.assertEqual([item.attempt_number for item in vision_attempts], [1, 2])
        self.assertEqual([item.status for item in vision_attempts], ["failed", "succeeded"])

    def test_rate_limit_honors_retry_after_header(self) -> None:
        enqueue_vision_review(self.jobs, self.payload(), "consumer-a")
        failed = self.worker(
            lambda _r, _t: HttpResponse(429, b"ignored", {"Retry-After": "7"})
        ).run_once()
        self.assertEqual(failed.status, "queued")
        self.assertEqual(failed.error_kind, "rate_limit")
        delay = datetime.fromisoformat(failed.available_at) - datetime.fromisoformat(failed.updated_at)
        self.assertGreaterEqual(delay.total_seconds(), 6.9)

    def test_invalid_response_is_dead_lettered_and_routed_to_model_error(self) -> None:
        enqueue_vision_review(self.jobs, self.payload(), "consumer-a")
        failed = self.worker(
            lambda _r, _t: HttpResponse(200, b'{"decision":"allow","confidence":"certain"}')
        ).run_once()
        self.assertEqual(failed.status, "failed")
        self.assertTrue(failed.dead_lettered)
        self.assertFalse(failed.retryable)
        self.assertEqual(failed.error_kind, "invalid_response")
        self.assertEqual(self.reviews.get("item-1").stage, "model_error")

    def test_retryable_error_exhausts_max_attempts(self) -> None:
        enqueue_vision_review(self.jobs, self.payload(), "consumer-a", max_attempts=2)
        worker = self.worker(
            lambda _r, _t: HttpResponse(503, b"ignored"),
            backoff_base_seconds=0.001,
            backoff_cap_seconds=0.001,
            router=ReviewRouter(RouterConfig(max_attempts_per_stage=2)),
        )
        first = worker.run_once()
        self.assertEqual(first.status, "queued")
        time.sleep(0.005)
        exhausted = worker.run_once()
        self.assertTrue(exhausted.dead_lettered)
        self.assertEqual(exhausted.attempts, 2)
        self.assertEqual(self.reviews.get("item-1").stage, "model_error")

    def test_backoff_is_exponential_and_capped(self) -> None:
        self.assertEqual([retry_delay_seconds(i, base_seconds=2, cap_seconds=5) for i in (1, 2, 3)], [2, 4, 5])


if __name__ == "__main__":
    unittest.main()
