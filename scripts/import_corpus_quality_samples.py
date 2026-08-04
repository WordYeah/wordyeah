#!/usr/bin/env python3
"""Import controlled candidate manifests into the private quality-review inbox."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_review.corpus_quality_import import (  # noqa: E402
    CorpusQualityImportError,
    import_candidate_manifests,
)
from wy_review.quality import QualityConflictError  # noqa: E402


def _manifest(value: str) -> tuple[str, Path]:
    stratum, separator, raw_path = value.partition("=")
    if not separator or not raw_path:
        raise argparse.ArgumentTypeError("manifest must use STRATUM=PATH")
    return stratum, Path(raw_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy unreviewed corpus candidates into a private WordYeah quality inbox"
    )
    parser.add_argument("--manifest", action="append", type=_manifest, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--consumer-id", default="corpus-avatar")
    parser.add_argument("--vocabulary-version", default="v1")
    args = parser.parse_args()
    try:
        report = import_candidate_manifests(
            args.manifest,
            database=args.database,
            media_root=args.media_root,
            consumer_id=args.consumer_id,
            vocabulary_version=args.vocabulary_version,
        )
    except (CorpusQualityImportError, QualityConflictError, OSError, ValueError) as exc:
        print(
            json.dumps({"kind": "wordyeah_corpus_quality_import", "error": str(exc)}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
