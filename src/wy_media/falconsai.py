from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ImageScores:
    normal: float
    nsfw: float


class FalconsaiClassifier:
    """Local-only wrapper around Falconsai/nsfw_image_detection.

    Model and processor imports are lazy so the core contract tests do not
    require the ML runtime. ``local_files_only=True`` is intentional: a
    moderation request must never trigger a model download or external call.
    """

    model_id = "Falconsai/nsfw_image_detection"
    model_version = "Falconsai/nsfw_image_detection"

    def __init__(self, model_path: str | Path | None = None, device: str = "auto") -> None:
        self.model_path = str(model_path or self.model_id)
        self.device_name = self._choose_device(device)
        self._processor: Any | None = None
        self._model: Any | None = None

    @staticmethod
    def _choose_device(requested: str) -> str:
        if requested != "auto":
            return requested
        import torch

        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def _load(self) -> None:
        if self._processor is not None and self._model is not None:
            return
        from transformers import AutoImageProcessor, AutoModelForImageClassification

        self._processor = AutoImageProcessor.from_pretrained(
            self.model_path,
            local_files_only=True,
        )
        self._model = AutoModelForImageClassification.from_pretrained(
            self.model_path,
            local_files_only=True,
        ).eval()
        self._model.to(self.device_name)

    def classify(self, image_bytes: bytes) -> ImageScores:
        from io import BytesIO

        from PIL import Image

        self._load()
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt")
        inputs = {key: value.to(self.device_name) for key, value in inputs.items()}

        import torch

        with torch.inference_mode():
            output = self._model(**inputs)
            probabilities = output.logits.softmax(dim=-1)[0].detach().cpu().tolist()

        labels = getattr(self._model.config, "id2label", {})
        scores = {str(labels.get(index, index)).lower(): float(score) for index, score in enumerate(probabilities)}
        normal = scores.get("normal")
        nsfw = scores.get("nsfw")
        if normal is None or nsfw is None:
            raise RuntimeError(f"Falconsai labels are missing normal/nsfw: {labels}")
        return ImageScores(normal=normal, nsfw=nsfw)
