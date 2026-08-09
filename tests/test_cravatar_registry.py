from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from wy_cravatar.registry import (
    RegistryExportPage,
    RegistryLedger,
    RegistryRecord,
    collect_registry_export,
    read_registry_export,
)


def _png(color: str = "white") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(output, format="PNG")
    return output.getvalue()


def _row(key: str, email_hash: str, *, origin: str = "gravatar") -> dict[str, object]:
    return {
        "registry_key": key,
        "image_md5": key,
        "email_hash": email_hash,
        "avatar_url": f"https://cravatar.com/avatar/{email_hash}",
        "avatar_origin": origin,
        "registry_status": 0,
        "hash_type": "md5",
        "metadata_valid": True,
        "errors": [],
        "mutates_avatar": False,
    }


def test_registry_export_preserves_invalid_rows_and_keyset_cursor(tmp_path: Path) -> None:
    path = tmp_path / "registry.jsonl"
    invalid = {
        "registry_key": "",
        "metadata_valid": False,
        "errors": ["invalid_registry_image_md5"],
        "mutates_avatar": False,
    }
    path.write_text(
        json.dumps(invalid) + "\n" + json.dumps(_row("b" * 32, "a" * 32)) + "\n",
        encoding="utf-8",
    )

    page = read_registry_export(path)

    assert page.source_count == 2
    assert page.last_key == "b" * 32
    assert len(page.records) == 1
    assert page.records[0].source_id == f"cravatar-registry:{'b' * 32}"
    assert page.invalid_records[0].reasons == ("invalid_registry_image_md5",)


def test_registry_export_rejects_non_keyset_order(tmp_path: Path) -> None:
    path = tmp_path / "registry.jsonl"
    path.write_text(
        json.dumps(_row("b" * 32, "a" * 32))
        + "\n"
        + json.dumps(_row("a" * 32, "c" * 32))
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="strictly keyset ordered"):
        read_registry_export(path)


def test_registry_collection_uses_canonical_host_and_content_addressing(tmp_path: Path) -> None:
    records = (
        RegistryRecord("a" * 32, "a" * 32, "1" * 32, f"https://cravatar.com/avatar/{'1' * 32}", "gravatar", 0, "md5"),
        RegistryRecord("b" * 32, "b" * 32, "2" * 32, f"https://cravatar.com/avatar/{'2' * 32}", "cravatar", 1, "md5"),
    )
    urls: list[str] = []
    manifest = tmp_path / "manifest.jsonl"
    report = collect_registry_export(
        records,
        controlled_root=tmp_path / "media",
        manifest_path=manifest,
        fetch=lambda url: urls.append(url) or _png(),
        workers=2,
    )

    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    assert report["collected"] == 2
    assert report["unique_content"] == 1
    assert report["manifest_source_count"] == 2
    assert report["manifest_unique_content"] == 1
    assert report["production_write"] is False
    assert all(url.startswith("https://cn.cravatar.com/avatar/") for url in urls)
    assert all("cravatar.cn" not in url for url in urls)
    assert rows[0]["path"] == rows[1]["path"]
    assert len(list((tmp_path / "media").rglob("*.img"))) == 1


def test_registry_collection_retry_preserves_prior_manifest_rows(tmp_path: Path) -> None:
    first = RegistryRecord(
        "a" * 32,
        "a" * 32,
        "1" * 32,
        f"https://cravatar.com/avatar/{'1' * 32}",
        "gravatar",
        0,
        "md5",
    )
    second = RegistryRecord(
        "b" * 32,
        "b" * 32,
        "2" * 32,
        f"https://cravatar.com/avatar/{'2' * 32}",
        "cravatar",
        0,
        "md5",
    )
    manifest = tmp_path / "manifest.jsonl"
    media = tmp_path / "media"
    collect_registry_export(
        (first,),
        controlled_root=media,
        manifest_path=manifest,
        fetch=lambda _url: _png("white"),
    )
    report = collect_registry_export(
        (second,),
        controlled_root=media,
        manifest_path=manifest,
        fetch=lambda _url: _png("black"),
    )

    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    assert [row["source_id"] for row in rows] == [first.source_id, second.source_id]
    assert report["collected"] == 1
    assert report["manifest_source_count"] == 2
    assert report["manifest_unique_content"] == 2


