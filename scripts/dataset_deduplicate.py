#!/usr/bin/env python3
"""Report exact and perceptual duplicate groups for a private image manifest."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_media.image_safety import ImageLimits, decode_image  # noqa: E402

from dataset_validate import _read_entries, _resolve_local_path, _validate_entry  # noqa: E402


def _average_hash(image_bytes: bytes) -> int:
    image = decode_image(image_bytes, ImageLimits())
    grayscale = ImageOps.grayscale(image).resize((16, 16), Image.Resampling.BILINEAR)
    if hasattr(grayscale, "get_flattened_data"):
        pixels = list(grayscale.get_flattened_data())
    else:  # pragma: no cover - compatibility with older Pillow releases
        pixels = list(grayscale.getdata())
    average = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= average)
    return value


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _perceptual_groups(items: list[tuple[str, int]], distance: int) -> list[dict[str, Any]]:
    groups: list[list[tuple[str, int]]] = []
    for sample_id, image_hash in items:
        matches = [
            index
            for index, group in enumerate(groups)
            if any(_hamming(image_hash, other) <= distance for _, other in group)
        ]
        if not matches:
            groups.append([(sample_id, image_hash)])
            continue
        first = matches[0]
        groups[first].append((sample_id, image_hash))
        for index in reversed(matches[1:]):
            groups[first].extend(groups.pop(index))
    return [
        {"sample_ids": [sample_id for sample_id, _ in group], "size": len(group)}
        for group in groups
        if len(group) > 1
    ]


def deduplicate_manifest(manifest: Path, root: Path | None, distance: int) -> dict[str, Any]:
    entries, parse_errors = _read_entries(manifest)
    errors = list(parse_errors)
    exact: dict[str, list[str]] = defaultdict(list)
    image_hashes: list[tuple[str, int]] = []
    for entry in entries:
        entry_errors = _validate_entry(entry)
        errors.extend(entry_errors)
        if entry_errors:
            continue
        sample_id = str(entry["sample_id"])
        exact[str(entry["content_sha256"])].append(sample_id)
        try:
            path = _resolve_local_path(entry, manifest, root)
            image_hashes.append((sample_id, _average_hash(path.read_bytes())))
        except (OSError, ValueError) as exc:
            errors.append(f"sample_{sample_id}: local_file_invalid={type(exc).__name__}")
    exact_groups = [
        {"content_sha256": digest, "sample_ids": sample_ids, "size": len(sample_ids)}
        for digest, sample_ids in sorted(exact.items())
        if len(sample_ids) > 1
    ]
    return {
        "kind": "wordyeah_dataset_deduplication",
        "manifest": manifest.name,
        "sample_count": len(entries),
        "exact_duplicate_groups": exact_groups,
        "perceptual_duplicate_groups": _perceptual_groups(image_hashes, distance),
        "perceptual_distance": distance,
        "error_count": len(errors),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Report WordYeah image duplicate groups")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--distance", type=int, default=12)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-exact", action="store_true")
    args = parser.parse_args()
    if args.distance < 0:
        parser.error("distance must be non-negative")
    report = deduplicate_manifest(args.manifest, args.root, args.distance)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report["error_count"]:
        return 2
    if args.fail_on_exact and report["exact_duplicate_groups"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
