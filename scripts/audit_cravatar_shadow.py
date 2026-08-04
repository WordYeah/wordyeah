#!/usr/bin/env python3
"""Build tamper-evident Cravatar shadow acceptance evidence from real run artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _jsonl(path: Path) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{path} must contain JSON objects")
    return rows


def _elapsed(path: Path) -> float:
    match = re.search(r"^real\s+([0-9]+(?:\.[0-9]+)?)$", path.read_text(), re.MULTILINE)
    if match is None:
        raise ValueError(f"{path} has no time(1) real duration")
    return float(match.group(1))


def _fingerprint(rows: list[dict[str, object]]) -> str:
    payload = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    return hashlib.sha256(payload.encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--first-run", type=Path, required=True)
    parser.add_argument("--second-run", type=Path, required=True)
    parser.add_argument("--pause", type=Path, required=True)
    parser.add_argument("--pause-time", type=Path, required=True)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--minimum", type=int, default=1100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        before_rows = _jsonl(args.before)
        after_rows = _jsonl(args.after)
        manifest = _jsonl(args.manifest)
        first = _json(args.first_run)
        second = _json(args.second_run)
        pause = _json(args.pause)
        collection = _json(args.collection)
        pause_seconds = _elapsed(args.pause_time)

        before = {str(row["source_id"]): row for row in before_rows}
        after = {str(row["source_id"]): row for row in after_rows}
        source_ids = [str(row["source_id"]) for row in manifest]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("manifest source_id values must be unique")
        if any(row.get("mutates_avatar") is not False for row in manifest):
            raise ValueError("manifest must remain non-mutating")

        unchanged = all(source_id in before and before[source_id] == after.get(source_id) for source_id in source_ids)
        first_watermark = first.get("watermark")
        second_watermark = second.get("watermark")
        pause_watermark = pause.get("watermark")
        if not all(isinstance(item, dict) for item in (first_watermark, second_watermark, pause_watermark)):
            raise ValueError("run evidence is missing a watermark")

        source_count = int(first_watermark["source_count"])
        failed_count = int(first_watermark["failed_count"])
        completed_count = int(first_watermark["completed_count"])
        first_outcomes = first.get("outcomes", [])
        submitted_ids = {
            str(item.get("source_id"))
            for item in first_outcomes
            if isinstance(item, dict) and item.get("status") == "submitted"
        }
        stable_rerun = (
            source_count == int(second_watermark["source_count"])
            and completed_count == int(second_watermark["completed_count"])
            and int(second_watermark["failed_count"]) == 0
            and len(second.get("outcomes", [])) == 0
        )
        passed = (
            source_count >= args.minimum
            and source_count == len(manifest)
            and completed_count == source_count
            and failed_count == 0
            and len(first_outcomes) == source_count
            and submitted_ids == set(source_ids)
            and stable_rerun
            and unchanged
            and pause_watermark.get("paused") is True
            and pause_seconds <= 60
            and first_watermark.get("mutates_avatar") is False
            and second_watermark.get("mutates_avatar") is False
            and pause_watermark.get("mutates_avatar") is False
            and collection.get("mutates_avatar") is False
            and int(collection.get("exported", 0)) >= source_count
        )
        evidence = {
            "kind": "cravatar_shadow_acceptance",
            "status": "PASS" if passed else "FAIL",
            "source_count": source_count,
            "completed_count": completed_count,
            "failed_count": failed_count,
            "stable_rerun": stable_rerun,
            "production_state_unchanged": unchanged,
            "unchanged_production_rows": sum(
                source_id in before and before[source_id] == after.get(source_id)
                for source_id in source_ids
            ),
            "feature_flag_stop_seconds": pause_seconds,
            "mutates_avatar": False,
            "collection_exported": int(collection.get("exported", 0)),
            "collection_failed": int(collection.get("failed", 0)),
            "selected_manifest_sha256": _fingerprint(manifest),
            "before_selected_sha256": _fingerprint([before[source_id] for source_id in source_ids if source_id in before]),
            "after_selected_sha256": _fingerprint([after[source_id] for source_id in source_ids if source_id in after]),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
        args.output.chmod(0o600)
        print(json.dumps(evidence, ensure_ascii=False))
        return 0 if passed else 1
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"kind": "cravatar_shadow_acceptance", "status": "FAIL", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
