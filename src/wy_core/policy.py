from __future__ import annotations

from dataclasses import dataclass

from .contracts import Decision


@dataclass(frozen=True)
class MediaPolicy:
    """Initial, deliberately uncalibrated policy for the local PoC.

    These thresholds are configuration defaults for smoke testing only. They
    must be recalibrated against a manually labelled corpus before enforcement.
    """

    review_threshold: float = 0.30
    block_threshold: float = 0.85

    def __post_init__(self) -> None:
        if not 0.0 <= self.review_threshold <= self.block_threshold <= 1.0:
            raise ValueError("thresholds must satisfy 0 <= review <= block <= 1")

    def decide_nsfw(self, score: float) -> tuple[Decision, tuple[str, ...]]:
        if not 0.0 <= score <= 1.0:
            raise ValueError("NSFW score must be between 0 and 1")
        if score >= self.block_threshold:
            return "block", ("nsfw_score_at_or_above_block_threshold",)
        if score >= self.review_threshold:
            return "review", ("nsfw_score_at_or_above_review_threshold",)
        return "allow", ()
