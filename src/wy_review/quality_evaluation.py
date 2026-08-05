"""Evaluate the frozen quality corpus without treating AI proposals as truth."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Mapping

from wy_review.evaluation import DEFAULT_GATES, CorpusRecord, evaluate_corpus


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
                  attempt.stage, attempt.attempt_number, attempt.decision,
                  attempt.created_at
        FROM quality_samples AS sample
        JOIN review_items AS review
          ON review.consumer_id = sample.consumer_id
         AND review.source_id = sample.item_id
        JOIN review_attempts AS attempt ON attempt.item_id = review.item_id
        WHERE sample.consumer_id = ?
          AND attempt.status = 'succeeded'
          AND attempt.stage IN ('vision_review_1', 'vision_review_2')
          AND attempt.decision IN ('allow', 'review', 'block')
        ORDER BY sample.sample_id,
                 CASE attempt.stage WHEN 'vision_review_2' THEN 0 ELSE 1 END,
                 attempt.attempt_number DESC, attempt.created_at DESC""",
        (consumer_id,),
    ).fetchall()
    predictions: dict[str, str] = {}
    for row in rows:
        if row["sample_id"] in predictions:
            continue
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
        predictions[row["sample_id"]] = row["decision"]
    return predictions
