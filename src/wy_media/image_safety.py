from __future__ import annotations

import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


@dataclass(frozen=True)
class ImageLimits:
    """Resource limits applied before image pixels are decoded."""

    max_bytes: int = 10 * 1024 * 1024
    max_width: int = 4096
    max_height: int = 4096
    max_pixels: int = 16_777_216
    max_frames: int = 1

    def __post_init__(self) -> None:
        if any(value < 1 for value in (self.max_bytes, self.max_width, self.max_height, self.max_pixels)):
            raise ValueError("image limits must be positive")
        if self.max_frames < 1:
            raise ValueError("max_frames must be positive")


ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF", "BMP"})


def decode_image(image_bytes: bytes, limits: ImageLimits | None = None) -> Image.Image:
    """Decode one safe, bounded, non-animated RGB image for model inference."""

    limits = limits or ImageLimits()
    if not image_bytes:
        raise ValueError("image payload is empty")
    if len(image_bytes) > limits.max_bytes:
        raise ValueError("image payload exceeds configured byte limit")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(image_bytes))
            if image.format not in ALLOWED_FORMATS:
                raise ValueError(f"unsupported decoded image format: {image.format}")
            width, height = image.size
            if width < 1 or height < 1:
                raise ValueError("image has invalid dimensions")
            if width > limits.max_width or height > limits.max_height:
                raise ValueError("image dimensions exceed configured limit")
            if width * height > limits.max_pixels:
                raise ValueError("image pixel count exceeds configured limit")
            frames = int(getattr(image, "n_frames", 1))
            if frames > limits.max_frames:
                raise ValueError("animated images are not supported for avatar review")
            image.load()
            return ImageOps.exif_transpose(image).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("image decompression resource limit exceeded") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("image payload could not be decoded") from exc
