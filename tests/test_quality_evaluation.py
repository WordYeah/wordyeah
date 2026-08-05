from __future__ import annotations

import tempfile
from pathlib import Path

from wy_core.contracts import ModerationResult
from wy_review.attempt_store import ReviewAttemptStore
from wy_review.quality import QualityStore
from wy_review.quality_evaluation import evaluate_quality_database
from wy_review.store import ReviewStore


def _fixture(database: Path, *, with_prediction: bool, with_truth: bool) -> None:
    reviews = ReviewStore(str(database))
    quality = QualityStore(str(database))
    quality.create_vocabulary(consumer_id="corpus-avatar")
    sample = quality.create_sample(
        consumer_id="corpus-avatar",
        item_id="corpus-" + "a" * 64,
        content_sha256="a" * 64,
        media_ref="media://corpus/corpus-avatar/sample.jpg",
        reason="quality_sample",
        stratum="human",
        retention_status="private_corpus",
        required_reviewers=1,
    )
    quality.create_review_batch(
        consumer_id="corpus-avatar",
        batch_id="corpus-primary-v1",
        source_sha256="f" * 64,
        fraction=1.0,
        seed="frozen",
        required_reviewers=1,
        items=((sample.sample_id, "human"),),
    )
    item = reviews.enqueue(
        ModerationResult(
            request_id="quality-prelabel",
            content_sha256="a" * 64,
            media_type="image/jpeg",
            decision="review",
            model_versions={"policy": "avatar-v1"},
        ),
        sample.media_ref,
        consumer_id="corpus-avatar",
        source_id=sample.item_id,
        source_metadata={
            "quality_ai_prelabel": True,
            "quality_sample_id": sample.sample_id,
            "ground_truth": False,
        },
    )
    reviews.close()
    if with_prediction:
        attempts = ReviewAttemptStore(str(database))
        attempts.append_attempt(
            item_id=item.item_id,
            consumer_id="corpus-avatar",
            stage="vision_review_1",
            attempt_number=1,
            decision="allow",
            confidence=0.95,
            status="succeeded",
        )
        attempts.close()
    if with_truth:
        quality.submit_decision(
            sample_id=sample.sample_id,
            consumer_id="corpus-avatar",
            reviewer_id="reviewer-a",
            decision="allow",
        )
    quality.close()


def test_unresolved_labels_remain_incomplete_and_are_not_synthesized() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        _fixture(database, with_prediction=True, with_truth=False)
        before = database.stat().st_mtime_ns
        report = evaluate_quality_database(
            database, consumer_id="corpus-avatar", gates={"human": {"minimum": 1}}
        )
        assert report["status"] == "INCOMPLETE"
        assert report["selected_count"] == 1
        assert report["human_resolved_count"] == 0
        assert report["ai_prediction_count"] == 1
        assert report["evaluable_count"] == 0
        assert report["mutates_quality_decisions"] is False
        assert database.stat().st_mtime_ns == before


def test_resolved_human_truth_and_independent_ai_attempt_are_evaluated() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        _fixture(database, with_prediction=True, with_truth=True)
        report = evaluate_quality_database(
            database,
            consumer_id="corpus-avatar",
            gates={"human": {"minimum": 1, "block_false_positive_max": 0.0}},
        )
        assert report["status"] == "INCOMPLETE"
        assert report["sample_count"] == 1
        assert report["evaluable_count"] == 1
        assert report["ground_truth_complete"] is True
        assert report["prediction_complete"] is True
        assert report["dual_review"]["status"] == "INCOMPLETE"


def test_missing_ai_attempt_cannot_count_as_prediction() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        _fixture(database, with_prediction=False, with_truth=True)
        report = evaluate_quality_database(
            database, consumer_id="corpus-avatar", gates={"human": {"minimum": 1}}
        )
        assert report["status"] == "INCOMPLETE"
        assert report["ai_prediction_count"] == 0
        assert report["evaluable_count"] == 0
