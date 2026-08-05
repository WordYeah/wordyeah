"""Create AI proposals for a private quality corpus without creating truth labels."""

from __future__ import annotations

import json
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from wy_core.config import load_policy_config
from wy_core.contracts import ModerationResult
from wy_jobs.store import JobStore
from wy_jobs.vision import VisionReviewJobPayload, enqueue_vision_review

from .store import ReviewItem, ReviewStore


class CorpusPrelabelError(RuntimeError):
    """Raised when a corpus sample cannot safely become an AI proposal."""


@dataclass(frozen=True)
class CorpusPrelabelCandidate:
    sample_id: str
    item_id: str
    content_sha256: str
    media_ref: str
    linked_item_id: str | None
    linked_stage: str | None
    linked_content_sha256: str | None
    linked_media_ref: str | None
    linked_policy_version: str | None
    linked_source_metadata: dict[str, object] | None
    retention_status: str
    link_count: int


def enqueue_corpus_ai_prelabels(
    *,
    database: str | Path,
    policy_path: str | Path,
    consumer_id: str = "corpus-avatar",
    limit: int | None = None,
    apply: bool = False,
    max_active_jobs: int = 2000,
) -> dict[str, object]:
    """Plan or enqueue model proposals without writing quality decisions."""

    database_path = _database_path(database)
    if not consumer_id or len(consumer_id) > 128:
        raise ValueError("consumer_id must be between 1 and 128 characters")
    if limit is not None and (limit < 1 or limit > 100_000):
        raise ValueError("limit must be between 1 and 100000")
    if max_active_jobs < 1:
        raise ValueError("max_active_jobs must be positive")
    policy = load_policy_config(policy_path)
    candidates, before = _read_snapshot(database_path, consumer_id, limit)
    _validate_candidates(candidates, consumer_id, policy.policy_version)

    report: dict[str, object] = {
        "kind": "wordyeah_corpus_ai_prelabels",
        "status": "APPLIED" if apply else "DRY_RUN",
        "applied": apply,
        "consumer_id": consumer_id,
        "policy_version": policy.policy_version,
        "selected_samples": len(candidates),
        "already_linked": sum(row.linked_item_id is not None for row in candidates),
        "would_create": sum(row.linked_item_id is None for row in candidates),
        "would_ensure_jobs": sum(
            row.linked_item_id is None
            or row.linked_stage in {"fast_scan", "vision_review_1"}
            for row in candidates
        ),
        "already_processed": sum(
            row.linked_item_id is not None
            and row.linked_stage not in {"fast_scan", "vision_review_1"}
            for row in candidates
        ),
        "conflicts": 0,
        "review_items_created": 0,
        "routes_ensured": 0,
        "jobs_created": 0,
        "jobs_ensured": 0,
        "human_decisions_created": 0,
        "counts_toward_ground_truth": False,
        "stratum_or_expected_label_in_prompt": False,
        "mutates_avatar": False,
        "production_write": False,
        "quality_state_before": before,
    }
    if not apply:
        report["quality_state_after"] = dict(before)
        return report

    if stat.S_IMODE(database_path.stat().st_mode) != 0o600:
        raise CorpusPrelabelError("apply requires a private database with mode 0600")

    review_store = ReviewStore(str(database_path))
    job_store = JobStore(str(database_path))
    created = routes_ensured = jobs_created = jobs_ensured = 0
    try:
        for candidate in candidates:
            try:
                item = review_store.get_by_source_id(
                    candidate.item_id, consumer_id=consumer_id
                )
            except KeyError:
                if job_store.count_active(consumer_id) >= max_active_jobs:
                    raise CorpusPrelabelError(
                        f"active vision job limit reached before sample {candidate.sample_id}"
                    )
                item = review_store.enqueue(
                    ModerationResult(
                        request_id=f"quality-prelabel-{candidate.sample_id[:24]}",
                        content_sha256=candidate.content_sha256,
                        media_type=_media_type(candidate.media_ref),
                        decision="review",
                        reasons=("quality_sample_ai_prelabel",),
                        model_versions={"policy": policy.policy_version},
                    ),
                    candidate.media_ref,
                    consumer_id=consumer_id,
                    source_id=candidate.item_id,
                    source_ref=f"quality://{candidate.sample_id}",
                    source_metadata=_source_metadata(candidate.sample_id),
                    force=True,
                )
                created += 1
            _validate_link(item, candidate, policy.policy_version)
            if item.stage not in {"fast_scan", "vision_review_1"}:
                continue
            payload = _payload(item, candidate)
            existing_job = job_store.connection.execute(
                "SELECT 1 FROM jobs WHERE consumer_id = ? AND idempotency_key = ?",
                (consumer_id, payload.idempotency_key),
            ).fetchone()
            if existing_job is None and job_store.count_active(consumer_id) >= max_active_jobs:
                raise CorpusPrelabelError(
                    f"active vision job limit reached before sample {candidate.sample_id}"
                )
            if item.stage == "fast_scan":
                item = review_store.apply_route(
                    item.item_id,
                    stage="vision_review_1",
                    final_decision=None,
                    reason_code="quality_sample_ai_prelabel",
                    actor_id="quality-prelabel-router",
                    consumer_id=consumer_id,
                )
                routes_ensured += 1
                payload = _payload(item, candidate)
            enqueue_vision_review(job_store, payload, consumer_id, max_attempts=3)
            jobs_ensured += 1
            if existing_job is None:
                jobs_created += 1
    finally:
        job_store.close()
        review_store.close()

    _, after = _read_snapshot(database_path, consumer_id, limit=0)
    if before != after:
        raise CorpusPrelabelError("quality decision state changed while creating AI proposals")
    report.update(
        {
            "review_items_created": created,
            "routes_ensured": routes_ensured,
            "jobs_created": jobs_created,
            "jobs_ensured": jobs_ensured,
            "quality_state_after": after,
        }
    )
    return report


