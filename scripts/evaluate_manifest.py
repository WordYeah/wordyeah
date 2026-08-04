#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_core.metrics import evaluate_decisions  # noqa: E402
from wy_media.falconsai import FalconsaiClassifier  # noqa: E402
from wy_media.service import MediaModerationService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a labelled WordYeah media manifest")
    parser.add_argument("manifest", type=Path, help="JSONL with path and expected_decision fields")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--model-path", default=None)
    args = parser.parse_args()

    entries = [
        json.loads(line)
        for line in args.manifest.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    classifier = FalconsaiClassifier(model_path=args.model_path, device=args.device)
    service = MediaModerationService(classifier)
    results = []
    expected = []
    observed = []
    for entry in entries:
        image_path = Path(entry["path"])
        if not image_path.is_absolute():
            image_path = args.manifest.parent / image_path
        result = service.moderate_image(image_path.read_bytes())
        expected.append(entry["expected_decision"])
        observed.append(result.decision)
        results.append({"path": str(image_path), **result.to_dict()})

    report = {
        "kind": "labelled_media_evaluation",
        "model": classifier.model_version,
        "device": classifier.device_name,
        "sample_count": len(results),
        "metrics": evaluate_decisions(expected, observed).to_dict(),
        "results": results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
