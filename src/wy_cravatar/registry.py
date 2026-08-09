"""Read-only registry snapshot, collection and source-to-content ledger."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Literal

from .export import _atomic_write, _fetch_image, _normalized_avatar_url, _validate_image


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_hex(value: str) -> bool:
    return bool(value) and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True)
class RegistryRecord:
    registry_key: str
    image_md5: str
    email_hash: str
    avatar_url: str
    avatar_origin: Literal["cravatar", "gravatar"]
    registry_status: int
    hash_type: Literal["md5", "sha256"]

    @property
    def source_id(self) -> str:
        return f"cravatar-registry:{self.registry_key}"


@dataclass(frozen=True)
class InvalidRegistryRecord:
    registry_key: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RegistryExportPage:
    records: tuple[RegistryRecord, ...]
    invalid_records: tuple[InvalidRegistryRecord, ...]
    source_count: int
    last_key: str | None


def read_registry_export(path: Path) -> RegistryExportPage:
    records: list[RegistryRecord] = []
    invalid: list[InvalidRegistryRecord] = []
    seen: set[str] = set()
    last_key: str | None = None
    source_count = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        source_count += 1
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError("row must be an object")
            registry_key = str(row["registry_key"]).lower()
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid registry export row {line_number}: {exc}") from exc
        if len(registry_key) > 100 or any(ord(char) < 32 for char in registry_key):
            raise ValueError(f"invalid keyset value on row {line_number}")
        if last_key is not None and registry_key <= last_key:
            raise ValueError(f"registry export is not strictly keyset ordered on row {line_number}")
        if registry_key in seen:
            raise ValueError(f"duplicate registry key on row {line_number}")
        seen.add(registry_key)
        last_key = registry_key

        reasons = tuple(str(value) for value in row.get("errors", ()) if str(value))
        if row.get("mutates_avatar") is not False:
            reasons += ("mutating_export_contract",)
        if row.get("metadata_valid") is not True:
            invalid.append(InvalidRegistryRecord(registry_key, reasons or ("invalid_metadata",)))
            continue
        try:
            image_md5 = str(row["image_md5"]).lower()
            email_hash = str(row["email_hash"]).lower()
            avatar_url = str(row["avatar_url"])
            origin = str(row["avatar_origin"]).lower()
            hash_type = str(row["hash_type"]).lower()
            registry_status = int(row["registry_status"])
        except (KeyError, TypeError, ValueError) as exc:
            invalid.append(InvalidRegistryRecord(registry_key, (f"invalid_fields:{exc}",)))
            continue
        field_errors: list[str] = []
        if registry_key != image_md5 or len(image_md5) != 32 or not _is_hex(image_md5):
            field_errors.append("invalid_registry_image_md5")
        if origin not in {"cravatar", "gravatar"}:
            field_errors.append("invalid_avatar_origin")
        if hash_type not in {"md5", "sha256"}:
            field_errors.append("invalid_hash_type")
        expected_hash_length = 64 if hash_type == "sha256" else 32
        if len(email_hash) != expected_hash_length or not _is_hex(email_hash):
            field_errors.append("invalid_email_hash")
        try:
            _normalized_avatar_url(avatar_url, email_hash)
        except ValueError:
            field_errors.append("invalid_avatar_url")
        if field_errors:
            invalid.append(InvalidRegistryRecord(registry_key, tuple(field_errors)))
            continue
        records.append(
            RegistryRecord(
                registry_key=registry_key,
                image_md5=image_md5,
                email_hash=email_hash,
                avatar_url=avatar_url,
                avatar_origin=origin,  # type: ignore[arg-type]
                registry_status=registry_status,
                hash_type=hash_type,  # type: ignore[arg-type]
            )
        )
    return RegistryExportPage(tuple(records), tuple(invalid), source_count, last_key)


def collect_registry_export(
    records: Iterable[RegistryRecord],
    *,
    controlled_root: Path,
    manifest_path: Path,
    fetch: Callable[[str], bytes] | None = None,
    workers: int = 8,
    snapshot_id: str | None = None,
) -> dict[str, object]:
    """Collect current bytes and atomically merge them into the snapshot manifest."""

    if workers < 1 or workers > 32:
        raise ValueError("workers must be between 1 and 32")
    controlled_root.mkdir(parents=True, exist_ok=True)
    os.chmod(controlled_root, 0o700)
    fetch_image = fetch or _fetch_image
    source_records = tuple(records)

    def collect_one(
        record: RegistryRecord,
    ) -> tuple[dict[str, object] | None, dict[str, str] | None, int]:
        public_url = _normalized_avatar_url(record.avatar_url, record.email_hash)
        started = time.perf_counter()
        try:
            payload = fetch_image(public_url)
            _validate_image(payload)
            content_sha256 = hashlib.sha256(payload).hexdigest()
            content_md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
            relative = Path(content_sha256[:2]) / f"{content_sha256}.img"
            target = controlled_root / relative
            if not target.exists():
                _atomic_write(target, payload, mode=0o600)
            return (
                {
                    "path": relative.as_posix(),
                    "avatar_ref": f"cravatar://{record.email_hash}",
                    "request_id": f"cravatar-registry-shadow-{record.registry_key}",
                    "source_id": record.source_id,
                    "content_sha256": content_sha256,
                    "source_kind": "registry-read-only-keyset",
                    "registry_snapshot_id": snapshot_id or "",
                    "image_md5": record.image_md5,
                    "avatar_origin": record.avatar_origin,
                    "origin_verified": True,
                    "registry_status": record.registry_status,
                    "hash_type": record.hash_type,
                    "url_hash": hashlib.sha256(record.email_hash.encode("ascii")).hexdigest(),
                    "collection_url_host": "cn.cravatar.com",
                    "collected_at": _now(),
                    "collected_content_md5": content_md5,
                    "matches_registry_image_md5": content_md5 == record.image_md5,
                    "requires_ai_review": True,
                    "mutates_avatar": False,
                },
                None,
                round((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return (
                None,
                {
                    "source_id": record.source_id,
                    "error": str(exc),
                    "error_kind": type(exc).__name__,
                },
                round((time.perf_counter() - started) * 1000),
            )

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cravatar-registry") as pool:
        results = list(pool.map(collect_one, source_records))
    rows = [row for row, _failure, _elapsed in results if row is not None]
    failures = [failure for _row, failure, _elapsed in results if failure is not None]
    latencies = sorted(elapsed for _row, _failure, elapsed in results)

    def percentile(percent: float) -> int | None:
        if not latencies:
            return None
        return latencies[min(len(latencies) - 1, round((len(latencies) - 1) * percent))]

    merged: dict[str, dict[str, object]] = {}
    if manifest_path.exists():
        root = controlled_root.resolve(strict=True)
        for line_number, line in enumerate(
            manifest_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
                source_id = str(existing["source_id"])
                digest = str(existing["content_sha256"])
                relative = Path(str(existing["path"]))
                target = (root / relative).resolve(strict=True)
                target.relative_to(root)
            except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid existing manifest row {line_number}") from exc
            if (
                not source_id.startswith("cravatar-registry:")
                or len(digest) != 64
                or not _is_hex(digest)
                or existing.get("mutates_avatar") is not False
                or hashlib.sha256(target.read_bytes()).hexdigest() != digest
            ):
                raise ValueError(f"invalid existing manifest row {line_number}")
            if source_id in merged:
                raise ValueError(f"duplicate existing manifest source on row {line_number}")
            merged[source_id] = existing
    for row in rows:
        source_id = str(row["source_id"])
        existing = merged.get(source_id)
        if existing is not None and existing["content_sha256"] != row["content_sha256"]:
            raise ValueError(f"registry source content changed inside snapshot: {source_id}")
        merged[source_id] = row
    manifest_rows = [merged[source_id] for source_id in sorted(merged)]
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in manifest_rows
    )
    _atomic_write(manifest_path, payload.encode("utf-8"), mode=0o600)
    return {
        "kind": "cravatar_registry_collection",
        "source_count": len(source_records),
        "collected": len(rows),
        "failed": len(failures),
        "failures": failures,
        "fetch_latency_ms": {"p50": percentile(0.50), "p95": percentile(0.95)},
        "unique_content": len({str(row["content_sha256"]) for row in rows}),
        "manifest_source_count": len(manifest_rows),
        "manifest_unique_content": len(
            {str(row["content_sha256"]) for row in manifest_rows}
        ),
        "manifest": str(manifest_path),
        "outbound_hosts": ["cn.cravatar.com"],
        "mutates_avatar": False,
        "production_write": False,
    }


class RegistryLedger:
    """Local source-to-content ledger; it never connects to the source database."""

    def __init__(self, database: str) -> None:
        self.connection = sqlite3.connect(database, timeout=30.0)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS registry_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                source_table TEXT NOT NULL,
                source_count_expected INTEGER,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                cursor_end TEXT,
                manifest_sha256 TEXT,
                source_mode TEXT NOT NULL CHECK(source_mode IN ('replica','live_keyset')),
                status TEXT NOT NULL CHECK(status IN ('preparing','running','reconciling','complete','failed'))
            );
            CREATE TABLE IF NOT EXISTS registry_assets (
                snapshot_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                registry_image_md5 TEXT NOT NULL,
                url_hash TEXT,
                avatar_origin TEXT,
                registry_status INTEGER,
                hash_type TEXT,
                canonical_url_host TEXT,
                fetch_status TEXT NOT NULL,
                content_sha256 TEXT,
                media_ref TEXT,
                updated_at TEXT NOT NULL,
                error_reason TEXT,
                PRIMARY KEY(snapshot_id, source_id)
            );
            CREATE TABLE IF NOT EXISTS content_assets (
                content_sha256 TEXT PRIMARY KEY,
                media_ref TEXT NOT NULL,
                byte_size INTEGER,
                reference_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )

    def begin_snapshot(
        self,
        snapshot_id: str,
        *,
        source_mode: Literal["replica", "live_keyset"],
        source_count_expected: int | None = None,
    ) -> None:
        if not snapshot_id.strip():
            raise ValueError("snapshot_id is required")
        self.connection.execute(
            """INSERT INTO registry_snapshots
                   (snapshot_id, source_table, source_count_expected, started_at, source_mode, status)
               VALUES (?, 'wp_9_avatar_verify', ?, ?, ?, 'preparing')
               ON CONFLICT(snapshot_id) DO NOTHING""",
            (snapshot_id, source_count_expected, _now(), source_mode),
        )
        self.connection.commit()

    def ingest_page(self, snapshot_id: str, page: RegistryExportPage) -> dict[str, int]:
        now = _now()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            for record in page.records:
                existing = self.connection.execute(
                    """SELECT registry_image_md5, url_hash, avatar_origin, registry_status, hash_type
                       FROM registry_assets WHERE snapshot_id=? AND source_id=?""",
                    (snapshot_id, record.source_id),
                ).fetchone()
                values = (
                    record.image_md5,
                    hashlib.sha256(record.email_hash.encode("ascii")).hexdigest(),
                    record.avatar_origin,
                    record.registry_status,
                    record.hash_type,
                )
                if existing is not None:
                    if tuple(existing) != values:
                        raise ValueError(f"registry source changed inside snapshot: {record.source_id}")
                    continue
                self.connection.execute(
                    """INSERT INTO registry_assets
                           (snapshot_id, source_id, registry_image_md5, url_hash, avatar_origin,
                            registry_status, hash_type, canonical_url_host, fetch_status, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'cn.cravatar.com', 'pending', ?)""",
                    (
                        snapshot_id,
                        record.source_id,
                        *values,
                        now,
                    ),
                )
            for record in page.invalid_records:
                source_id = f"cravatar-registry:{record.registry_key or 'invalid-empty'}"
                self.connection.execute(
                    """INSERT INTO registry_assets
                           (snapshot_id, source_id, registry_image_md5, fetch_status, updated_at, error_reason)
                       VALUES (?, ?, ?, 'invalid_metadata', ?, ?)
                       ON CONFLICT(snapshot_id, source_id) DO UPDATE SET
                         updated_at=excluded.updated_at, error_reason=excluded.error_reason""",
                    (snapshot_id, source_id, record.registry_key, now, ",".join(record.reasons)),
                )
            self.connection.execute(
                "UPDATE registry_snapshots SET cursor_end = ?, status = 'running' WHERE snapshot_id = ?",
                (page.last_key, snapshot_id),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.summary(snapshot_id)

    def apply_manifest(self, snapshot_id: str, manifest_path: Path, controlled_root: Path) -> dict[str, int]:
        root = controlled_root.resolve(strict=True)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                source_id = str(row["source_id"])
                digest = str(row["content_sha256"])
                relative = Path(str(row["path"]))
                target = (root / relative).resolve(strict=True)
                target.relative_to(root)
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ValueError(f"manifest content mismatch on row {line_number}")
                existing = self.connection.execute(
                    """SELECT fetch_status, content_sha256 FROM registry_assets
                       WHERE snapshot_id=? AND source_id=?""",
                    (snapshot_id, source_id),
                ).fetchone()
                if existing is None:
                    raise ValueError(f"manifest source is outside snapshot on row {line_number}")
                if existing["fetch_status"] == "collected":
                    if existing["content_sha256"] != digest:
                        raise ValueError(f"collected content changed on row {line_number}")
                    continue
                updated = self.connection.execute(
                    """UPDATE registry_assets SET fetch_status='collected', content_sha256=?,
                           media_ref=?, updated_at=?, error_reason=NULL
                       WHERE snapshot_id=? AND source_id=?""",
                    (digest, f"media://registry/{relative.as_posix()}", _now(), snapshot_id, source_id),
                )
                if updated.rowcount != 1:
                    raise RuntimeError(f"failed to update manifest source on row {line_number}")
                self.connection.execute(
                    """INSERT INTO content_assets
                           (content_sha256, media_ref, byte_size, reference_count, updated_at)
                       VALUES (?, ?, ?, 1, ?)
                       ON CONFLICT(content_sha256) DO UPDATE SET
                         reference_count=content_assets.reference_count + 1,
                         updated_at=excluded.updated_at""",
                    (digest, f"media://registry/{relative.as_posix()}", target.stat().st_size, _now()),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.summary(snapshot_id)

    def retryable_source_ids(self, snapshot_id: str) -> set[str]:
        rows = self.connection.execute(
            """SELECT source_id FROM registry_assets
               WHERE snapshot_id=? AND fetch_status IN ('pending','fetch_error')""",
            (snapshot_id,),
        ).fetchall()
        return {str(row["source_id"]) for row in rows}

    def complete_snapshot(
        self,
        snapshot_id: str,
        *,
        source_count_expected: int,
        manifest_sha256: str,
    ) -> dict[str, int]:
        """Seal a fully reconciled local snapshot after explicit count checks."""

        if source_count_expected < 1:
            raise ValueError("source_count_expected must be positive")
        if len(manifest_sha256) != 64 or not _is_hex(manifest_sha256):
            raise ValueError("manifest_sha256 must be a lowercase SHA-256 digest")
        summary = self.summary(snapshot_id)
        if summary["total"] != source_count_expected:
            raise ValueError(
                f"snapshot count mismatch: expected {source_count_expected}, got {summary['total']}"
            )
        if summary["pending"] or summary["fetch_error"]:
            raise ValueError("snapshot still contains retryable sources")
        updated = self.connection.execute(
            """UPDATE registry_snapshots
               SET source_count_expected=?, manifest_sha256=?, completed_at=?, status='complete'
               WHERE snapshot_id=? AND status!='failed'""",
            (source_count_expected, manifest_sha256, _now(), snapshot_id),
        )
        if updated.rowcount != 1:
            self.connection.rollback()
            raise ValueError("snapshot is missing or failed")
        self.connection.commit()
        return summary

    def mark_failures(self, snapshot_id: str, failures: Iterable[object]) -> None:
        now = _now()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            for failure in failures:
                if not isinstance(failure, dict):
                    raise ValueError("collection failure must be an object")
                source_id = str(failure.get("source_id", ""))
                error = str(failure.get("error", "collection_failed"))[:1000]
                error_kind = str(failure.get("error_kind", ""))
                if error_kind == "HTTPError" and ("404" in error or "410" in error):
                    fetch_status = "fetch_missing"
                elif error_kind in {"UnidentifiedImageError", "DecompressionBombError", "ValueError"}:
                    fetch_status = "invalid_media"
                else:
                    fetch_status = "fetch_error"
                updated = self.connection.execute(
                    """UPDATE registry_assets SET fetch_status=?, error_reason=?, updated_at=?
                       WHERE snapshot_id=? AND source_id=? AND fetch_status!='collected'""",
                    (fetch_status, error, now, snapshot_id, source_id),
                )
                if updated.rowcount != 1:
                    raise ValueError(f"failure source is outside snapshot: {source_id}")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def summary(self, snapshot_id: str) -> dict[str, int]:
        rows = self.connection.execute(
            """SELECT fetch_status, COUNT(*) AS count FROM registry_assets
               WHERE snapshot_id=? GROUP BY fetch_status""",
            (snapshot_id,),
        ).fetchall()
        counts = {str(row["fetch_status"]): int(row["count"]) for row in rows}
        return {
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "collected": counts.get("collected", 0),
            "invalid_metadata": counts.get("invalid_metadata", 0),
            "fetch_error": counts.get("fetch_error", 0),
            "fetch_missing": counts.get("fetch_missing", 0),
            "invalid_media": counts.get("invalid_media", 0),
        }
