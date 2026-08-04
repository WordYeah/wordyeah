#!/usr/bin/env python3
"""Collect a metadata-only Cavalcade export into a local shadow manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_cravatar.export import collect_export, read_export  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="JSONL from cravatar_cavalcade_export.php")
    parser.add_argument("--root", type=Path, required=True, help="controlled local image directory")
    parser.add_argument("--manifest", type=Path, required=True, help="atomic output manifest")
    args = parser.parse_args()
    try:
        report = collect_export(
            read_export(args.export), controlled_root=args.root, manifest_path=args.manifest
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps({"kind": "cravatar_shadow_collection", "error": str(exc)}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 2 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
