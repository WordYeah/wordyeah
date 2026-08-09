#!/usr/bin/env python3
"""Collect one read-only registry export page into the local snapshot ledger."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_cravatar.registry import (  # noqa: E402
    RegistryLedger,
    collect_registry_export,
    read_registry_export,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--database", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--source-mode", choices=("replica", "live_keyset"), default="live_keyset")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    try:
        page = read_registry_export(args.export)
        ledger = RegistryLedger(args.database)
        ledger.begin_snapshot(args.snapshot_id, source_mode=args.source_mode)
        before = ledger.ingest_page(args.snapshot_id, page)
        retryable = ledger.retryable_source_ids(args.snapshot_id)
        collection = collect_registry_export(
            (record for record in page.records if record.source_id in retryable),
            controlled_root=args.root,
            manifest_path=args.manifest,
            workers=args.workers,
            snapshot_id=args.snapshot_id,
        )
        after = ledger.apply_manifest(args.snapshot_id, args.manifest, args.root)
        ledger.mark_failures(args.snapshot_id, collection["failures"])
        after = ledger.summary(args.snapshot_id)
        print(
            json.dumps(
                {
                    "kind": "cravatar_registry_page",
                    "snapshot_id": args.snapshot_id,
                    "source_count": page.source_count,
                    "last_key": page.last_key,
                    "invalid_metadata": len(page.invalid_records),
                    "ledger_before_collection": before,
                    "ledger_after_collection": after,
                    "collection": collection,
                    "production_write": False,
                    "mutates_avatar": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2 if collection["failed"] else 0
    except (OSError, TypeError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"kind": "cravatar_registry_page", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
