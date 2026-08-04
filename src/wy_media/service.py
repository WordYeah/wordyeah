from __future__ import annotations

from collections import OrderedDict
from time import perf_counter
from uuid import uuid4

from wy_core.contracts import Finding, ModerationResult, sha256_bytes
from wy_core.policy import MediaPolicy

from .protocol import ImageClassifier


class MediaModerationService:
    """Thin orchestration layer for the first local media PoC."""

    def __init__(
        self,
        classifier: ImageClassifier,
        policy: MediaPolicy | None = None,
        policy_version: str = "policy-default",
        cache_size: int = 1024,
    ) -> None:
        self.classifier = classifier
        self.policy = policy or MediaPolicy()
        self.policy_version = policy_version
        self.cache_size = cache_size
        self._cache: OrderedDict[str, ModerationResult] = OrderedDict()
        self.cache_hits = 0

    @property
    def ready(self) -> bool:
        return bool(getattr(self.classifier, "ready", False))

    def warmup(self) -> None:
        warmup = getattr(self.classifier, "warmup", None)
        if warmup is None:
            return
        warmup()

    def moderate_image(self, image_bytes: bytes, request_id: str | None = None) -> ModerationResult:
        started = perf_counter()
        content_hash = sha256_bytes(image_bytes)
        request_id = request_id or uuid4().hex
        cache_key = f"{self.policy_version}:{content_hash}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            self._cache.move_to_end(cache_key)
            return cached
        try:
            scores = self.classifier.classify(image_bytes)
            decision, reasons = self.policy.decide_nsfw(scores.nsfw)
            result = ModerationResult(
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
                model_versions={
                    "media.nsfw": self.classifier.model_version,
                    "policy": self.policy_version,
                },
                elapsed_ms=round((perf_counter() - started) * 1000, 3),
            )
            if self.cache_size > 0:
                self._cache[cache_key] = result
                self._cache.move_to_end(cache_key)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
            return result
        except Exception as exc:  # API boundary: never turn model failure into allow.
            return ModerationResult(
                request_id=request_id,
                content_sha256=content_hash,
                media_type="image",
                decision="error",
                reasons=("media_classifier_failed",),
                model_versions={
                    "media.nsfw": self.classifier.model_version,
                    "policy": self.policy_version,
                },
                elapsed_ms=round((perf_counter() - started) * 1000, 3),
                error=f"{type(exc).__name__}: {exc}",
            )
