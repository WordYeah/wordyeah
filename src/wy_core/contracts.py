from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Literal

Decision = Literal["allow", "block", "review", "error"]


def sha256_bytes(payload: bytes) -> str:
    """Return a stable content key without persisting the submitted media."""

    return sha256(payload).hexdigest()


@dataclass(frozen=True)
class Finding:
    category: str
    label: str
    score: float | None = None
    source: str = "unknown"

    def __post_init__(self) -> None:
        if self.score is not None and not 0.0 <= self.score <= 1.0:
            raise ValueError("finding score must be between 0 and 1")


@dataclass(frozen=True)
class ModerationResult:
    request_id: str
    content_sha256: str
    media_type: str
    decision: Decision
    reasons: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    top_score: float | None = None
    model_versions: dict[str, str] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    error: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in {"allow", "block", "review", "error"}:
            raise ValueError(f"unknown decision: {self.decision}")
        if self.top_score is not None and not 0.0 <= self.top_score <= 1.0:
            raise ValueError("top_score must be between 0 and 1")
        if self.decision == "error" and not self.error:
            raise ValueError("error decision must include an error message")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["findings"] = [asdict(finding) for finding in self.findings]
        value["reasons"] = list(self.reasons)
        return value
