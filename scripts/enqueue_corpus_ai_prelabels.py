#!/usr/bin/env python3
"""Safely enqueue AI proposals for private corpus samples."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_review.corpus_ai_prelabels import (  # noqa: E402
    CorpusPrelabelError,
    enqueue_corpus_ai_prelabels,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--policy", type=Path, default=ROOT / "config/policy.avatar.example.json"
    )
    parser.add_argument("--consumer-id", default="corpus-avatar")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-active-jobs", type=int, default=2000)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write review items and vision jobs; omitted means read-only dry-run",
    )
    args = parser.parse_args()
    try:
        report = enqueue_corpus_ai_prelabels(
            database=args.database,
            policy_path=args.policy,
            consumer_id=args.consumer_id,
            limit=args.limit,
            apply=args.apply,
            max_active_jobs=args.max_active_jobs,
        )
    except (CorpusPrelabelError, OSError, sqlite3.Error, ValueError) as exc:
        print(
            json.dumps(
                {"kind": "wordyeah_corpus_ai_prelabels", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
