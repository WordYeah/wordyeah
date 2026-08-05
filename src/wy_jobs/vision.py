from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from .store import Job, JobStore

VisionJobKind = Literal["vision_review_1", "vision_review_2"]
VISION_JOB_KINDS: tuple[VisionJobKind, ...] = ("vision_review_1", "vision_review_2")


@dataclass(frozen=True)
class VisionReviewJobPayload:
    """Versioned, JSON-safe contract for an advanced vision queue job."""

    item_id: str
    media_ref: str
    media_type: str
    stage: VisionJobKind
    attempt_number: int
    request_id: str
    policy_version: str
    content_sha256: str
    media_sha256: str | None = None
    categories: tuple[str, ...] = ()
    context: str = ""
    parent_attempt_id: str | None = None
    provider_slot: str = "primary"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported vision job payload schema_version")
        if not self.item_id or len(self.item_id) > 128:
            raise ValueError("item_id must be between 1 and 128 characters")
        if self.stage not in VISION_JOB_KINDS:
            raise ValueError("stage must be vision_review_1 or vision_review_2")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")
        if not self.media_ref.startswith("media://") or len(self.media_ref) > 512:
            raise ValueError("media_ref must be a controlled media:// reference")
        if self.media_type not in {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}:
            raise ValueError("unsupported image media_type")
        if not self.request_id or len(self.request_id) > 128:
            raise ValueError("request_id must be between 1 and 128 characters")
        if not self.policy_version or len(self.policy_version) > 128:
            raise ValueError("policy_version must be between 1 and 128 characters")
        if len(self.content_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 hex digest")
        if self.media_sha256 is not None and (
            len(self.media_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.media_sha256)
        ):
            raise ValueError("media_sha256 must be a lowercase SHA-256 hex digest")
        if any(not value or len(value) > 128 for value in self.categories):
            raise ValueError("categories must contain non-empty values up to 128 characters")
        if len(self.context) > 4000:
            raise ValueError("context is too long")
        if self.parent_attempt_id is not None and not self.parent_attempt_id:
            raise ValueError("parent_attempt_id cannot be empty")
        if not self.provider_slot or len(self.provider_slot) > 64:
            raise ValueError("provider_slot must be between 1 and 64 characters")

    @property
    def idempotency_key(self) -> str:
        identity = {
            "consumer_contract": "wordyeah-vision-job-v1",
            "item_id": self.item_id,
            "stage": self.stage,
            "attempt_number": self.attempt_number,
            "provider_slot": self.provider_slot,
            "policy_version": self.policy_version,
            "content_sha256": self.content_sha256,
            "media_sha256": self.media_sha256,
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"vision-review:v1:{digest}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "item_id": self.item_id,
            "media_ref": self.media_ref,
            "media_type": self.media_type,
            "stage": self.stage,
            "attempt_number": self.attempt_number,
            "request_id": self.request_id,
            "policy_version": self.policy_version,
            "content_sha256": self.content_sha256,
            "media_sha256": self.media_sha256,
            "categories": list(self.categories),
            "context": self.context,
            "parent_attempt_id": self.parent_attempt_id,
            "provider_slot": self.provider_slot,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> VisionReviewJobPayload:
        categories = value.get("categories", ())
        if isinstance(categories, str) or not isinstance(categories, Sequence):
            raise ValueError("categories must be an array of strings")
        if any(not isinstance(item, str) for item in categories):
            raise ValueError("categories must be an array of strings")
        return cls(
            schema_version=_integer(value.get("schema_version", 1), "schema_version"),
            item_id=_string(value, "item_id"),
            media_ref=_string(value, "media_ref"),
            media_type=_string(value, "media_type"),
            stage=_string(value, "stage"),  # type: ignore[arg-type]
            attempt_number=_integer(value.get("attempt_number"), "attempt_number"),
            request_id=_string(value, "request_id"),
            policy_version=_string(value, "policy_version"),
            content_sha256=_string(value, "content_sha256"),
            media_sha256=_optional_string(value.get("media_sha256"), "media_sha256"),
            categories=tuple(categories),
            context=_optional_string(value.get("context"), "context") or "",
            parent_attempt_id=_optional_string(value.get("parent_attempt_id"), "parent_attempt_id"),
            provider_slot=_optional_string(value.get("provider_slot", "primary"), "provider_slot") or "primary",
        )


def enqueue_vision_review(
    store: JobStore,
    payload: VisionReviewJobPayload,
    consumer_id: str,
    *,
    max_attempts: int = 3,
) -> Job:
    return store.enqueue(
        payload.stage,
        payload.to_dict(),
        consumer_id,
        max_attempts=max_attempts,
        idempotency_key=payload.idempotency_key,
    )


def _string(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str):
        raise ValueError(f"{field} must be a string")
    return item


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string when provided")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value
