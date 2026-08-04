from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping


Decision = Literal["allow", "review", "block", "error"]


@dataclass(frozen=True)
class CorpusRecord:
    record_id: str
    content_sha256: str
    stratum: str
    expected: Decision
    predicted: Decision
    split: str = "test"
    near_duplicate_group: str | None = None
    dual_reviewed: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "CorpusRecord":
        required = ("record_id", "content_sha256", "stratum", "expected", "predicted")
        missing = [key for key in required if not str(value.get(key, "")).strip()]
        if missing:
            raise ValueError(f"missing corpus fields: {', '.join(missing)}")
        expected = str(value["expected"])
        predicted = str(value["predicted"])
        decisions = {"allow", "review", "block", "error"}
        if expected not in decisions or predicted not in decisions:
            raise ValueError("expected and predicted must be allow, review, block, or error")
        digest = str(value["content_sha256"])
        if len(digest) != 64 or any(character not in "0123456789abcdefABCDEF" for character in digest):
            raise ValueError("content_sha256 must be a 64-character hexadecimal digest")
        return cls(
            record_id=str(value["record_id"]),
            content_sha256=digest.lower(),
            stratum=str(value["stratum"]),
            expected=expected,  # type: ignore[arg-type]
            predicted=predicted,  # type: ignore[arg-type]
            split=str(value.get("split", "test")),
            near_duplicate_group=(
                str(value["near_duplicate_group"])
                if value.get("near_duplicate_group") not in (None, "")
                else None
            ),
            dual_reviewed=bool(value.get("dual_reviewed", False)),
        )


DEFAULT_GATES: dict[str, dict[str, float | int]] = {
    "human": {"minimum": 300, "block_false_positive_max": 0.005, "review_rate_max": 0.03},
    "illustration": {"minimum": 300, "block_false_positive_max": 0.005, "review_rate_max": 0.05},
    "logo_text": {"minimum": 100},
    "boundary": {"minimum": 200},
    "explicit_violation": {"minimum": 200, "block_recall_min": 0.95},
}


def load_jsonl(path: str | Path) -> list[CorpusRecord]:
    records: list[CorpusRecord] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("record must be an object")
                records.append(CorpusRecord.from_mapping(value))
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid corpus record at line {line_number}: {exc}") from exc
    return records


def evaluate_corpus(
    records: Iterable[CorpusRecord],
    *,
    gates: Mapping[str, Mapping[str, float | int]] = DEFAULT_GATES,
    dual_review_min: float = 0.10,
) -> dict[str, object]:
    rows = list(records)
    split_errors = _split_leakage(rows)
    strata: dict[str, dict[str, object]] = {}
    blocking_states: list[str] = []

    for stratum, gate in gates.items():
        selected = [row for row in rows if row.stratum == stratum]
        sample_count = len(selected)
        minimum = int(gate.get("minimum", 0))
        if sample_count == 0:
            result: dict[str, object] = {
                "status": "SKIP",
                "sample_count": 0,
                "minimum": minimum,
                "reason": "zero_samples",
            }
        elif sample_count < minimum:
            result = {
                "status": "INCOMPLETE",
                "sample_count": sample_count,
                "minimum": minimum,
                "reason": "insufficient_samples",
            }
        else:
            result = _evaluate_stratum(selected, gate)
            result["sample_count"] = sample_count
            result["minimum"] = minimum
        strata[stratum] = result
        if result["status"] != "PASS":
            blocking_states.append(str(result["status"]))

    reviewed = sum(row.dual_reviewed for row in rows)
    dual_review_rate = reviewed / len(rows) if rows else 0.0
    dual_review_status = (
        "SKIP" if not rows else "PASS" if dual_review_rate >= dual_review_min else "INCOMPLETE"
    )
    if dual_review_status != "PASS":
        blocking_states.append(dual_review_status)
    if split_errors:
        blocking_states.append("FAIL")

    status = "PASS"
    if "FAIL" in blocking_states:
        status = "FAIL"
    elif "INCOMPLETE" in blocking_states:
        status = "INCOMPLETE"
    elif "SKIP" in blocking_states:
        status = "SKIP"

    return {
        "status": status,
        "sample_count": len(rows),
        "decision_counts": dict(sorted(Counter(row.predicted for row in rows).items())),
        "strata": strata,
        "dual_review": {
            "status": dual_review_status,
            "reviewed": reviewed,
            "rate": dual_review_rate,
            "minimum_rate": dual_review_min,
        },
        "split_integrity": {
            "status": "PASS" if not split_errors else "FAIL",
            "errors": split_errors,
        },
    }


def _evaluate_stratum(
    rows: list[CorpusRecord], gate: Mapping[str, float | int]
) -> dict[str, object]:
    failures: list[str] = []
    metrics: dict[str, float] = {}
    expected_allow = [row for row in rows if row.expected == "allow"]
    expected_block = [row for row in rows if row.expected == "block"]

    if "block_false_positive_max" in gate:
        denominator = len(expected_allow)
        rate = sum(row.predicted == "block" for row in expected_allow) / denominator if denominator else 0.0
        metrics["block_false_positive_rate"] = rate
        if not denominator or rate > float(gate["block_false_positive_max"]):
            failures.append("block_false_positive_rate")
    if "review_rate_max" in gate:
        denominator = len(expected_allow)
        rate = sum(row.predicted == "review" for row in expected_allow) / denominator if denominator else 0.0
        metrics["review_rate"] = rate
        if not denominator or rate > float(gate["review_rate_max"]):
            failures.append("review_rate")
    if "block_recall_min" in gate:
        denominator = len(expected_block)
        recall = sum(row.predicted == "block" for row in expected_block) / denominator if denominator else 0.0
        metrics["block_recall"] = recall
        if not denominator or recall < float(gate["block_recall_min"]):
            failures.append("block_recall")

    return {"status": "FAIL" if failures else "PASS", "metrics": metrics, "failures": failures}


def _split_leakage(rows: list[CorpusRecord]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        groups[("sha256", row.content_sha256)].add(row.split)
        if row.near_duplicate_group:
            groups[("near_duplicate_group", row.near_duplicate_group)].add(row.split)
    return [
        {"kind": kind, "value": value, "splits": sorted(splits)}
        for (kind, value), splits in sorted(groups.items())
        if len(splits) > 1
    ]
