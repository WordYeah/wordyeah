from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from wy_core.contracts import Finding, ModerationResult, sha256_bytes
from wy_core.policy import MediaPolicy

from .falconsai import FalconsaiClassifier


class MediaModerationService:
    """Thin orchestration layer for the first local media PoC."""

    def __init__(self, classifier: FalconsaiClassifier, policy: MediaPolicy | None = None) -> None:
        self.classifier = classifier
        self.policy = policy or MediaPolicy()

    def moderate_image(self, image_bytes: bytes, request_id: str | None = None) -> ModerationResult:
        started = perf_counter()
        content_hash = sha256_bytes(image_bytes)
        request_id = request_id or uuid4().hex
        try:
            scores = self.classifier.classify(image_bytes)
            decision, reasons = self.policy.decide_nsfw(scores.nsfw)
            return ModerationResult(
                request_id=request_id,
                content_sha256=content_hash,
                media_type="image",
                decision=decision,
                reasons=reasons,
                findings=(
                    Finding("sexual_content", "nsfw", scores.nsfw, self.classifier.model_version),
                    Finding("sexual_content", "normal", scores.normal, self.classifier.model_version),
                ),
                top_score=scores.nsfw,
                model_versions={"media.nsfw": self.classifier.model_version},
                elapsed_ms=round((perf_counter() - started) * 1000, 3),
            )
        except Exception as exc:  # API boundary: never turn model failure into allow.
            return ModerationResult(
                request_id=request_id,
                content_sha256=content_hash,
                media_type="image",
                decision="error",
                reasons=("media_classifier_failed",),
                model_versions={"media.nsfw": self.classifier.model_version},
                elapsed_ms=round((perf_counter() - started) * 1000, 3),
                error=f"{type(exc).__name__}: {exc}",
            )
