#!/usr/bin/env python3
"""Run one real advanced-vision request and emit secret-free acceptance evidence."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_media.failover import build_primary_vision_provider  # noqa: E402
from wy_media.g2a import G2AConfig, G2AVisionProvider  # noqa: E402
from wy_media.vision_provider import VisionProviderError, VisionReviewRequest  # noqa: E402


def _media_type(payload: bytes) -> str:
    with Image.open(io.BytesIO(payload)) as image:
        value = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
            "GIF": "image/gif",
            "BMP": "image/bmp",
        }.get(image.format)
        image.verify()
    if value is None:
        raise ValueError("unsupported canary image format")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--with-fallback",
        action="store_true",
        help="exercise the configured G2A-to-Ollama primary chain instead of G2A alone",
    )
    args = parser.parse_args()
    try:
        payload = args.image.read_bytes()
        if args.with_fallback:
            provider = build_primary_vision_provider()
        else:
            config = G2AConfig.from_env()
            provider = G2AVisionProvider(config)
        started = time.monotonic()
        conclusion = provider.review(
            VisionReviewRequest(
                image_bytes=payload,
                media_type=_media_type(payload),
                request_id=f"wordyeah-canary-{hashlib.sha256(payload).hexdigest()[:16]}",
                categories=(
                    "sexual_explicit",
                    "sexual_suggestive",
                    "violence_gore",
                    "hate_extremism",
                    "political_public_figure",
                    "logo_text",
                ),
                context="Synthetic acceptance canary; do not infer identity.",
            )
        )
        evidence = {
            "kind": "advanced_vision_canary",
            "status": "PASS",
            "actual_provider_response": True,
            "image_count": 1,
            "image_sha256": hashlib.sha256(payload).hexdigest(),
            "provider": conclusion.provider,
            "configured_provider": provider.provider_name,
            "model_id": conclusion.model_id,
            "prompt_version": conclusion.prompt_version,
            "decision": conclusion.decision,
            "confidence": conclusion.confidence,
            "reason_count": len(conclusion.reasons),
            "finding_count": len(conclusion.findings),
            "evidence_count": len(conclusion.evidence),
            "fallback_used": any(
                item.kind == "provider_failover" for item in conclusion.evidence
            ),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        code = 0
    except (OSError, ValueError, VisionProviderError) as exc:
        evidence = {
            "kind": "advanced_vision_canary",
            "status": "FAIL",
            "actual_provider_response": False,
            "image_count": 1 if args.image.is_file() else 0,
            "error_kind": exc.kind.value if isinstance(exc, VisionProviderError) else type(exc).__name__,
            "retryable": exc.retryable if isinstance(exc, VisionProviderError) else False,
            "error": str(exc),
        }
        if isinstance(exc, VisionProviderError):
            if exc.status_code is not None:
                evidence["status_code"] = exc.status_code
            if exc.retry_after_seconds is not None:
                evidence["retry_after_seconds"] = exc.retry_after_seconds
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    args.output.chmod(0o600)
    print(json.dumps(evidence, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
