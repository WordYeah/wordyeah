from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from wy_jobs.store import JobStore
from wy_jobs.vision import VisionReviewJobPayload, enqueue_vision_review
from wy_review.attempt_store import ReviewAttemptStore
from wy_review.media_integrity_recovery import (
    MediaIntegrityRecoveryError,
    recover_legacy_vision_media_hashes,
)


def _legacy_payload(
    media_ref: str,
    *,
    item_id: str = "item-1",
    context: str = "consumer=corpus-avatar",
):
    return VisionReviewJobPayload(
        item_id=item_id,
        media_ref=media_ref,
        media_type="image/jpeg",
        stage="vision_review_1",
        attempt_number=1,
        request_id=f"{item_id}:vision_review_1:1",
        policy_version="policy-v1",
        content_sha256="a" * 64,
        context=context,
    )


def test_recovery_is_dry_run_by_default_and_preserves_decisions() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "wordyeah.sqlite3"
        media_root = root / "media"
        media = media_root / "review" / "avatar.jpg"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"normalized-review-media")

        store = JobStore(str(database))
        legacy = enqueue_vision_review(
            store,
            _legacy_payload("media://review/avatar.jpg"),
            "corpus-avatar",
        )
        enqueue_vision_review(
            store,
            _legacy_payload(
                "media://review/avatar.jpg",
                item_id="quality-item",
                context="quality_ai_prelabel=true; ground_truth=false",
            ),
            "corpus-avatar",
        )
        store.close()
        before = database.stat()

        dry_run = recover_legacy_vision_media_hashes(
            database=database,
            media_root=media_root,
            consumer_id="corpus-avatar",
        )

        assert dry_run["status"] == "DRY_RUN"
        assert dry_run["repairable_jobs"] == 1
        assert dry_run["jobs_created"] == 0
        assert dry_run["mutates_avatar"] is False
        assert dry_run["decision_state_before"] == dry_run["decision_state_after"]
        after = database.stat()
        assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
        store = JobStore(str(database))
        assert store.get(legacy.job_id).status == "queued"
        store.close()


def test_apply_cancels_legacy_job_and_enqueues_integrity_bound_replacement() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "wordyeah.sqlite3"
        media_root = root / "media"
        media = media_root / "review" / "avatar.jpg"
        media.parent.mkdir(parents=True)
        media_bytes = b"normalized-review-media"
        media.write_bytes(media_bytes)
        expected_hash = hashlib.sha256(media_bytes).hexdigest()

        store = JobStore(str(database))
        legacy = enqueue_vision_review(
            store,
            _legacy_payload("media://review/avatar.jpg"),
            "corpus-avatar",
        )
        store.close()
        database.chmod(0o600)

        applied = recover_legacy_vision_media_hashes(
            database=database,
            media_root=media_root,
            consumer_id="corpus-avatar",
            apply=True,
        )

        assert applied["jobs_cancelled"] == 1
        assert applied["jobs_created"] == 1
        assert applied["decision_state_before"] == applied["decision_state_after"]
        store = JobStore(str(database))
        cancelled = store.get(legacy.job_id)
        assert cancelled.status == "cancelled"
        assert cancelled.error_kind == "media_integrity_superseded"
        replacement = store.connection.execute(
            "SELECT payload_json FROM jobs WHERE status = 'queued'"
        ).fetchone()
        assert replacement is not None
        assert json.loads(replacement["payload_json"])["media_sha256"] == expected_hash
        store.close()

        repeated = recover_legacy_vision_media_hashes(
            database=database,
            media_root=media_root,
            consumer_id="corpus-avatar",
            apply=True,
        )
        assert repeated["repairable_jobs"] == 0
        assert repeated["jobs_created"] == 0


def test_apply_requires_private_database_permissions() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "wordyeah.sqlite3"
        media_root = root / "media"
        media_root.mkdir()
        JobStore(str(database)).close()
        database.chmod(0o644)

        with pytest.raises(MediaIntegrityRecoveryError, match="mode 0600"):
            recover_legacy_vision_media_hashes(
                database=database,
                media_root=media_root,
                consumer_id="corpus-avatar",
                apply=True,
            )


