"""Evaluate the frozen quality corpus without treating AI proposals as truth."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Mapping

from wy_review.corpus_ai_prelabels import is_corpus_ai_prelabel_context
from wy_review.evaluation import DEFAULT_GATES, CorpusRecord, evaluate_corpus
from wy_review.attempt_store import ReviewAttempt
from wy_review.router import ReviewRouter


def evaluate_quality_database(
    database: str | Path,
    *,
    consumer_id: str,
    batch_id: str = "corpus-primary-v1",
    gates: Mapping[str, Mapping[str, float | int]] = DEFAULT_GATES,
) -> dict[str, object]:
    """Build evidence only from resolved human labels and independent AI attempts."""

    if not consumer_id or len(consumer_id) > 128:
        raise ValueError("consumer_id must be between 1 and 128 characters")
    if not batch_id or len(batch_id) > 128:
        raise ValueError("batch_id must be between 1 and 128 characters")
    database_path = Path(database).expanduser().resolve(strict=True)
    connection = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        batch = connection.execute(
            """SELECT source_sha256, required_reviewers
            FROM quality_review_batches
            WHERE consumer_id = ? AND batch_id = ?""",
            (consumer_id, batch_id),
        ).fetchone()
        if batch is None:
            raise KeyError(f"quality review batch not found: {batch_id}")
        rows = connection.execute(
            """SELECT item.ordinal, sample.sample_id, sample.item_id,
                      sample.content_sha256, sample.stratum, sample.status,
                      sample.final_decision, sample.required_reviewers,
                      COUNT(DISTINCT decision.reviewer_id) AS reviewer_count,
                      COUNT(DISTINCT arbitration.arbitration_id) AS arbitration_count
            FROM quality_review_batch_items AS item
            JOIN quality_samples AS sample
              ON sample.consumer_id = item.consumer_id
             AND sample.sample_id = item.sample_id
            LEFT JOIN quality_decisions AS decision
              ON decision.consumer_id = sample.consumer_id
             AND decision.sample_id = sample.sample_id
            LEFT JOIN quality_arbitrations AS arbitration
              ON arbitration.consumer_id = sample.consumer_id
             AND arbitration.sample_id = sample.sample_id
            WHERE item.consumer_id = ? AND item.batch_id = ?
            GROUP BY item.ordinal, sample.sample_id
            ORDER BY item.ordinal""",
            (consumer_id, batch_id),
        ).fetchall()
        predictions = _quality_predictions(connection, consumer_id=consumer_id)
    finally:
        connection.close()

    selected_count = len(rows)
    resolved_count = sum(
        row["status"] == "resolved" and row["final_decision"] is not None for row in rows
    )
    predicted_count = sum(row["sample_id"] in predictions for row in rows)
    records: list[CorpusRecord] = []
    for row in rows:
        expected = row["final_decision"] if row["status"] == "resolved" else None
        predicted = predictions.get(row["sample_id"])
        if expected is None or predicted is None:
            continue
        records.append(
            CorpusRecord(
                record_id=row["sample_id"],
                content_sha256=row["content_sha256"],
                stratum=row["stratum"],
                expected=expected,
                predicted=predicted,
                split="test",
                dual_reviewed=bool(
                    int(row["reviewer_count"]) >= 2
                    or int(row["arbitration_count"]) >= 1
                ),
            )
        )

    report = evaluate_corpus(records, gates=gates)
    incomplete_reasons: list[str] = []
    if selected_count == 0:
        incomplete_reasons.append("empty_frozen_batch")
    if resolved_count < selected_count:
        incomplete_reasons.append("human_ground_truth_incomplete")
    if predicted_count < selected_count:
        incomplete_reasons.append("ai_predictions_incomplete")
    if len(records) < selected_count:
        incomplete_reasons.append("evaluable_pairs_incomplete")
    if report["status"] != "FAIL" and incomplete_reasons:
        report["status"] = "INCOMPLETE"
    report.update(
        {
            "kind": "wordyeah_quality_corpus_evaluation",
            "consumer_id": consumer_id,
            "batch_id": batch_id,
            "source_sha256": batch["source_sha256"],
            "selected_count": selected_count,
            "human_resolved_count": resolved_count,
            "ai_prediction_count": predicted_count,
            "evaluable_count": len(records),
            "ground_truth_complete": selected_count > 0
            and resolved_count == selected_count,
            "prediction_complete": selected_count > 0
            and predicted_count == selected_count,
            "incomplete_reasons": incomplete_reasons,
            "database_mode": "read_only",
            "mutates_quality_decisions": False,
            "mutates_avatar": False,
        }
    )
    return report


def _quality_predictions(
    connection: sqlite3.Connection, *, consumer_id: str
) -> dict[str, str]:
    rows = connection.execute(
        """SELECT sample.sample_id, review.source_metadata_json,
                  attempt.attempt_id, attempt.item_id, attempt.stage,
                  attempt.attempt_number, attempt.actor_type, attempt.provider,
                  attempt.model_id, attempt.model_version, attempt.prompt_version,
                  attempt.decision, attempt.confidence, attempt.status,
                  attempt.parent_attempt_id, attempt.started_at,
                  attempt.completed_at, attempt.elapsed_ms, attempt.error,
                  attempt.created_at, job.payload_json
        FROM quality_samples AS sample
        JOIN review_items AS review
          ON review.consumer_id = sample.consumer_id
         AND review.source_id = sample.item_id
        JOIN review_attempts AS attempt ON attempt.item_id = review.item_id
        JOIN jobs AS job
          ON job.consumer_id = sample.consumer_id
         AND json_extract(job.result_json, '$.attempt.attempt_id') = attempt.attempt_id
        WHERE sample.consumer_id = ?
          AND attempt.status = 'succeeded'
          AND attempt.stage IN ('vision_review_1', 'vision_review_2')
          AND attempt.decision IN ('allow', 'review', 'block')
        ORDER BY sample.sample_id, attempt.stage,
                 attempt.attempt_number, attempt.created_at""",
        (consumer_id,),
    ).fetchall()
    grouped: dict[str, list[ReviewAttempt]] = {}
    for row in rows:
        try:
            metadata = json.loads(row["source_metadata_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, dict):
            continue
        if metadata.get("quality_ai_prelabel") is not True:
            continue
        if metadata.get("quality_sample_id") != row["sample_id"]:
            continue
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not is_corpus_ai_prelabel_context(
            str(payload.get("context", ""))
        ):
            continue
        grouped.setdefault(row["sample_id"], []).append(
            ReviewAttempt(
                attempt_id=row["attempt_id"],
                item_id=row["item_id"],
                stage=row["stage"],
                attempt_number=int(row["attempt_number"]),
                actor_type=row["actor_type"],
                provider=row["provider"],
                model_id=row["model_id"],
                model_version=row["model_version"],
                prompt_version=row["prompt_version"],
                decision=row["decision"],
                confidence=row["confidence"],
                reasons=(),
                findings=(),
                evidence=(),
                status=row["status"],
                parent_attempt_id=row["parent_attempt_id"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                elapsed_ms=row["elapsed_ms"],
                error=row["error"],
                created_at=row["created_at"],
            )
        )

    predictions: dict[str, str] = {}
    router = ReviewRouter()
    for sample_id, attempts in grouped.items():
        route = router.route_proposal(attempts)
        if route.reason == "quality_ai_prelabel_ready":
            first = max(
                (attempt for attempt in attempts if attempt.stage == "vision_review_1"),
                key=lambda attempt: attempt.attempt_number,
            )
            assert first.decision in {"allow", "block"}
            predictions[sample_id] = first.decision
        elif route.reason == "quality_ai_prelabel_consensus":
            second = max(
                (attempt for attempt in attempts if attempt.stage == "vision_review_2"),
                key=lambda attempt: attempt.attempt_number,
            )
            assert second.decision in {"allow", "block"}
            predictions[sample_id] = second.decision
        elif route.reason == "quality_ai_prelabel_requires_human":
            predictions[sample_id] = "review"
    return predictions