def is_corpus_ai_prelabel(metadata: Mapping[str, object]) -> bool:
    """Identify an AI proposal that is explicitly excluded from human truth."""

    return metadata == _source_metadata(str(metadata.get("quality_sample_id", "")))


def _source_metadata(sample_id: str) -> dict[str, object]:
    return {
        "origin": "quality_corpus",
        "quality_sample_id": sample_id,
        "quality_ai_prelabel": True,
        "ground_truth": False,
        "human_decision": False,
        "counts_toward_quality_decisions": False,
        "stratum_hidden_from_model": True,
    }


def _database_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("database must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"database does not exist: {path}") from exc
    if not resolved.is_file():
        raise ValueError("database must be a regular file")
    return resolved


def _read_snapshot(
    database: Path, consumer_id: str, limit: int | None
) -> tuple[list[CorpusPrelabelCandidate], dict[str, int]]:
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        sample_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM quality_samples WHERE consumer_id = ?",
                (consumer_id,),
            ).fetchone()[0]
        )
        decision_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM quality_decisions WHERE consumer_id = ?",
                (consumer_id,),
            ).fetchone()[0]
        )
        resolved_count = int(
            connection.execute(
                """SELECT COUNT(*) FROM quality_samples
                WHERE consumer_id = ? AND final_decision IS NOT NULL""",
                (consumer_id,),
            ).fetchone()[0]
        )
        pagination = ""
        parameters: list[object] = [consumer_id]
        if limit is not None and limit > 0:
            pagination = " LIMIT ?"
            parameters.append(limit)
        rows = connection.execute(
            f"""
            SELECT qs.sample_id, qs.item_id, qs.content_sha256, qs.media_ref,
                   qs.retention_status,
                   MIN(ri.item_id) AS linked_item_id,
                   MIN(ri.stage) AS linked_stage,
                   MIN(ri.content_sha256) AS linked_content_sha256,
                   MIN(ri.media_ref) AS linked_media_ref,
                   MIN(ri.policy_version) AS linked_policy_version,
                   MIN(ri.source_metadata_json) AS linked_source_metadata_json,
                   COUNT(ri.item_id) AS link_count
            FROM quality_samples AS qs
            LEFT JOIN review_items AS ri
              ON ri.consumer_id = qs.consumer_id AND ri.source_id = qs.item_id
            WHERE qs.consumer_id = ?
            GROUP BY qs.sample_id, qs.item_id, qs.content_sha256, qs.media_ref
            ORDER BY qs.created_at, qs.sample_id{pagination}
            """,
            parameters,
        ).fetchall()
    finally:
        connection.close()
    candidates = [
        CorpusPrelabelCandidate(
            sample_id=row["sample_id"],
            item_id=row["item_id"],
            content_sha256=row["content_sha256"],
            media_ref=row["media_ref"],
            linked_item_id=row["linked_item_id"],
            linked_stage=row["linked_stage"],
            linked_content_sha256=row["linked_content_sha256"],
            linked_media_ref=row["linked_media_ref"],
            linked_policy_version=row["linked_policy_version"],
            linked_source_metadata=(
                _metadata(row["linked_source_metadata_json"])
                if row["linked_source_metadata_json"] is not None
                else None
            ),
            retention_status=row["retention_status"],
            link_count=int(row["link_count"]),
        )
        for row in rows
    ]
    return candidates, {
        "sample_count": sample_count,
        "human_decision_count": decision_count,
        "resolved_sample_count": resolved_count,
    }


