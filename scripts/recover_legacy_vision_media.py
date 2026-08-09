#!/usr/bin/env python3
"""Plan or apply recovery of queued vision jobs missing normalized media hashes."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_review.media_integrity_recovery import (  # noqa: E402
    MediaIntegrityRecoveryError,
    recover_legacy_vision_media_hashes,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--consumer-id", default="corpus-avatar")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="cancel legacy queued jobs and enqueue integrity-bound replacements",
    )
    args = parser.parse_args()
    try:
        report = recover_legacy_vision_media_hashes(
            database=args.database,
            media_root=args.media_root,
            consumer_id=args.consumer_id,
            apply=args.apply,
            limit=args.limit,
        )
    except (MediaIntegrityRecoveryError, OSError, sqlite3.Error, ValueError) as exc:
        print(
            json.dumps(
                {"kind": "wordyeah_legacy_vision_media_recovery", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
