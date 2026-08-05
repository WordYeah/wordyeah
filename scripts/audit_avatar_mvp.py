#!/usr/bin/env python3
"""Aggregate WordYeah avatar MVP evidence into PASS/INCOMPLETE/FAIL."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_review.mvp_acceptance import audit_avatar_mvp  # noqa: E402


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=ROOT / "artifacts/avatar-corpus-evaluation-mvp.json",
    )
    parser.add_argument(
        "--queue-load",
        type=Path,
        default=ROOT / "artifacts/review-queue-load-15m.json",
    )
    parser.add_argument(
        "--fault-drills",
        type=Path,
        default=ROOT / "artifacts/avatar-fault-drills-mvp.json",
    )
    parser.add_argument(
        "--browser",
        type=Path,
        default=ROOT / "artifacts/browser-acceptance-mvp.json",
    )
    parser.add_argument(
        "--reviewer-runtime",
        type=Path,
        default=ROOT / "artifacts/reviewer-runtime-acceptance-mvp.json",
    )
    parser.add_argument(
        "--shadow",
        type=Path,
        default=ROOT / "artifacts/cravatar-shadow-acceptance-mvp.json",
    )
    parser.add_argument(
        "--vision-canary",
        type=Path,
        default=ROOT / "artifacts/vision-canary-acceptance-mvp.json",
    )
    parser.add_argument("--shadow-minimum", type=positive_integer, default=1100)
    parser.add_argument("--enforce", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_avatar_mvp(
        corpus=args.corpus,
        queue_load=args.queue_load,
        fault_drills=args.fault_drills,
        browser=args.browser,
        reviewer_runtime=args.reviewer_runtime,
        shadow=args.shadow,
        vision_canary=args.vision_canary,
        shadow_minimum=args.shadow_minimum,
        enforce=args.enforce,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        _atomic_write(args.output, rendered)
    else:
        print(rendered, end="")
    return {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}[str(report["status"])]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(temporary).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
