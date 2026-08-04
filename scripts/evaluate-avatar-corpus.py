#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from wy_review.evaluation import evaluate_corpus, load_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate an avatar moderation JSONL corpus")
    parser.add_argument("corpus", help="JSONL corpus containing expected and predicted decisions")
    parser.add_argument("--output", help="optional path for the JSON report")
    args = parser.parse_args()
    report = evaluate_corpus(load_jsonl(args.corpus))
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
