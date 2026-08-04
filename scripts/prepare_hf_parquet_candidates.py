#!/usr/bin/env python3
"""Prepare unreviewed avatar candidates from local Hugging Face Parquet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_review.corpus_candidates import (  # noqa: E402
    CandidateSourceError,
    collect_huggingface_parquet_candidates,
)


def bounded_count(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 5000:
        raise argparse.ArgumentTypeError("must be between 1 and 5000")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parquet", type=Path)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--candidate-set", required=True)
    parser.add_argument("--label", type=int, action="append", required=True)
    parser.add_argument("--count", type=bounded_count, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--license", dest="license_name", required=True)
    parser.add_argument("--style-candidate", required=True)
    parser.add_argument("--decision-candidate", required=True)
    args = parser.parse_args()
    try:
        report = collect_huggingface_parquet_candidates(
            parquet=args.parquet,
            dataset=args.dataset,
            candidate_set=args.candidate_set,
            labels=set(args.label),
            count=args.count,
            output_root=args.output_root,
            source_url=args.source_url,
            license_name=args.license_name,
            style_candidate=args.style_candidate,
            decision_candidate=args.decision_candidate,
        )
    except (CandidateSourceError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"kind": "wordyeah_huggingface_corpus_candidates", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "READY_FOR_REVIEW" else 3


if __name__ == "__main__":
    raise SystemExit(main())
