#!/usr/bin/env python3
"""Create a private labelled image manifest from a controlled directory tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_media.image_safety import ImageLimits, decode_image  # noqa: E402


STYLES = {"real", "anime", "cartoon", "logo", "poster", "other"}
DECISIONS = {"allow", "review", "block"}
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _safe_id(dataset_name: str, relative: Path) -> str:
    digest = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:16]
    prefix = "".join(character if character.isalnum() else "-" for character in dataset_name)
    return f"{prefix or 'dataset'}-{digest}"


def _infer_labels(relative: Path, style: str | None, decision: str | None) -> tuple[str, str]:
    inferred_style = style or next((item for item in relative.parts if item in STYLES), None)
    inferred_decision = decision or next((item for item in relative.parts if item in DECISIONS), None)
    if inferred_style is None or inferred_decision is None:
        raise ValueError(
            f"cannot infer labels for {relative}; use --style/--decision or style/decision directories"
        )
    return inferred_style, inferred_decision


def import_manifest(
    input_root: Path,
    *,
    output: Path,
    dataset_name: str,
    source: str,
    license_name: str,
    split: str,
    style: str | None,
    decision: str | None,
    reviewer_count: int,
) -> dict[str, object]:
    if not input_root.is_dir():
        raise ValueError(f"input root does not exist or is not a directory: {input_root}")
    if not source.strip() or not license_name.strip():
        raise ValueError("source and license are required")
    if split not in {"train", "calibration", "test"}:
        raise ValueError("split must be train, calibration or test")
    if reviewer_count < 1:
        raise ValueError("reviewer-count must be positive")
    if style is not None and style not in STYLES:
        raise ValueError(f"invalid style: {style}")
    if decision is not None and decision not in DECISIONS:
        raise ValueError(f"invalid decision: {decision}")

    rows: list[dict[str, object]] = []
    for path in sorted(input_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        relative = path.relative_to(input_root)
        image_bytes = path.read_bytes()
        decode_image(image_bytes, ImageLimits())
        current_style, current_decision = _infer_labels(relative, style, decision)
        digest = hashlib.sha256(image_bytes).hexdigest()
        rows.append(
            {
                "sample_id": _safe_id(dataset_name, relative),
                "content_sha256": digest,
                "local_ref": f"dataset://{dataset_name}/{relative.as_posix()}",
                "media_type": "image",
                "style": current_style,
                "expected_decision": current_decision,
                "categories": [],
                "source": source,
                "license": license_name,
                "reviewer_count": reviewer_count,
                "split": split,
                "duplicate_group": digest,
                "path": str(path.resolve()),
            }
        )
    if not rows:
        raise ValueError("no supported image files found")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "kind": "wordyeah_dataset_import",
        "dataset_name": dataset_name,
        "sample_count": len(rows),
        "output": output.name,
        "source": source,
        "license": license_name,
        "split": split,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a private WordYeah image manifest")
    parser.add_argument("input_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-name", default="avatars")
    parser.add_argument("--source", required=True)
    parser.add_argument("--license", dest="license_name", required=True)
    parser.add_argument("--split", default="calibration")
    parser.add_argument("--style", choices=sorted(STYLES))
    parser.add_argument("--decision", choices=sorted(DECISIONS))
    parser.add_argument("--reviewer-count", type=int, default=1)
    args = parser.parse_args()
    try:
        report = import_manifest(
            args.input_root,
            output=args.output,
            dataset_name=args.dataset_name,
            source=args.source,
            license_name=args.license_name,
            split=args.split,
            style=args.style,
            decision=args.decision,
            reviewer_count=args.reviewer_count,
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"kind": "wordyeah_dataset_import", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
