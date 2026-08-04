#!/usr/bin/env python3
"""Freeze a deterministic stratified quality subset for two human reviewers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_review.quality_selection import (  # noqa: E402
    QualitySelectionError,
    freeze_dual_review_selection,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--consumer-id", default="corpus-avatar")
    parser.add_argument("--fraction", type=float, default=0.10)
    parser.add_argument("--seed", default="avatar-mvp-dual-review-v1")
    parser.add_argument("--batch-id", default="dual-review-10pct-v2")
    parser.add_argument("--primary-batch-id", default="corpus-primary-v1")
    args = parser.parse_args()
    try:
        report = freeze_dual_review_selection(
            database=args.database,
            output=args.output,
            consumer_id=args.consumer_id,
            fraction=args.fraction,
            seed=args.seed,
            batch_id=args.batch_id,
            primary_batch_id=args.primary_batch_id,
        )
    except (OSError, QualitySelectionError, ValueError) as exc:
        print(json.dumps({"kind": "wordyeah_dual_review_selection", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
