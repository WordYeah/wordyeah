#!/usr/bin/env python3
"""Normalize a controlled local Cravatar backlog into shadow-only JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_cravatar.backlog import import_cravatar_backlog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and normalize a local Cravatar CSV/JSON/JSONL backlog"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, required=True, help="controlled local image root")
    parser.add_argument("--output", type=Path, help="normalized JSONL; stdout when omitted")
    args = parser.parse_args()

    try:
        backlog = import_cravatar_backlog(args.manifest, controlled_root=args.root)
        normalized = backlog.to_jsonl()
        if args.output:
            if args.output.resolve() == args.manifest.resolve():
                raise ValueError("output must not overwrite the input manifest")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(normalized, encoding="utf-8")
            args.output.chmod(0o600)
        else:
            sys.stdout.write(normalized)
    except (OSError, ValueError) as exc:
        print(json.dumps({"kind": "cravatar_backlog_import", "error": str(exc)}), file=sys.stderr)
        return 2

    report = {
        "kind": "cravatar_backlog_import",
        "source_count": backlog.source_count,
        "record_count": len(backlog.records),
        "duplicate_count": backlog.duplicate_count,
        "mutates_avatar": False,
        "output": str(args.output) if args.output else "stdout",
    }
    print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
