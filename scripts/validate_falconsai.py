#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_media.falconsai import FalconsaiClassifier  # noqa: E402
from wy_media.service import MediaModerationService  # noqa: E402


def make_smoke_images(directory: Path) -> list[tuple[str, Path]]:
    directory.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, Path]] = []

    safe = Image.new("RGB", (256, 256), (70, 120, 180))
    safe_draw = ImageDraw.Draw(safe)
    safe_draw.rectangle((32, 32, 224, 224), outline="white", width=4)
    safe_draw.text((64, 118), "SAFE CANARY", fill="white")
    safe_path = directory / "safe-canary.png"
    safe.save(safe_path)
    cases.append(("synthetic_safe", safe_path))

    poster = Image.new("RGB", (512, 256), "white")
    poster_draw = ImageDraw.Draw(poster)
    poster_draw.rectangle((20, 20, 492, 236), outline=(30, 30, 30), width=5)
    poster_draw.text((90, 105), "ELECTION PRESIDENT", fill=(20, 20, 20))
    poster_path = directory / "synthetic_text-poster.png"
    poster.save(poster_path)
    cases.append(("synthetic_text_poster", poster_path))
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Falconsai WordYeah smoke validation")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "falconsai-smoke.json")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--model-path", default=None)
    args = parser.parse_args()

    fixture_dir = args.output.parent / "fixtures"
    cases = make_smoke_images(fixture_dir)
    classifier = FalconsaiClassifier(model_path=args.model_path, device=args.device)
    service = MediaModerationService(classifier)
    results = []
    for label, image_path in cases:
        result = service.moderate_image(image_path.read_bytes())
        results.append({"case": label, "path": str(image_path), **result.to_dict()})

    payload = {
        "kind": "smoke_only",
        "model": classifier.model_version,
        "device": classifier.device_name,
        "external_model_calls": False,
        "limitations": [
            "synthetic fixtures are pipeline smoke tests, not production accuracy evidence",
            "thresholds are uncalibrated and must not enable enforcement",
        ],
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
