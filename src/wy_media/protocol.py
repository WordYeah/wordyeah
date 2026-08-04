from __future__ import annotations

from typing import Protocol

from .falconsai import ImageScores


class ImageClassifier(Protocol):
    """Common local image adapter contract used by the moderation service."""

    model_version: str
    ready: bool

    def warmup(self) -> None:
        ...

    def classify(self, image_bytes: bytes) -> ImageScores:
        ...
