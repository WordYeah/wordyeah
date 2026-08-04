#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
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

    rng = random.Random(42)
    for index in range(12):
        canvas = Image.new("RGB", (256, 256), (235, 238, 242))
        draw = ImageDraw.Draw(canvas)
        skin = [(244, 204, 170), (224, 170, 132), (190, 125, 85)][index % 3]
        hair = [(35, 35, 42), (95, 55, 30), (210, 180, 60)][index % 3]
        shirt = (60 + index * 11 % 130, 80 + index * 7 % 100, 140 + index * 5 % 80)
        cx = 128 + rng.randint(-5, 5)
        draw.ellipse((cx - 62, 35, cx + 62, 159), fill=skin, outline=(80, 80, 80), width=2)
        draw.pieslice((cx - 66, 24, cx + 66, 110), 180, 360, fill=hair)
        draw.ellipse((cx - 30, 82, cx - 18, 94), fill=(35, 35, 35))
        draw.ellipse((cx + 18, 82, cx + 30, 94), fill=(35, 35, 35))
        draw.arc((cx - 25, 100, cx + 25, 135), 10, 170, fill=(100, 40, 40), width=2)
        draw.ellipse((cx - 86, 142, cx + 86, 300), fill=shirt, outline=(80, 80, 80), width=2)
        avatar_path = directory / f"synthetic-avatar-{index:02d}.png"
        canvas.save(avatar_path)
        cases.append(("synthetic_safe_avatar", avatar_path))
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
        results.append(
            {
                "case": label,
                "path": str(image_path),
                "expected_decision": "allow",
                **result.to_dict(),
            }
        )

    scores = [result["top_score"] for result in results if result["top_score"] is not None]
    flagged = [result for result in results if result["decision"] in {"review", "block"}]

    payload = {
        "kind": "smoke_only",
        "model": classifier.model_version,
        "device": classifier.device_name,
        "external_model_calls": False,
        "limitations": [
            "synthetic fixtures are pipeline smoke tests, not production accuracy evidence",
            "avatar-like fixtures are generated shapes, not real user avatars",
            "thresholds are uncalibrated and must not enable enforcement",
        ],
        "summary": {
            "case_count": len(results),
            "max_nsfw_score": max(scores) if scores else None,
            "review_or_block_count": len(flagged),
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    manifest_path = args.output.with_name("falconsai-smoke-manifest.jsonl")
    manifest_path.write_text(
        "".join(
            json.dumps(
                {"path": result["path"], "expected_decision": result["expected_decision"]},
                ensure_ascii=False,
            )
            + "\n"
            for result in results
        )
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
