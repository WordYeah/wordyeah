from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from wy_core.contracts import ModerationResult

from .adapter import CravatarAction, CravatarAdapter


@dataclass(frozen=True)
class ShadowRecord:
    avatar_ref: str
    request_id: str
    content_sha256: str
    source_decision: str
    action: Literal["record_only"]
    mutates_avatar: bool
    recorded_at: str
    source_id: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "avatar_ref": self.avatar_ref,
            "request_id": self.request_id,
            "content_sha256": self.content_sha256,
            "source_decision": self.source_decision,
            "action": self.action,
            "mutates_avatar": self.mutates_avatar,
            "recorded_at": self.recorded_at,
        }


class CravatarShadowConnector:
    """Local shadow boundary; it records metadata and never changes an avatar."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.adapter = CravatarAdapter("shadow")

    def submit(
        self,
        avatar_ref: str,
        result: ModerationResult,
        *,
        source_id: str | None = None,
    ) -> ShadowRecord | None:
        if not self.enabled:
            return None
        if not avatar_ref or avatar_ref.startswith(("http://", "https://")):
            raise ValueError("avatar_ref must be a local/staging identifier")
        action: CravatarAction = self.adapter.translate(result)
        if action.mutates_avatar or action.action != "record_only":
            raise RuntimeError("shadow connector received a mutating action")
        stable_source_id = source_id or f"cravatar-sha256:{result.content_sha256}"
        if (
            not isinstance(stable_source_id, str)
            or not stable_source_id.strip()
            or stable_source_id.lower().startswith(("http://", "https://"))
        ):
            raise ValueError("source_id must be a local/staging identifier")
        return ShadowRecord(
            source_id=stable_source_id,
            avatar_ref=avatar_ref,
            request_id=result.request_id,
            content_sha256=result.content_sha256,
            source_decision=result.decision,
            action="record_only",
            mutates_avatar=False,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