def _validate_candidates(
    candidates: list[CorpusPrelabelCandidate],
    consumer_id: str,
    policy_version: str,
) -> None:
    for candidate in candidates:
        if candidate.link_count > 1:
            raise CorpusPrelabelError(
                f"multiple review items link to quality sample {candidate.sample_id}"
            )
        if len(candidate.content_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in candidate.content_sha256
        ):
            raise CorpusPrelabelError(
                f"invalid content hash for quality sample {candidate.sample_id}"
            )
        if candidate.retention_status != "private_corpus":
            raise CorpusPrelabelError(
                f"quality sample is not retained as private corpus: {candidate.sample_id}"
            )
        if candidate.item_id != f"corpus-{candidate.content_sha256}":
            raise CorpusPrelabelError(
                f"quality sample has an invalid corpus item id: {candidate.sample_id}"
            )
        if not candidate.media_ref.startswith(f"media://corpus/{consumer_id}/"):
            raise CorpusPrelabelError(
                f"uncontrolled media reference for quality sample {candidate.sample_id}"
            )
        _media_type(candidate.media_ref)
        if candidate.linked_item_id is not None and (
            candidate.linked_content_sha256 != candidate.content_sha256
            or candidate.linked_media_ref != candidate.media_ref
            or candidate.linked_policy_version != policy_version
            or candidate.linked_source_metadata != _source_metadata(candidate.sample_id)
        ):
            raise CorpusPrelabelError(
                f"existing review link conflicts with quality sample {candidate.sample_id}"
            )


def _metadata(raw: object) -> dict[str, object]:
    if not isinstance(raw, str):
        raise CorpusPrelabelError("review source metadata is not stored as JSON text")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CorpusPrelabelError("review source metadata is invalid JSON") from exc
    if not isinstance(value, dict):
        raise CorpusPrelabelError("review source metadata must be an object")
    return value


def _validate_link(
    item: ReviewItem,
    candidate: CorpusPrelabelCandidate,
    policy_version: str,
) -> None:
    if (
        item.source_id != candidate.item_id
        or item.content_sha256 != candidate.content_sha256
        or item.media_ref != candidate.media_ref
        or item.source_metadata != _source_metadata(candidate.sample_id)
        or item.policy_version != policy_version
    ):
        raise CorpusPrelabelError(
            f"existing review link conflicts with quality sample {candidate.sample_id}"
        )


def _payload(
    item: ReviewItem, candidate: CorpusPrelabelCandidate
) -> VisionReviewJobPayload:
    return VisionReviewJobPayload(
        item_id=item.item_id,
        media_ref=item.media_ref,
        media_type=_media_type(item.media_ref),
        stage="vision_review_1",
        attempt_number=1,
        request_id=f"{item.item_id}:vision_review_1:quality-prelabel",
        policy_version=item.policy_version,
        content_sha256=item.content_sha256,
        media_sha256=candidate.content_sha256,
        categories=(),
        context=(
            f"consumer={item.consumer_id}; policy={item.policy_version}; "
            "quality_ai_prelabel=true; ground_truth=false"
        ),
        provider_slot="primary",
    )


def _media_type(media_ref: str) -> str:
    suffix = Path(media_ref.removeprefix("media://")).suffix.lower()
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(suffix)
    if media_type is None:
        raise CorpusPrelabelError(f"unsupported corpus image type: {suffix or 'missing'}")
    return media_type
