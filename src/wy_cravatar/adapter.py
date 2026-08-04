from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from wy_core.contracts import ModerationResult

AdapterMode = Literal["shadow", "review", "enforce"]
AvatarAction = Literal["keep", "replace_default", "blacklist"]
Action = Literal["record_only", "allow", "queue_review", "replace_default", "blacklist", "hold"]


@dataclass(frozen=True)
class CravatarAction:
    mode: AdapterMode
    action: Action
    source_decision: str
    mutates_avatar: bool
    reason: str
    avatar_action: AvatarAction | None = None


class CravatarAdapter:
    """Translate a WordYeah result without connecting to WordPress.

    This adapter is intentionally pure. Production PHP/WP wiring is a later
    gate and cannot be reached from this package.
    """

    def __init__(self, mode: AdapterMode = "shadow") -> None:
        self.mode = mode

    def translate(
        self,
        result: ModerationResult,
        avatar_action: AvatarAction | None = None,
    ) -> CravatarAction:
        if avatar_action is not None and avatar_action not in {"keep", "replace_default", "blacklist"}:
            raise ValueError("unknown avatar action")
        if self.mode == "shadow":
            return CravatarAction("shadow", "record_only", result.decision, False, "shadow_no_avatar_mutation")
        if self.mode == "review":
            if result.decision == "allow":
                return CravatarAction("review", "allow", result.decision, False, "review_mode_allow")
            if result.decision == "error":
                return CravatarAction("review", "hold", result.decision, False, "classifier_error_hold")
            return CravatarAction("review", "queue_review", result.decision, False, "manual_review_required")
        if result.decision == "allow":
            if avatar_action not in {None, "keep"}:
                raise ValueError("allow decisions can only keep the avatar")
            return CravatarAction("enforce", "allow", result.decision, False, "enforce_allow", "keep")
        if result.decision == "block":
            resolved = avatar_action or "replace_default"
            if resolved == "keep":
                raise ValueError("block decisions cannot keep the avatar")
            return CravatarAction(
                "enforce",
                resolved,
                result.decision,
                True,
                f"enforce_{resolved}",
                resolved,
            )
        if result.decision == "error":
            return CravatarAction("enforce", "hold", result.decision, False, "classifier_error_hold")
        return CravatarAction("enforce", "queue_review", result.decision, False, "manual_review_required")