def test_failed_attempt_conflict_is_requeued_at_next_attempt_number() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "wordyeah.sqlite3"
        media_root = root / "media"
        media = media_root / "review" / "avatar.jpg"
        media.parent.mkdir(parents=True)
        media_bytes = b"normalized-review-media"
        media.write_bytes(media_bytes)
        media_hash = hashlib.sha256(media_bytes).hexdigest()

        store = JobStore(str(database))
        store.connection.execute(
            """INSERT INTO review_items
            (item_id, consumer_id, content_sha256, media_type, media_ref,
             decision_hint, reasons_json, status, policy_version, top_score, created_at)
            VALUES ('item-1', 'corpus-avatar', ?, 'image', 'media://review/avatar.jpg',
                    'review', '[]', 'pending', 'policy-v1', 0.5,
                    '2026-08-05T00:00:00+00:00')""",
            ("a" * 64,),
        )
        store.connection.commit()
        attempts = ReviewAttemptStore(str(database))
        attempts.append_attempt(
            item_id="item-1",
            consumer_id="corpus-avatar",
            stage="vision_review_1",
            attempt_number=1,
            decision="error",
            status="failed",
            error="legacy media mismatch",
        )
        attempts.close()
        stale = enqueue_vision_review(
            store,
            VisionReviewJobPayload(
                **{
                    **_legacy_payload("media://review/avatar.jpg").to_dict(),
                    "media_sha256": media_hash,
                }
            ),
            "corpus-avatar",
        )
        store.connection.execute(
            """UPDATE jobs SET status = 'failed', error_kind = 'worker_error',
                error = 'AttemptConflictError: fixture' WHERE job_id = ?""",
            (stale.job_id,),
        )
        store.connection.commit()
        store.close()
        database.chmod(0o600)

        applied = recover_legacy_vision_media_hashes(
            database=database,
            media_root=media_root,
            consumer_id="corpus-avatar",
            apply=True,
        )

        assert applied["failed_sources_requeued"] == 1
        assert applied["jobs_created"] == 1
        store = JobStore(str(database))
        replacement = store.connection.execute(
            "SELECT payload_json FROM jobs WHERE status = 'queued'"
        ).fetchone()
        assert replacement is not None
        assert json.loads(replacement["payload_json"])["attempt_number"] == 2
        store.close()


def test_apply_refuses_to_race_a_running_normal_vision_job() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "wordyeah.sqlite3"
        media_root = root / "media"
        media = media_root / "review" / "avatar.jpg"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"normalized-review-media")
        store = JobStore(str(database))
        enqueue_vision_review(
            store,
            _legacy_payload("media://review/avatar.jpg"),
            "corpus-avatar",
        )
        assert store.claim(
            "active-worker", kinds=("vision_review_1",)
        ) is not None
        store.close()
        database.chmod(0o600)

        with pytest.raises(MediaIntegrityRecoveryError, match="zero running jobs"):
            recover_legacy_vision_media_hashes(
                database=database,
                media_root=media_root,
                consumer_id="corpus-avatar",
                apply=True,
            )


def test_dry_run_rejects_symlinked_controlled_media() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "wordyeah.sqlite3"
        media_root = root / "media"
        media_root.mkdir()
        target = root / "target.jpg"
        target.write_bytes(b"outside-controlled-root")
        (media_root / "avatar.jpg").symlink_to(target)
        store = JobStore(str(database))
        enqueue_vision_review(
            store,
            _legacy_payload("media://avatar.jpg"),
            "corpus-avatar",
        )
        store.close()

        report = recover_legacy_vision_media_hashes(
            database=database,
            media_root=media_root,
            consumer_id="corpus-avatar",
        )

        assert report["repairable_jobs"] == 0
        assert report["states"] == {"invalid_payload": 1}
