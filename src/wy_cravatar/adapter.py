from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from wy_core.contracts import ModerationResult

AdapterMode = Literal["shadow", "review", "enforce"]
Action = Literal["record_only", "allow", "queue_review", "block", "hold"]


@dataclass(frozen=True)
class CravatarAction:
    mode: AdapterMode
    action: Action
    source_decision: str
    mutates_avatar: bool
    reason: str


class CravatarAdapter:
    """Translate a WordYeah result without connecting to WordPress.

    This adapter is intentionally pure. Production PHP/WP wiring is a later
    gate and cannot be reached from this package.
    """

    def __init__(self, mode: AdapterMode = "shadow") -> None:
        self.mode = mode

    def translate(self, result: ModerationResult) -> CravatarAction:
        if self.mode == "shadow":
            return CravatarAction("shadow", "record_only", result.decision, False, "shadow_no_avatar_mutation")
        if self.mode == "review":
            if result.decision == "allow":
                return CravatarAction("review", "allow", result.decision, False, "review_mode_allow")
            if result.decision == "error":
                return CravatarAction("review", "hold", result.decision, False, "classifier_error_hold")
            return CravatarAction("review", "queue_review", result.decision, False, "manual_review_required")
        if result.decision == "allow":
            return CravatarAction("enforce", "allow", result.decision, False, "enforce_allow")
        if result.decision == "block":
            return CravatarAction("enforce", "block", result.decision, True, "enforce_block")
        if result.decision == "error":
            return CravatarAction("enforce", "hold", result.decision, False, "classifier_error_hold")
        return CravatarAction("enforce", "queue_review", result.decision, False, "manual_review_required")
