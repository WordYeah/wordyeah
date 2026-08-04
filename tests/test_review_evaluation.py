from __future__ import annotations

import json

import pytest

from wy_review.evaluation import CorpusRecord, evaluate_corpus, load_jsonl


def record(
    record_id: str,
    *,
    stratum: str = "human",
    expected: str = "allow",
    predicted: str = "allow",
    split: str = "test",
    near_duplicate_group: str | None = None,
    dual_reviewed: bool = True,
) -> CorpusRecord:
    return CorpusRecord.from_mapping(
        {
            "record_id": record_id,
            "content_sha256": f"{int(record_id):064x}",
            "stratum": stratum,
            "expected": expected,
            "predicted": predicted,
            "split": split,
            "near_duplicate_group": near_duplicate_group,
            "dual_reviewed": dual_reviewed,
        }
    )


def test_zero_samples_are_skip_not_pass() -> None:
    report = evaluate_corpus([])
    assert report["status"] == "SKIP"
    assert report["strata"]["human"]["status"] == "SKIP"
    assert report["dual_review"]["status"] == "SKIP"


def test_insufficient_samples_are_incomplete() -> None:
    report = evaluate_corpus([record("1")])
    assert report["status"] == "INCOMPLETE"
    assert report["strata"]["human"]["status"] == "INCOMPLETE"


def test_thresholds_pass_with_small_explicit_test_gates() -> None:
    rows = [
        record("1", stratum="human"),
        record("2", stratum="explicit_violation", expected="block", predicted="block"),
    ]
    report = evaluate_corpus(
        rows,
        gates={
            "human": {"minimum": 1, "block_false_positive_max": 0.0, "review_rate_max": 0.0},
            "explicit_violation": {"minimum": 1, "block_recall_min": 1.0},
        },
    )
    assert report["status"] == "PASS"
    assert report["strata"]["explicit_violation"]["metrics"]["block_recall"] == 1.0


def test_metric_failure_cannot_pass() -> None:
    report = evaluate_corpus(
        [record("1", predicted="block")],
        gates={"human": {"minimum": 1, "block_false_positive_max": 0.0}},
    )
    assert report["status"] == "FAIL"
    assert report["strata"]["human"]["failures"] == ["block_false_positive_rate"]


def test_exact_and_near_duplicate_split_leakage_fails() -> None:
    first = record("1", split="train", near_duplicate_group="face-a")
    second = CorpusRecord(
        record_id="2",
        content_sha256=first.content_sha256,
        stratum="human",
        expected="allow",
        predicted="allow",
        split="test",
        near_duplicate_group="face-a",
        dual_reviewed=True,
    )
    report = evaluate_corpus([first, second], gates={"human": {"minimum": 2}})
    assert report["status"] == "FAIL"
    assert {error["kind"] for error in report["split_integrity"]["errors"]} == {
        "sha256",
        "near_duplicate_group",
    }


def test_dual_review_gate_is_reported() -> None:
    rows = [record(str(index), dual_reviewed=index == 1) for index in range(1, 12)]
    report = evaluate_corpus(rows, gates={"human": {"minimum": 1}})
    assert report["status"] == "INCOMPLETE"
    assert report["dual_review"]["status"] == "INCOMPLETE"


def test_jsonl_loader_reports_line_number(tmp_path) -> None:
    path = tmp_path / "corpus.jsonl"
    path.write_text(json.dumps({"record_id": "missing"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        load_jsonl(path)