def test_registry_ledger_is_idempotent_and_keeps_all_source_mappings(tmp_path: Path) -> None:
    records = (
        RegistryRecord("a" * 32, "a" * 32, "1" * 32, f"https://cravatar.com/avatar/{'1' * 32}", "gravatar", 0, "md5"),
        RegistryRecord("b" * 32, "b" * 32, "2" * 32, f"https://cravatar.com/avatar/{'2' * 32}", "cravatar", 1, "md5"),
    )
    page = RegistryExportPage(records, (), 2, "b" * 32)
    database = str(tmp_path / "wordyeah.sqlite3")
    ledger = RegistryLedger(database)
    ledger.begin_snapshot("snapshot-1", source_mode="live_keyset", source_count_expected=2)
    assert ledger.ingest_page("snapshot-1", page)["pending"] == 2
    assert ledger.ingest_page("snapshot-1", page)["total"] == 2

    manifest = tmp_path / "manifest.jsonl"
    media = tmp_path / "media"
    collect_registry_export(
        records,
        controlled_root=media,
        manifest_path=manifest,
        fetch=lambda _url: _png(),
    )
    first = ledger.apply_manifest("snapshot-1", manifest, media)
    second = ledger.apply_manifest("snapshot-1", manifest, media)
    assert first == second == {
        "total": 2,
        "pending": 0,
        "collected": 2,
        "invalid_metadata": 0,
        "fetch_error": 0,
        "fetch_missing": 0,
        "invalid_media": 0,
    }

    with sqlite3.connect(database) as connection:
        content = connection.execute(
            "SELECT reference_count FROM content_assets"
        ).fetchone()
        mappings = connection.execute("SELECT COUNT(*) FROM registry_assets").fetchone()
    assert content == (2,)
    assert mappings == (2,)


def test_registry_ledger_rejects_source_drift_inside_snapshot(tmp_path: Path) -> None:
    ledger = RegistryLedger(str(tmp_path / "wordyeah.sqlite3"))
    ledger.begin_snapshot("snapshot-1", source_mode="live_keyset")
    first = RegistryRecord("a" * 32, "a" * 32, "1" * 32, f"https://cravatar.com/avatar/{'1' * 32}", "gravatar", 0, "md5")
    changed = RegistryRecord("a" * 32, "a" * 32, "2" * 32, f"https://cravatar.com/avatar/{'2' * 32}", "gravatar", 0, "md5")
    ledger.ingest_page("snapshot-1", RegistryExportPage((first,), (), 1, "a" * 32))
    with pytest.raises(ValueError, match="changed inside snapshot"):
        ledger.ingest_page("snapshot-1", RegistryExportPage((changed,), (), 1, "a" * 32))


def test_registry_ledger_classifies_terminal_and_retryable_collection_failures(
    tmp_path: Path,
) -> None:
    records = tuple(
        RegistryRecord(
            character * 32,
            character * 32,
            str(index) * 32,
            f"https://cravatar.com/avatar/{str(index) * 32}",
            "gravatar",
            0,
            "md5",
        )
        for index, character in enumerate(("a", "b", "c"), 1)
    )
    ledger = RegistryLedger(str(tmp_path / "wordyeah.sqlite3"))
    ledger.begin_snapshot("snapshot-1", source_mode="live_keyset")
    ledger.ingest_page("snapshot-1", RegistryExportPage(records, (), 3, "c" * 32))
    ledger.mark_failures(
        "snapshot-1",
        (
            {"source_id": records[0].source_id, "error_kind": "HTTPError", "error": "HTTP Error 404"},
            {"source_id": records[1].source_id, "error_kind": "ValueError", "error": "bad image"},
            {"source_id": records[2].source_id, "error_kind": "TimeoutError", "error": "timeout"},
        ),
    )
    summary = ledger.summary("snapshot-1")
    assert summary["fetch_missing"] == 1
    assert summary["invalid_media"] == 1
    assert summary["fetch_error"] == 1
    assert ledger.retryable_source_ids("snapshot-1") == {records[2].source_id}


def test_registry_snapshot_completion_requires_terminal_counted_sources(tmp_path: Path) -> None:
    record = RegistryRecord(
        "a" * 32,
        "a" * 32,
        "1" * 32,
        f"https://cravatar.com/avatar/{'1' * 32}",
        "gravatar",
        0,
        "md5",
    )
    database = str(tmp_path / "wordyeah.sqlite3")
    ledger = RegistryLedger(database)
    ledger.begin_snapshot("snapshot-1", source_mode="live_keyset")
    ledger.ingest_page("snapshot-1", RegistryExportPage((record,), (), 1, record.registry_key))

    with pytest.raises(ValueError, match="retryable"):
        ledger.complete_snapshot(
            "snapshot-1", source_count_expected=1, manifest_sha256="f" * 64
        )

    ledger.mark_failures(
        "snapshot-1",
        ({"source_id": record.source_id, "error_kind": "HTTPError", "error": "404"},),
    )
    with pytest.raises(ValueError, match="count mismatch"):
        ledger.complete_snapshot(
            "snapshot-1", source_count_expected=2, manifest_sha256="f" * 64
        )
    summary = ledger.complete_snapshot(
        "snapshot-1", source_count_expected=1, manifest_sha256="f" * 64
    )
    assert summary["fetch_missing"] == 1
    with sqlite3.connect(database) as connection:
        snapshot = connection.execute(
            "SELECT source_count_expected, manifest_sha256, status, completed_at "
            "FROM registry_snapshots WHERE snapshot_id='snapshot-1'"
        ).fetchone()
    assert snapshot[:3] == (1, "f" * 64, "complete")
    assert snapshot[3]
