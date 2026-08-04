#!/usr/bin/env python3
"""Validate a private WordYeah image manifest without exposing local paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_media.image_safety import ImageLimits, decode_image  # noqa: E402


DECISIONS = {"allow", "review", "block"}
STYLES = {"real", "anime", "cartoon", "logo", "poster", "other"}
SPLITS = {"train", "calibration", "test"}
CATEGORIES = {
    "sexual_explicit",
    "sexual_suggestive",
    "violence_gore",
    "hate_symbol",
    "sensitive_term",
    "political_person",
    "political_symbol",
    "political_text",
    "ocr_text",
    "model_disagreement",
    "invalid_media",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ManifestError(ValueError):
    pass


def _read_entries(manifest: Path) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"manifest_read: {exc}"]
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            errors.append(f"line_{line_number}: invalid_json: {exc.msg}")
            continue
        if not isinstance(value, dict):
            errors.append(f"line_{line_number}: entry_must_be_object")
            continue
        value["_line_number"] = line_number
        entries.append(value)
    return entries, errors


def _entry_location(entry: dict[str, Any]) -> str:
    return f"line_{entry.get('_line_number', '?')}/sample_{entry.get('sample_id', '?')}"


def _resolve_local_path(entry: dict[str, Any], manifest: Path, root: Path | None) -> Path:
    path_value = entry.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        local_ref = entry.get("local_ref")
        if not isinstance(local_ref, str) or not local_ref.startswith("dataset://"):
            raise ManifestError("missing_local_path")
        path_value = local_ref.removeprefix("dataset://")
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = (root or manifest.parent) / candidate
    resolved = candidate.resolve()
    if root is not None:
        root_resolved = root.expanduser().resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise ManifestError("path_outside_root") from exc
    return resolved


def _validate_entry(entry: dict[str, Any]) -> list[str]:
    location = _entry_location(entry)
    errors: list[str] = []
    required = {
        "sample_id",
        "content_sha256",
        "local_ref",
        "media_type",
        "style",
        "expected_decision",
        "categories",
        "source",
        "license",
        "reviewer_count",
        "split",
        "duplicate_group",
    }
    allowed = required | {"path", "_line_number"}
    unknown = sorted(set(entry) - allowed)
    missing = sorted(required - set(entry))
    if unknown:
        errors.append(f"{location}: unknown_fields={','.join(unknown)}")
    if missing:
        errors.append(f"{location}: missing_fields={','.join(missing)}")
        return errors

    sample_id = entry["sample_id"]
    if not isinstance(sample_id, str) or not SAMPLE_ID_RE.fullmatch(sample_id):
        errors.append(f"{location}: invalid_sample_id")
    digest = entry["content_sha256"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        errors.append(f"{location}: content_sha256_must_be_lowercase_sha256")
    local_ref = entry["local_ref"]
    local_ref_parts = local_ref.removeprefix("dataset://").split("/") if isinstance(local_ref, str) else []
    if (
        not isinstance(local_ref, str)
        or not local_ref.startswith("dataset://")
        or local_ref.startswith("dataset:///")
        or any(part in {"", ".", ".."} for part in local_ref_parts)
    ):
        errors.append(f"{location}: local_ref_must_use_dataset_scheme")
    if entry["media_type"] != "image":
        errors.append(f"{location}: media_type_must_be_image")
    if entry["style"] not in STYLES:
        errors.append(f"{location}: invalid_style")
    if entry["expected_decision"] not in DECISIONS:
        errors.append(f"{location}: invalid_expected_decision")
    categories = entry["categories"]
    if not isinstance(categories, list) or any(
        not isinstance(category, str) or category not in CATEGORIES for category in categories
    ):
        errors.append(f"{location}: invalid_categories")
    elif len(categories) != len(set(categories)):
        errors.append(f"{location}: duplicate_categories")
    if not isinstance(entry["source"], str) or not entry["source"].strip():
        errors.append(f"{location}: source_required")
    if not isinstance(entry["license"], str) or not entry["license"].strip():
        errors.append(f"{location}: license_required")
    if (
        not isinstance(entry["reviewer_count"], int)
        or isinstance(entry["reviewer_count"], bool)
        or entry["reviewer_count"] < 1
    ):
        errors.append(f"{location}: reviewer_count_must_be_positive_integer")
    if entry["split"] not in SPLITS:
        errors.append(f"{location}: invalid_split")
    duplicate_group = entry["duplicate_group"]
    if not isinstance(duplicate_group, str) or not duplicate_group.strip():
        errors.append(f"{location}: duplicate_group_required")
    return errors


def _acceptance_gates(entries: list[dict[str, Any]]) -> dict[str, Any]:
    def count(predicate: Any) -> int:
        return sum(1 for entry in entries if predicate(entry))

    gates = {
        "real_allow": (count(lambda item: item["style"] == "real" and item["expected_decision"] == "allow"), 300),
        "anime_or_cartoon_allow": (
            count(
                lambda item: item["style"] in {"anime", "cartoon"}
                and item["expected_decision"] == "allow"
            ),
            300,
        ),
        "logo_or_poster_allow": (
            count(
                lambda item: item["style"] in {"logo", "poster"}
                and item["expected_decision"] == "allow"
            ),
            100,
        ),
        "boundary_review": (count(lambda item: item["expected_decision"] == "review"), 200),
        "explicit_block": (count(lambda item: item["expected_decision"] == "block"), 200),
    }
    rendered: dict[str, Any] = {}
    complete = True
    for name, (observed, minimum) in gates.items():
        if observed == 0:
            status = "SKIP_NO_SAMPLES"
            complete = False
        elif observed < minimum:
            status = "INCOMPLETE"
            complete = False
        else:
            status = "MEASURED"
        rendered[name] = {"count": observed, "minimum": minimum, "status": status}
    return {"status": "MEASURED" if complete else "INCOMPLETE_OR_SKIPPED", "gates": rendered}


def validate_manifest(
    manifest: Path,
    *,
    root: Path | None = None,
    check_files: bool = False,
    require_acceptance: bool = False,
) -> tuple[dict[str, Any], int]:
    entries, errors = _read_entries(manifest)
    seen_ids: set[str] = set()
    seen_refs: set[str] = set()
    seen_hashes: dict[str, str] = {}
    duplicate_splits: dict[str, set[str]] = defaultdict(set)
    counts: Counter[str] = Counter()

    for entry in entries:
        errors.extend(_validate_entry(entry))
        location = _entry_location(entry)
        sample_id = entry.get("sample_id")
        local_ref = entry.get("local_ref")
        digest = entry.get("content_sha256")
        if isinstance(sample_id, str):
            if sample_id in seen_ids:
                errors.append(f"{location}: duplicate_sample_id")
            seen_ids.add(sample_id)
        if isinstance(local_ref, str):
            if local_ref in seen_refs:
                errors.append(f"{location}: duplicate_local_ref")
            seen_refs.add(local_ref)
        if isinstance(digest, str) and SHA256_RE.fullmatch(digest):
            previous = seen_hashes.get(digest)
            if previous is not None:
                errors.append(f"{location}: duplicate_content_sha256_with_{previous}")
            else:
                seen_hashes[digest] = location
        group = entry.get("duplicate_group")
        split = entry.get("split")
        if isinstance(group, str) and isinstance(split, str):
            duplicate_splits[group].add(split)
        if entry.get("style") in STYLES and entry.get("expected_decision") in DECISIONS:
            counts[f"style:{entry['style']}"] += 1
            counts[f"decision:{entry['expected_decision']}"] += 1

        if check_files and not _validate_entry(entry):
            try:
                path = _resolve_local_path(entry, manifest, root)
                data = path.read_bytes()
                actual_digest = hashlib.sha256(data).hexdigest()
                if actual_digest != digest:
                    errors.append(f"{location}: content_sha256_mismatch")
                decode_image(data, ImageLimits())
            except FileNotFoundError:
                errors.append(f"{location}: local_file_missing")
            except (OSError, ManifestError, ValueError) as exc:
                errors.append(f"{location}: local_file_invalid={type(exc).__name__}")

    for group, splits in sorted(duplicate_splits.items()):
        if len(splits) > 1:
            errors.append(f"duplicate_group_crosses_splits:{group}")

    acceptance = _acceptance_gates(
        [
            entry
            for entry in entries
            if not _validate_entry(entry)
            and entry.get("style") in STYLES
            and entry.get("expected_decision") in DECISIONS
        ]
    )
    report = {
        "kind": "wordyeah_dataset_validation",
        "manifest": manifest.name,
        "sample_count": len(entries),
        "counts": dict(sorted(counts.items())),
        "acceptance": acceptance,
        "check_files": check_files,
        "error_count": len(errors),
        "errors": errors,
    }
    if errors:
        return report, 2
    if require_acceptance and acceptance["status"] != "MEASURED":
        return report, 3
    return report, 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a private WordYeah image manifest")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, default=None, help="Root allowed for local file checks")
    parser.add_argument("--check-files", action="store_true")
    parser.add_argument("--require-acceptance", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report, exit_code = validate_manifest(
        args.manifest,
        root=args.root,
        check_files=args.check_files,
        require_acceptance=args.require_acceptance,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
