#!/usr/bin/env python3
"""Run browser acceptance against a disposable read-only backup of reviewer data."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Mapping

import uvicorn
from wy_api.app import ApiSettings, create_app
from wy_media.falconsai import ImageScores
from wy_media.service import MediaModerationService

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_browser_acceptance import _atomic_write, _load_runtime  # noqa: E402


class _FixtureClassifier:
    """Keep browser acceptance independent from model/network availability."""

    model_version = "browser-fixture/no-external-model"
    ready = True

    def warmup(self) -> None:
        return

    def classify(self, image_bytes: bytes) -> ImageScores:
        return ImageScores(normal=1.0, nsfw=0.0)


def _regular_file(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = expanded.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    return resolved


def _review_state(connection: sqlite3.Connection, item_id: str) -> dict[str, object]:
    row = connection.execute(
        """SELECT status, stage, final_decision, avatar_action, reviewer, review_note,
                  reviewed_at, quality_sample, arbitration_required, version
           FROM review_items WHERE item_id = ?""",
        (item_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("fixture review item disappeared")
    tables = {
        str(item[0])
        for item in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    return {
        "item": list(row),
        "review_events": int(
            connection.execute(
                "SELECT COUNT(*) FROM review_events WHERE item_id = ?", (item_id,)
            ).fetchone()[0]
        ),
        "quality_decisions": int(
            connection.execute("SELECT COUNT(*) FROM quality_decisions").fetchone()[0]
        )
        if "quality_decisions" in tables
        else 0,
    }


def _clone_and_stage_fixture(
    source_database: Path,
    fixture_database: Path,
    *,
    consumer_id: str,
) -> tuple[str, dict[str, object]]:
    """Backup a query-only source and stage one human item only in the copy."""

    source = _regular_file(source_database, label="source database")
    fixture_database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fixture_database.parent.chmod(0o700)
    source_uri = f"{source.as_uri()}?mode=ro"
    source_connection = sqlite3.connect(source_uri, uri=True, timeout=5.0)
    source_connection.execute("PRAGMA query_only = ON")
    try:
        row = source_connection.execute(
            """SELECT item_id FROM review_items
               WHERE consumer_id = ?
               ORDER BY quality_sample ASC, created_at DESC, item_id DESC
               LIMIT 1""",
            (consumer_id,),
        ).fetchone()
        if row is None:
            raise ValueError("source database has no review item for the selected consumer")
        item_id = str(row[0])
        fixture_connection = sqlite3.connect(fixture_database)
        try:
            source_connection.backup(fixture_connection)
        finally:
            fixture_connection.close()
    finally:
        source_connection.close()

    fixture_database.chmod(0o600)
    connection = sqlite3.connect(fixture_database)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        updated = connection.execute(
            """UPDATE review_items
               SET status = 'pending', stage = 'human_required', final_decision = NULL,
                   avatar_action = NULL, reviewer = NULL, review_note = NULL,
                   reviewed_at = NULL, quality_sample = 0, arbitration_required = 0,
                   appealed = 0, assignee = NULL, claim_until = NULL, due_at = NULL,
                   version = version + 1, updated_at = CURRENT_TIMESTAMP
               WHERE item_id = ? AND consumer_id = ?""",
            (item_id, consumer_id),
        )
        if updated.rowcount != 1:
            raise RuntimeError("failed to stage isolated human review item")
        connection.commit()
        staged_state = _review_state(connection, item_id)
    finally:
        connection.close()
    return item_id, staged_state


def _clean_subprocess_environment() -> dict[str, str]:
    allowed = ("HOME", "LANG", "LC_ALL", "PATH", "PYTHONPATH", "TMPDIR")
    return {key: os.environ[key] for key in allowed if key in os.environ}


def _wait_for_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if server.started:
            return
        if not thread.is_alive():
            raise RuntimeError("isolated reviewer server stopped during startup")
        time.sleep(0.05)
    raise TimeoutError("isolated reviewer server did not start within 15 seconds")


def _run_browser_audit(
    *,
    app: object,
    runtime_path: Path,
    output: Path,
    screenshot_dir: Path,
    reviewer: str,
    headed: bool,
) -> int:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = int(listener.getsockname()[1])
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        access_log=False,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="wordyeah-browser-fixture",
        daemon=True,
    )
    thread.start()
    try:
        _wait_for_server(server, thread)
        command = [
            sys.executable,
            str(SCRIPT_DIR / "audit_browser_acceptance.py"),
            "--base-url",
            f"http://127.0.0.1:{port}",
            "--runtime",
            str(runtime_path),
            "--output",
            str(output),
            "--screenshot-dir",
            str(screenshot_dir),
            "--reviewer",
            reviewer,
        ]
        if headed:
            command.append("--headed")
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=_clean_subprocess_environment(),
            capture_output=True,
            check=False,
            text=True,
            timeout=600,
        )
        return int(completed.returncode)
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("isolated reviewer server did not stop cleanly")


def _augment_report(
    report: Mapping[str, object],
    *,
    item_id: str,
    fixture_unchanged: bool,
    audit_exit_code: int,
) -> dict[str, object]:
    augmented = dict(report)
    checks = list(report.get("checks", [])) if isinstance(report.get("checks"), list) else []
    checks.append(
        {
            "name": "isolated_fixture_non_mutation",
            "status": "PASS" if fixture_unchanged else "FAIL",
            "detail": {
                "source_open_mode": "sqlite_uri_mode_ro_query_only",
                "browser_database": "disposable_backup",
                "review_state_unchanged": fixture_unchanged,
                "production_avatar_write": False,
            },
        }
    )
    augmented.update(
        {
            "checks": checks,
            "isolated_fixture": True,
            "fixture_review_item": item_id,
            "source_database_mode": "read_only_backup",
            "source_database_mutated": False,
            "production_avatar_write": False,
            "mutates_avatar": False,
            "browser_fixture_model_calls": False,
            "audit_exit_code": audit_exit_code,
        }
    )
    if not fixture_unchanged or audit_exit_code != 0:
        augmented["status"] = "FAIL"
    return augmented


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--screenshot-dir",
        type=Path,
        default=ROOT / "output/playwright/browser-acceptance-mvp",
    )
    parser.add_argument("--consumer-id", default="corpus-avatar")
    parser.add_argument("--reviewer", default="reviewer-a")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    runtime_path = _regular_file(args.runtime, label="reviewer runtime")
    runtime = _load_runtime(runtime_path)
    reviewers = runtime["reviewers"]
    assert isinstance(reviewers, dict)
    if args.reviewer not in reviewers:
        raise ValueError("reviewer is not present in runtime config")
    media_root = args.media_root.expanduser().resolve(strict=True)
    if not media_root.is_dir():
        raise ValueError("media root must be a directory")
    output = args.output.expanduser().resolve()
    screenshot_dir = args.screenshot_dir.expanduser().resolve()

    with tempfile.TemporaryDirectory(prefix="wordyeah-browser-") as temporary:
        temporary_root = Path(temporary)
        temporary_root.chmod(0o700)
        fixture_database = temporary_root / "review.sqlite3"
        item_id, staged_state = _clone_and_stage_fixture(
            args.source_database,
            fixture_database,
            consumer_id=args.consumer_id,
        )
        settings = ApiSettings(
            database_path=str(fixture_database),
            media_root=media_root,
            consumer_id=args.consumer_id,
            reviewer_credentials=tuple(sorted(reviewers.items())),
            review_session_secret=str(runtime["session_secret"]),
            workspace_definitions=(
                (
                    args.consumer_id,
                    "Corpus Avatar",
                    "cravatar",
                    "avatar-default",
                    True,
                ),
            ),
        )
        app = create_app(
            settings=settings,
            service=MediaModerationService(_FixtureClassifier()),
        )
        audit_exit_code = _run_browser_audit(
            app=app,
            runtime_path=runtime_path,
            output=output,
            screenshot_dir=screenshot_dir,
            reviewer=args.reviewer,
            headed=args.headed,
        )
        if not output.is_file():
            raise RuntimeError("browser audit did not create its report")
        report = json.loads(output.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise RuntimeError("browser audit report must be an object")
        connection = sqlite3.connect(fixture_database)
        try:
            final_state = _review_state(connection, item_id)
        finally:
            connection.close()
        augmented = _augment_report(
            report,
            item_id=item_id,
            fixture_unchanged=final_state == staged_state,
            audit_exit_code=audit_exit_code,
        )
        _atomic_write(output, augmented)

    print(
        json.dumps(
            {
                "kind": augmented.get("kind"),
                "status": augmented.get("status"),
                "isolated_fixture": True,
                "source_database_mutated": False,
                "production_avatar_write": False,
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if augmented.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
