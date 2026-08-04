#!/usr/bin/env python3
"""Run deterministic WordYeah avatar fault drills and write JSON evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_review.fault_drills import run_fault_drills  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="temporary drill database")
    parser.add_argument("--output", type=Path, help="atomic JSON evidence output")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="wordyeah-fault-drill-") as directory:
        database = args.database or Path(directory) / "fault-drills.sqlite3"
        report = run_fault_drills(database)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        _atomic_write(args.output, rendered)
    else:
        print(rendered, end="")
    return 0 if report["status"] == "PASS" else 2


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(temporary).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
