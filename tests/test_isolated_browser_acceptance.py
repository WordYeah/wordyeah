from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
from pathlib import Path

import pytest

from wy_core.database import open_database


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_isolated_browser_acceptance.py"
SPEC = importlib.util.spec_from_file_location("run_isolated_browser_acceptance", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _source_database(path: Path) -> None:
    connection = open_database(str(path))
    connection.execute(
        """INSERT INTO review_items
             (item_id, consumer_id, content_sha256, media_type, media_ref,
              decision_hint, reasons_json, status, version, created_at, stage,
              final_decision, avatar_action, reviewer, review_note, reviewed_at,
              quality_sample, arbitration_required, appealed)
           VALUES
             ('item-1', 'corpus-avatar', ?, 'image/png', 'media://fixture/item.png',
              'allow', '[]', 'approved', 7, '2026-08-05T00:00:00+00:00',
              'human_decided', 'allow', 'keep', 'reviewer-a', 'done',
              '2026-08-05T00:01:00+00:00', 1, 1, 1)""",
        ("a" * 64,),
    )
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_clone_stages_only_disposable_database(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    fixture = tmp_path / "private" / "fixture.sqlite3"
    _source_database(source)
    source_before = _sha256(source)

    item_id, staged = MODULE._clone_and_stage_fixture(
        source,
        fixture,
        consumer_id="corpus-avatar",
    )

    assert item_id == "item-1"
    assert source_before == _sha256(source)
    assert fixture.stat().st_mode & 0o777 == 0o600
    source_connection = sqlite3.connect(source)
    fixture_connection = sqlite3.connect(fixture)
    try:
        source_row = source_connection.execute(
            "SELECT status, stage, final_decision, quality_sample, version "
            "FROM review_items WHERE item_id = 'item-1'"
        ).fetchone()
        fixture_row = fixture_connection.execute(
            "SELECT status, stage, final_decision, quality_sample, version "
            "FROM review_items WHERE item_id = 'item-1'"
        ).fetchone()
    finally:
        source_connection.close()
        fixture_connection.close()
    assert source_row == ("approved", "human_decided", "allow", 1, 7)
    assert fixture_row == ("pending", "human_required", None, 0, 8)
    assert staged["item"][:4] == ["pending", "human_required", None, None]


def test_clone_rejects_database_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _source_database(source)
    link = tmp_path / "source-link.sqlite3"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="symlink"):
        MODULE._clone_and_stage_fixture(
            link,
            tmp_path / "fixture.sqlite3",
            consumer_id="corpus-avatar",
        )


def test_augmented_report_fails_if_fixture_changed() -> None:
    report = MODULE._augment_report(
        {"kind": "wordyeah_browser_acceptance", "status": "PASS", "checks": []},
        item_id="item-1",
        fixture_unchanged=False,
        audit_exit_code=0,
    )
    assert report["status"] == "FAIL"
    assert report["source_database_mutated"] is False
    assert report["production_avatar_write"] is False
    assert report["checks"][-1]["status"] == "FAIL"
