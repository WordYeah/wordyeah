#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from wy_review.quality_evaluation import evaluate_quality_database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a frozen WordYeah quality batch without modifying labels"
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--consumer-id", required=True)
    parser.add_argument("--batch-id", default="corpus-primary-v1")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate_quality_database(
        args.database, consumer_id=args.consumer_id, batch_id=args.batch_id
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 3 if report["status"] == "INCOMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
