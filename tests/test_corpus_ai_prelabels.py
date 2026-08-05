from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from wy_core.contracts import ModerationResult
from wy_jobs.store import JobStore
from wy_review.attempt_store import ReviewAttemptStore
from wy_review.corpus_ai_prelabels import (
    CorpusPrelabelError,
    enqueue_corpus_ai_prelabels,
)
from wy_review.quality import QualityStore
from wy_review.store import ReviewStore


POLICY = Path(__file__).parents[1] / "config/policy.avatar.example.json"


def _create_sample(
    database: Path,
    *,
    consumer_id: str = "corpus-avatar",
    digest: str = "a" * 64,
):
    ReviewStore(str(database)).close()
    quality = QualityStore(str(database))
    quality.create_vocabulary(consumer_id=consumer_id)
    sample = quality.create_sample(
        consumer_id=consumer_id,
        item_id=f"corpus-{digest}",
        content_sha256=digest,
        media_ref=f"media://corpus/{consumer_id}/{digest}.jpg",
        reason="quality_sample",
        stratum="explicit_violation",
        retention_status="private_corpus",
        required_reviewers=1,
    )
    quality.close()
    return sample


def test_corpus_ai_prelabels_are_idempotent_and_never_create_ground_truth() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "wordyeah.sqlite3"
        sample = _create_sample(database)
        before_stat = database.stat()

        dry_run = enqueue_corpus_ai_prelabels(
            database=database,
            policy_path=POLICY,
            consumer_id="corpus-avatar",
        )
        assert dry_run["status"] == "DRY_RUN"
        assert dry_run["would_create"] == 1
        assert dry_run["human_decisions_created"] == 0
        assert dry_run["counts_toward_ground_truth"] is False
        after_stat = database.stat()
        assert after_stat.st_size == before_stat.st_size
        assert after_stat.st_mtime_ns == before_stat.st_mtime_ns
        reviews = ReviewStore(str(database))
        assert reviews.list_items(status=None, consumer_id="corpus-avatar") == []
        reviews.close()

        database.chmod(0o600)
        applied = enqueue_corpus_ai_prelabels(
            database=database,
            policy_path=POLICY,
            consumer_id="corpus-avatar",
            apply=True,
        )
        assert applied["review_items_created"] == 1
        assert applied["routes_ensured"] == 1
        assert applied["jobs_created"] == 1
        assert applied["quality_state_before"] == applied["quality_state_after"]
        assert applied["quality_state_after"] == {
            "sample_count": 1,
            "human_decision_count": 0,
            "resolved_sample_count": 0,
        }

        reviews = ReviewStore(str(database))
        item = reviews.get_by_source_id(sample.item_id, consumer_id="corpus-avatar")
        assert item.stage == "vision_review_1"
        assert item.quality_sample is False
        assert item.source_metadata["ground_truth"] is False
        assert item.source_metadata["human_decision"] is False
        assert item.source_metadata["quality_ai_prelabel"] is True
        assert item.source_metadata["counts_toward_quality_decisions"] is False
        reviews.close()

        jobs = JobStore(str(database))
        row = jobs.connection.execute(
            "SELECT payload_json FROM jobs WHERE consumer_id = ?",
            ("corpus-avatar",),
        ).fetchone()
        assert row is not None
        payload = json.loads(row["payload_json"])
        assert payload["categories"] == []
        assert "explicit_violation" not in payload["context"]
        assert "ground_truth=false" in payload["context"]
        jobs.close()

        repeated = enqueue_corpus_ai_prelabels(
            database=database,
            policy_path=POLICY,
            consumer_id="corpus-avatar",
            apply=True,
        )
        assert repeated["review_items_created"] == 0
        assert repeated["jobs_created"] == 0
        assert repeated["jobs_ensured"] == 1
        quality = QualityStore(str(database))
        assert quality.list_decisions(
            sample_id=sample.sample_id, consumer_id="corpus-avatar"
        ) == []
        persisted = quality.get_sample(
            sample_id=sample.sample_id, consumer_id="corpus-avatar"
        )
        assert persisted.final_decision is None
        assert persisted.status == "awaiting_reviews"
        quality.close()

        attempts = ReviewAttemptStore(str(database))
        first_attempt = attempts.append_attempt(
            item_id=item.item_id,
            consumer_id="corpus-avatar",
            stage="vision_review_1",
            attempt_number=1,
            provider="local",
            model_id="primary-model",
            prompt_version="primary-prompt",
            decision="review",
            confidence=0.5,
            status="succeeded",
        )
        attempts.close()
        jobs = JobStore(str(database))
        jobs.connection.execute(
            """UPDATE jobs SET status = 'succeeded', attempts = 1,
                result_json = ?
            WHERE consumer_id = ? AND kind = 'vision_review_1'""",
            (
                json.dumps({"attempt": first_attempt.to_dict()}),
                "corpus-avatar",
            ),
        )
        jobs.connection.commit()
        jobs.close()
        reviews = ReviewStore(str(database))
        reviews.apply_route(
            item.item_id,
            stage="fast_scan",
            final_decision=None,
            reason_code="fixture_old_router_bug",
            consumer_id="corpus-avatar",
        )
        reviews.close()

        reconciled = enqueue_corpus_ai_prelabels(
            database=database,
            policy_path=POLICY,
            consumer_id="corpus-avatar",
            apply=True,
        )
        assert reconciled["routes_ensured"] == 1
        assert reconciled["jobs_created"] == 1
        reviews = ReviewStore(str(database))
        repaired = reviews.get(item.item_id, consumer_id="corpus-avatar")
        assert repaired.stage == "vision_review_2"
        assert repaired.final_decision is None
        reviews.close()
        jobs = JobStore(str(database))
        second = jobs.connection.execute(
            """SELECT payload_json FROM jobs
            WHERE consumer_id = ? AND kind = 'vision_review_2'""",
            ("corpus-avatar",),
        ).fetchone()
        assert second is not None
        second_payload = json.loads(second["payload_json"])
        assert second_payload["provider_slot"] == "secondary"
        assert second_payload["parent_attempt_id"] == first_attempt.attempt_id
        jobs.close()
        quality = QualityStore(str(database))
        assert quality.list_decisions(
            sample_id=sample.sample_id, consumer_id="corpus-avatar"
        ) == []
        assert quality.get_sample(
            sample_id=sample.sample_id, consumer_id="corpus-avatar"
        ).final_decision is None
        quality.close()


