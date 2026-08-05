from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

from .attempt_store import ReviewAttempt, ReviewStage


RouteState = Literal[
    "fast_scan",
    "vision_review_1",
    "vision_review_2",
    "human_required",
    "auto_approved",
    "auto_rejected",
    "model_error",
]


@dataclass(frozen=True)
class RouterConfig:
    allow_threshold: float = 0.10
    reject_threshold: float = 0.90
    fast_scan_min_confidence: float = 0.90
    vision_review_1_min_confidence: float = 0.90
    vision_review_2_min_confidence: float = 0.90
    max_attempts_per_stage: int = 3
    human_required_categories: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        thresholds = (
            self.allow_threshold,
            self.reject_threshold,
            self.fast_scan_min_confidence,
            self.vision_review_1_min_confidence,
            self.vision_review_2_min_confidence,
        )
        if any(value < 0 or value > 1 for value in thresholds):
            raise ValueError("router thresholds must be between 0 and 1")
        if self.allow_threshold >= self.reject_threshold:
            raise ValueError("allow_threshold must be lower than reject_threshold")
        if self.max_attempts_per_stage < 1:
            raise ValueError("max_attempts_per_stage must be at least 1")

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> RouterConfig:
        allowed = {
            "allow_threshold",
            "reject_threshold",
            "fast_scan_min_confidence",
            "vision_review_1_min_confidence",
            "vision_review_2_min_confidence",
            "max_attempts_per_stage",
            "human_required_categories",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unknown router configuration: {', '.join(sorted(unknown))}")
        data = dict(values)
        if "human_required_categories" in data:
            categories = data["human_required_categories"]
            if isinstance(categories, str) or not isinstance(categories, Sequence):
                raise ValueError("human_required_categories must be a sequence of strings")
            data["human_required_categories"] = frozenset(str(value) for value in categories)
        return cls(**data)  # type: ignore[arg-type]


@dataclass(frozen=True)
class RouteResult:
    state: RouteState
    next_stage: ReviewStage | None
    final_decision: Literal["allow", "block"] | None
    reason: str
    retry: bool = False


class ReviewRouter:
    """Pure, vendor-neutral routing for the staged AI review pipeline."""

    def __init__(self, config: RouterConfig | None = None) -> None:
        self.config = config or RouterConfig()

    def route(
        self,
        attempts: Sequence[ReviewAttempt],
        *,
        risk_score: float | None = None,
        categories: Sequence[str] = (),
    ) -> RouteResult:
        if risk_score is not None and not 0 <= risk_score <= 1:
            raise ValueError("risk_score must be between 0 and 1")
        self._validate_attempts(attempts)
        latest = self._latest_by_stage(attempts)

        if "fast_scan" not in latest:
            return RouteResult("fast_scan", "fast_scan", None, "fast_scan_required")

        fast = latest["fast_scan"]
        failure = self._failure_route(fast, attempts)
        if failure is not None:
            return failure

        fast_route = self._route_fast_scan(fast, risk_score=risk_score)
        if "vision_review_1" not in latest:
            if (
                fast_route.state in {"auto_approved", "auto_rejected"}
                and self._requires_human(categories)
            ):
                return RouteResult(
                    "human_required", "human_review", None, "category_requires_human"
                )
            return fast_route
        first = latest["vision_review_1"]
        failure = self._failure_route(first, attempts)
        if failure is not None:
            return failure

        first_route = self._route_first_review(fast, first)
        if "vision_review_2" not in latest:
            if (
                first_route.state in {"auto_approved", "auto_rejected"}
                and self._requires_human(categories)
            ):
                return RouteResult(
                    "human_required", "human_review", None, "category_requires_human"
                )
            return first_route
        second = latest["vision_review_2"]
        failure = self._failure_route(second, attempts)
        if failure is not None:
            return failure
        return self._route_second_review(first, second, categories)

    def route_proposal(self, attempts: Sequence[ReviewAttempt]) -> RouteResult:
        """Route an AI-only proposal without creating an operational decision.

        Quality-corpus proposals intentionally start at the first advanced
        vision stage, so they must not be sent back through ``fast_scan`` or
        converted into an automatic allow/block decision.
        """

        self._validate_attempts(attempts)
        latest = self._latest_by_stage(attempts)
        first = latest.get("vision_review_1")
        if first is None:
            return RouteResult(
                "vision_review_1",
                "vision_review_1",
                None,
                "quality_ai_prelabel_first_review_required",
            )
        failure = self._failure_route(first, attempts)
        if failure is not None:
            return RouteResult(
                failure.state,
                failure.next_stage,
                None,
                "quality_ai_prelabel_" + failure.reason,
                retry=failure.retry,
            )

        second = latest.get("vision_review_2")
        if second is None:
            if (
                first.decision in {"allow", "block"}
                and first.confidence is not None
                and first.confidence >= self.config.vision_review_1_min_confidence
            ):
                return RouteResult(
                    "vision_review_1",
                    None,
                    None,
                    "quality_ai_prelabel_ready",
                )
            return RouteResult(
                "vision_review_2",
                "vision_review_2",
                None,
                "quality_ai_prelabel_needs_second_review",
            )

        failure = self._failure_route(second, attempts)
        if failure is not None:
            return RouteResult(
                failure.state,
                failure.next_stage,
                None,
                "quality_ai_prelabel_" + failure.reason,
                retry=failure.retry,
            )
        consensus = (
            first.decision in {"allow", "block"}
            and second.decision == first.decision
            and first.confidence is not None
            and first.confidence >= self.config.vision_review_1_min_confidence
            and second.confidence is not None
            and second.confidence >= self.config.vision_review_2_min_confidence
        )
        return RouteResult(
            "vision_review_2",
            None,
            None,
            "quality_ai_prelabel_consensus"
            if consensus
            else "quality_ai_prelabel_requires_human",
        )

    def _route_fast_scan(
        self, attempt: ReviewAttempt, *, risk_score: float | None
    ) -> RouteResult:
        if risk_score is not None:
            if risk_score <= self.config.allow_threshold:
                return self._automatic("allow", "fast_scan_risk_below_allow_threshold")
            if risk_score >= self.config.reject_threshold:
                return self._automatic("block", "fast_scan_risk_above_reject_threshold")
            return RouteResult(
                "vision_review_1", "vision_review_1", None, "fast_scan_boundary_score"
            )
        if (
            attempt.decision in {"allow", "block"}
            and attempt.confidence is not None
            and attempt.confidence >= self.config.fast_scan_min_confidence
        ):
            return self._automatic(attempt.decision, "fast_scan_high_confidence")
        return RouteResult(
            "vision_review_1", "vision_review_1", None, "fast_scan_uncertain"
        )

    def _route_first_review(
        self, fast: ReviewAttempt, first: ReviewAttempt
    ) -> RouteResult:
        if first.decision not in {"allow", "block"}:
            return RouteResult(
                "vision_review_2", "vision_review_2", None, "vision_review_1_uncertain"
            )
        if (
            first.confidence is None
            or first.confidence < self.config.vision_review_1_min_confidence
        ):
            return RouteResult(
                "vision_review_2", "vision_review_2", None, "vision_review_1_low_confidence"
            )
        if fast.decision in {"allow", "block"} and first.decision != fast.decision:
            return RouteResult(
                "vision_review_2", "vision_review_2", None, "fast_scan_disagreement"
            )
        return self._automatic(first.decision, "vision_review_1_high_confidence")

    def _route_second_review(
        self,
        first: ReviewAttempt,
        second: ReviewAttempt,
        categories: Sequence[str],
    ) -> RouteResult:
        if self._requires_human(categories):
            return RouteResult(
                "human_required", "human_review", None, "category_requires_human"
            )
        if second.decision not in {"allow", "block"}:
            return RouteResult(
                "human_required", "human_review", None, "vision_review_2_uncertain"
            )
        if (
            second.confidence is None
            or second.confidence < self.config.vision_review_2_min_confidence
        ):
            return RouteResult(
                "human_required", "human_review", None, "vision_review_2_low_confidence"
            )
        if first.decision in {"allow", "block"} and second.decision != first.decision:
            return RouteResult(
                "human_required", "human_review", None, "vision_review_disagreement"
            )
        return self._automatic(second.decision, "vision_review_2_high_confidence")

    def _failure_route(
        self, attempt: ReviewAttempt, attempts: Sequence[ReviewAttempt]
    ) -> RouteResult | None:
        if attempt.status not in {"failed", "cancelled"} and attempt.decision != "error":
            if attempt.status != "succeeded":
                return RouteResult(attempt.stage, attempt.stage, None, "attempt_not_complete")
            return None
        count = sum(candidate.stage == attempt.stage for candidate in attempts)
        if count < self.config.max_attempts_per_stage:
            return RouteResult(
                attempt.stage, attempt.stage, None, "model_retry_required", retry=True
            )
        return RouteResult("model_error", "human_review", None, "model_retries_exhausted")

    def _requires_human(self, categories: Sequence[str]) -> bool:
        return bool(self.config.human_required_categories.intersection(categories))

    @staticmethod
    def _automatic(
        decision: Literal["allow", "block"], reason: str
    ) -> RouteResult:
        if decision == "allow":
            return RouteResult("auto_approved", None, "allow", reason)
        return RouteResult("auto_rejected", None, "block", reason)

    @staticmethod
    def _latest_by_stage(attempts: Sequence[ReviewAttempt]) -> dict[ReviewStage, ReviewAttempt]:
        latest: dict[ReviewStage, ReviewAttempt] = {}
        for attempt in attempts:
            previous = latest.get(attempt.stage)
            if previous is None or attempt.attempt_number > previous.attempt_number:
                latest[attempt.stage] = attempt
        return latest

    @staticmethod
    def _validate_attempts(attempts: Sequence[ReviewAttempt]) -> None:
        item_ids = {attempt.item_id for attempt in attempts}
        if len(item_ids) > 1:
            raise ValueError("all attempts must belong to the same review item")
        keys: set[tuple[str, int]] = set()
        for attempt in attempts:
            key = (attempt.stage, attempt.attempt_number)
            if key in keys:
                raise ValueError("duplicate stage and attempt number")
            keys.add(key)


Router = ReviewRouter
