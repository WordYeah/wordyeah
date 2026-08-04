from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Literal, Mapping, Protocol, Sequence, runtime_checkable


VisionDecision = Literal["allow", "review", "block"]


class VisionErrorKind(str, Enum):
    """Stable error classes used by retry and escalation policy."""

    DISABLED = "disabled"
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    BAD_REQUEST = "bad_request"
    UPSTREAM = "upstream"
    INVALID_RESPONSE = "invalid_response"


class VisionProviderError(RuntimeError):
    def __init__(
        self,
        kind: VisionErrorKind,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "kind": self.kind.value,
            "message": str(self),
            "retryable": self.retryable,
        }
        if self.status_code is not None:
            result["status_code"] = self.status_code
        if self.retry_after_seconds is not None:
            result["retry_after_seconds"] = self.retry_after_seconds
        return result


@dataclass(frozen=True)
class VisionReviewRequest:
    image_bytes: bytes
    media_type: str
    request_id: str
    categories: tuple[str, ...] = ()
    context: str = ""

    def __post_init__(self) -> None:
        if not self.image_bytes:
            raise ValueError("image_bytes must not be empty")
        if self.media_type not in {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}:
            raise ValueError("unsupported image media_type")
        if not self.request_id or len(self.request_id) > 128:
            raise ValueError("request_id must be between 1 and 128 characters")
        if len(self.context) > 4000:
            raise ValueError("context is too long")
        if any(not category or len(category) > 128 for category in self.categories):
            raise ValueError("categories must contain non-empty values up to 128 characters")


@dataclass(frozen=True)
class VisionFinding:
    category: str
    label: str
    score: float | None = None
    explanation: str | None = None
    region: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.category or not self.label:
            raise ValueError("finding category and label are required")
        if self.score is not None and not 0 <= self.score <= 1:
            raise ValueError("finding score must be between 0 and 1")

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        return {key: item for key, item in value.items() if item is not None}


@dataclass(frozen=True)
class VisionEvidence:
    kind: str
    description: str
    region: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.kind or not self.description:
            raise ValueError("evidence kind and description are required")

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        return {key: item for key, item in value.items() if item is not None}


@dataclass(frozen=True)
class VisionReviewConclusion:
    decision: VisionDecision
    confidence: float
    reasons: tuple[str, ...]
    findings: tuple[VisionFinding, ...]
    evidence: tuple[VisionEvidence, ...]
    provider: str
    model_id: str
    model_version: str | None
    prompt_version: str
    request_id: str

    def __post_init__(self) -> None:
        if self.decision not in {"allow", "review", "block"}:
            raise ValueError("unknown vision decision")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not self.provider or not self.model_id or not self.prompt_version or not self.request_id:
            raise ValueError("provider, model_id, prompt_version and request_id are required")
        if any(not reason or len(reason) > 500 for reason in self.reasons):
            raise ValueError("reasons must contain non-empty values up to 500 characters")

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "findings": [finding.to_dict() for finding in self.findings],
            "evidence": [item.to_dict() for item in self.evidence],
            "provider": self.provider,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "request_id": self.request_id,
        }

    def to_attempt_payload(self, *, stage: str, attempt_number: int) -> dict[str, object]:
        """Return fields accepted by the existing review-attempt endpoint."""

        if stage not in {"vision_review_1", "vision_review_2"}:
            raise ValueError("advanced vision conclusion requires a vision review stage")
        if attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")
        return {
            "stage": stage,
            "attempt_number": attempt_number,
            "provider": self.provider,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "decision": self.decision,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "findings": [finding.to_dict() for finding in self.findings],
            "evidence": [item.to_dict() for item in self.evidence],
            "status": "succeeded",
        }


@runtime_checkable
class AdvancedVisionProvider(Protocol):
    """Provider-neutral boundary for advanced image review adapters."""

    provider_name: str
    model_id: str
    enabled: bool

    def review(self, request: VisionReviewRequest) -> VisionReviewConclusion:
        ...


def string_sequence(value: object, *, field: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be an array of strings")
    result = tuple(item for item in value if isinstance(item, str) and item.strip())
    if len(result) != len(value):
        raise ValueError(f"{field} must contain non-empty strings")
    return result
