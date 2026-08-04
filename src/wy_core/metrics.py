from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class DecisionMetrics:
    total: int
    exact_matches: int
    expected_allow: int
    expected_review: int
    expected_block: int
    false_positive: int
    false_negative: int

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = asdict(self)
        value["accuracy"] = self.exact_matches / self.total if self.total else None
        value["false_positive_rate"] = (
            self.false_positive / self.expected_allow if self.expected_allow else None
        )
        value["block_recall"] = (
            (self.expected_block - self.false_negative) / self.expected_block
            if self.expected_block
            else None
        )
        value["block_false_negative_rate"] = (
            self.false_negative / self.expected_block if self.expected_block else None
        )
        value["block_recall_status"] = "MEASURED" if self.expected_block else "SKIP_NO_EXPECTED_BLOCK"
        return value


def evaluate_decisions(expected: Iterable[str], observed: Iterable[str]) -> DecisionMetrics:
    expected_values = list(expected)
    observed_values = list(observed)
    if len(expected_values) != len(observed_values):
        raise ValueError("expected and observed decision counts differ")
    allowed = {"allow", "review", "block", "error"}
    if any(value not in allowed for value in expected_values + observed_values):
        raise ValueError("unknown decision in evaluation")

    return DecisionMetrics(
        total=len(expected_values),
        exact_matches=sum(left == right for left, right in zip(expected_values, observed_values)),
        expected_allow=expected_values.count("allow"),
        expected_review=expected_values.count("review"),
        expected_block=expected_values.count("block"),
        false_positive=sum(
            wanted == "allow" and got in {"review", "block"}
            for wanted, got in zip(expected_values, observed_values)
        ),
        false_negative=sum(
            wanted == "block" and got in {"allow", "review"}
            for wanted, got in zip(expected_values, observed_values)
        ),
    )
