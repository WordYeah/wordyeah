from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wy_jobs.store import JobStore
from wy_review.attempt_store import ReviewAttemptStore
from wy_review.corpus_ai_prelabels import enqueue_corpus_ai_prelabels
from wy_review.corpus_prelabel_progress import audit_corpus_prelabel_progress
from wy_review.quality import QualityStore
from wy_review.store import ReviewStore


POLICY = Path(__file__).parents[1] / "config/policy.avatar.example.json"
NOW = datetime(2026, 8, 5, 13, 0, tzinfo=UTC)


def _fixture(database: Path) -> tuple[str, str]:
    digest = "a" * 64
    ReviewStore(str(database)).close()
    quality = QualityStore(str(database))
    quality.create_vocabulary(consumer_id="corpus-avatar")
    sample = quality.create_sample(
        consumer_id="corpus-avatar",
        item_id=f"corpus-{digest}",
        content_sha256=digest,
        media_ref=f"media://corpus/corpus-avatar/{digest}.jpg",
        reason="quality_sample",
        stratum="explicit_violation",
        retention_status="private_corpus",
        required_reviewers=1,
    )
    quality.create_review_batch(
        consumer_id="corpus-avatar",
        batch_id="corpus-primary-v1",
        source_sha256="b" * 64,
        fraction=1.0,
        seed="fixed",
        items=((sample.sample_id, "explicit_violation"),),
        required_reviewers=1,
    )
    quality.close()
    database.chmod(0o600)
    enqueue_corpus_ai_prelabels(
        database=database,
        policy_path=POLICY,
        consumer_id="corpus-avatar",
        apply=True,
    )
    reviews = ReviewStore(str(database))
    item = reviews.get_by_source_id(sample.item_id, consumer_id="corpus-avatar")
    reviews.close()
    return sample.sample_id, item.item_id


def _complete_first_job(database: Path, item_id: str) -> dict[str, object]:
    attempts = ReviewAttemptStore(str(database))
    attempt = attempts.append_attempt(
        item_id=item_id,
        consumer_id="corpus-avatar",
        stage="vision_review_1",
        attempt_number=1,
        provider="fixture",
        model_id="fixture-vision",
        prompt_version="fixture-v1",
        decision="allow",
        confidence=0.99,
        status="succeeded",
        completed_at=(NOW - timedelta(minutes=2)).isoformat(),
    )
    attempts.close()
    jobs = JobStore(str(database))
    result = {"attempt": attempt.to_dict()}
    jobs.connection.execute(
        """UPDATE jobs SET status = 'succeeded', attempts = 1,
                  result_json = ?, worker_id = NULL, lease_until = NULL,
                  updated_at = ?
        WHERE consumer_id = ? AND kind = 'vision_review_1'""",
        (
            json.dumps(result),
            (NOW - timedelta(minutes=2)).isoformat(),
            "corpus-avatar",
        ),
    )
    jobs.connection.commit()
    jobs.close()
    return result


def test_progress_is_read_only_and_reports_healthy_active_drain() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        _fixture(database)
        before = database.stat()
        report = audit_corpus_prelabel_progress(
            database, consumer_id="corpus-avatar", now=NOW
        )
        after = database.stat()

        assert report["status"] == "HEALTHY"
        assert report["selected_count"] == 1
        assert report["ai_prediction_count"] == 0
        assert report["jobs"]["by_status"] == {"queued": 1}
        assert report["human_truth"] == {
            "expected_untouched": True,
            "untouched": True,
            "decision_count": 0,
            "resolved_count": 0,
        }
        assert report["integrity"]["ok"] is True
        assert report["database_mode"] == "read_only"
        assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def test_progress_marks_stale_running_lease_degraded() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        _fixture(database)
        jobs = JobStore(str(database))
        job_id = jobs.connection.execute(
            "SELECT job_id FROM jobs WHERE consumer_id = ?", ("corpus-avatar",)
        ).fetchone()[0]
        jobs.connection.execute(
            """UPDATE jobs SET status = 'running', worker_id = 'stale-worker',
                      lease_until = ?, attempts = 1 WHERE job_id = ?""",
            ((NOW - timedelta(seconds=1)).isoformat(), job_id),
        )
        jobs.connection.commit()
        jobs.close()

        report = audit_corpus_prelabel_progress(
            database, consumer_id="corpus-avatar", now=NOW
        )
        assert report["status"] == "DEGRADED"
        assert report["integrity"]["stale_lease_job_ids"] == [job_id]
        assert report["jobs"]["workers"][0]["lease_remaining_seconds"] == -1.0


def test_progress_reports_complete_prediction_and_recent_throughput() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        _, item_id = _fixture(database)
        _complete_first_job(database, item_id)

        report = audit_corpus_prelabel_progress(
            database, consumer_id="corpus-avatar", now=NOW
        )
        assert report["status"] == "COMPLETE"
        assert report["prediction_complete"] is True
        assert report["ai_prediction_count"] == 1
        assert report["throughput"]["succeeded_last_15_minutes"] == 1
        assert report["throughput"]["eta_minutes"] == 0.0


def test_progress_detects_duplicate_success_and_attempt_reuse() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "wordyeah.sqlite3"
        sample_id, item_id = _fixture(database)
        result = _complete_first_job(database, item_id)
        jobs = JobStore(str(database))
        original = jobs.connection.execute(
            "SELECT * FROM jobs WHERE consumer_id = ?", ("corpus-avatar",)
        ).fetchone()
        jobs.connection.execute(
            """INSERT INTO jobs
              (job_id, kind, payload_json, result_json, status, consumer_id,
               attempts, max_attempts, idempotency_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'succeeded', ?, 1, 3, ?, ?, ?)""",
            (
                "duplicate-job",
                original["kind"],
                original["payload_json"],
                json.dumps(result),
                "corpus-avatar",
                "duplicate-idempotency-key",
                NOW.isoformat(),
                NOW.isoformat(),
            ),
        )
        jobs.connection.commit()
        jobs.close()

        report = audit_corpus_prelabel_progress(
            database, consumer_id="corpus-avatar", now=NOW
        )
        assert report["status"] == "DEGRADED"
        assert report["integrity"]["duplicate_success_groups"] == [
            {"sample_id": sample_id, "stage": "vision_review_1", "count": 2}
        ]
        duplicate_attempts = report["integrity"]["duplicate_attempt_ids"]
        assert len(duplicate_attempts) == 1
        assert set(duplicate_attempts[0]["job_ids"]) == {
            original["job_id"],
            "duplicate-job",
        }


def test_progress_rejects_final_symlink() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "wordyeah.sqlite3"
        _fixture(database)
        alias = root / "alias.sqlite3"
        alias.symlink_to(database)
        with pytest.raises(ValueError, match="must not be a symlink"):
            audit_corpus_prelabel_progress(
                alias, consumer_id="corpus-avatar", now=NOW
            )
