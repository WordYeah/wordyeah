#!/usr/bin/env python3
"""Report a frozen quality corpus prelabel drain without changing SQLite."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_review.corpus_prelabel_progress import (  # noqa: E402
    audit_corpus_prelabel_progress,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--consumer-id", default="corpus-avatar")
    parser.add_argument("--batch-id", default="corpus-primary-v1")
    parser.add_argument(
        "--allow-human-truth",
        action="store_true",
        help="do not degrade once intentional human corpus labeling has started",
    )
    args = parser.parse_args()
    try:
        report = audit_corpus_prelabel_progress(
            args.database,
            consumer_id=args.consumer_id,
            batch_id=args.batch_id,
            expect_human_truth_untouched=not args.allow_human_truth,
        )
    except (KeyError, OSError, sqlite3.Error, ValueError) as exc:
        print(
            json.dumps(
                {"kind": "wordyeah_corpus_prelabel_progress", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"HEALTHY", "COMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