def test_apply_requires_private_database_permissions() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        _create_sample(database)
        database.chmod(0o644)
        dry_run = enqueue_corpus_ai_prelabels(
            database=database, policy_path=POLICY
        )
        assert dry_run["status"] == "DRY_RUN"
        with pytest.raises(CorpusPrelabelError, match="mode 0600"):
            enqueue_corpus_ai_prelabels(
                database=database, policy_path=POLICY, apply=True
            )


def test_active_job_cap_fails_before_creating_a_review_link() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        _create_sample(database)
        database.chmod(0o600)
        jobs = JobStore(str(database))
        jobs.enqueue("unrelated", {"fixture": True}, "corpus-avatar")
        jobs.close()
        with pytest.raises(CorpusPrelabelError, match="active vision job limit"):
            enqueue_corpus_ai_prelabels(
                database=database,
                policy_path=POLICY,
                apply=True,
                max_active_jobs=1,
            )
        reviews = ReviewStore(str(database))
        assert reviews.list_items(status=None, consumer_id="corpus-avatar") == []
        reviews.close()


def test_existing_conflicting_link_fails_during_read_only_plan() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        sample = _create_sample(database)
        reviews = ReviewStore(str(database))
        reviews.enqueue(
            ModerationResult(
                request_id="conflict",
                content_sha256="a" * 64,
                media_type="image/jpeg",
                decision="review",
                model_versions={"policy": "wrong-policy"},
            ),
            sample.media_ref,
            consumer_id="corpus-avatar",
            source_id=sample.item_id,
        )
        reviews.close()
        with pytest.raises(CorpusPrelabelError, match="existing review link conflicts"):
            enqueue_corpus_ai_prelabels(database=database, policy_path=POLICY)


def test_prelabels_are_consumer_scoped() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        first = _create_sample(database, consumer_id="corpus-avatar", digest="a" * 64)
        second = _create_sample(database, consumer_id="motucloud", digest="b" * 64)
        database.chmod(0o600)
        report = enqueue_corpus_ai_prelabels(
            database=database,
            policy_path=POLICY,
            consumer_id="motucloud",
            apply=True,
        )
        assert report["selected_samples"] == 1
        reviews = ReviewStore(str(database))
        assert reviews.get_by_source_id(second.item_id, consumer_id="motucloud")
        with pytest.raises(KeyError):
            reviews.get_by_source_id(first.item_id, consumer_id="corpus-avatar")
        reviews.close()


def test_non_private_quality_sample_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        quality = QualityStore(str(database))
        quality.create_vocabulary(consumer_id="corpus-avatar")
        digest = "a" * 64
        quality.create_sample(
            consumer_id="corpus-avatar",
            item_id=f"corpus-{digest}",
            content_sha256=digest,
            media_ref=f"media://corpus/corpus-avatar/{digest}.jpg",
            retention_status="active",
        )
        quality.close()
        with pytest.raises(CorpusPrelabelError, match="not retained as private corpus"):
            enqueue_corpus_ai_prelabels(database=database, policy_path=POLICY)
