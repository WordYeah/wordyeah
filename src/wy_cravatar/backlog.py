from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping

from wy_media.image_safety import ImageLimits, decode_image


PathField = Literal["path", "local_path", "image_path"]
PATH_FIELDS: tuple[PathField, ...] = ("path", "local_path", "image_path")
MODERATION_SOURCE_METADATA_FIELDS = (
    "source_kind",
    "registry_snapshot_id",
    "avatar_origin",
    "origin_verified",
    "registry_status",
    "hash_type",
    "url_hash",
    "collection_url_host",
    "image_md5",
    "collected_content_md5",
    "matches_queued_image_md5",
    "matches_registry_image_md5",
    "requires_ai_review",
)


@dataclass(frozen=True)
class CravatarBacklogRecord:
    """Metadata-only shadow contract for one controlled local avatar image."""

    avatar_ref: str
    request_id: str
    content_sha256: str
    source_path: str
    source_metadata: Mapping[str, object] = field(default_factory=dict)
    source_id: str = ""
    media_type: Literal["image"] = "image"
    mode: Literal["shadow"] = "shadow"
    action: Literal["record_only"] = "record_only"
    mutates_avatar: Literal[False] = False

    def __post_init__(self) -> None:
        source_id = self.source_id or f"cravatar-sha256:{self.content_sha256}"
        if (
            not isinstance(source_id, str)
            or not source_id.strip()
            or source_id.lower().startswith(("http://", "https://"))
        ):
            raise ValueError("source_id must be a local/staging identifier")
        object.__setattr__(self, "source_id", source_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "avatar_ref": self.avatar_ref,
            "request_id": self.request_id,
            "content_sha256": self.content_sha256,
            "source_path": self.source_path,
            "source_id": self.source_id,
            "source_metadata": dict(self.source_metadata),
            "media_type": self.media_type,
            "mode": self.mode,
            "action": self.action,
            "mutates_avatar": False,
        }


@dataclass(frozen=True)
class CravatarBacklog:
    records: tuple[CravatarBacklogRecord, ...]
    source_count: int
    duplicate_count: int

    def enqueue(self, callback: Callable[[dict[str, object]], Any]) -> tuple[Any, ...]:
        """Pass validated metadata to an explicitly injected queue callback.

        The importer owns no queue or production connector. Callback failures
        propagate immediately, so a caller cannot mistake a partial enqueue for
        success.
        """

        if not callable(callback):
            raise TypeError("enqueue callback must be callable")
        results: list[Any] = []
        for record in self.records:
            payload = record.to_dict()
            if payload["mutates_avatar"] is not False or payload["action"] != "record_only":
                raise RuntimeError("backlog contract must remain non-mutating")
            results.append(callback(payload))
        return tuple(results)

    def to_jsonl(self) -> str:
        return "".join(json.dumps(record.to_dict(), ensure_ascii=False) + "\n" for record in self.records)


def moderation_source_metadata(record: CravatarBacklogRecord) -> dict[str, object]:
    """Return the bounded Cravatar provenance passed to the local WordYeah API."""

    metadata = {
        key: record.source_metadata[key]
        for key in MODERATION_SOURCE_METADATA_FIELDS
        if key in record.source_metadata
    }
    # A backlog entry is not a live request. Even when the inexpensive scan
    # says allow, the historical item must still receive the normal AI review
    # chain before it can be considered closed.
    metadata["requires_ai_review"] = True
    return metadata


def _read_rows(manifest: Path) -> list[dict[str, object]]:
    suffix = manifest.suffix.lower()
    if suffix == ".csv":
        with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if suffix == ".jsonl":
        rows: list[dict[str, object]] = []
        for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_number} must be an object")
            rows.append(value)
        return rows
    if suffix == ".json":
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if isinstance(value, dict) and "records" in value:
            value = value["records"]
        elif isinstance(value, dict):
            value = [value]
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise ValueError("JSON manifest must be an object, an object list, or contain a records list")
        return value
    raise ValueError("manifest must use .csv, .json, or .jsonl")


def _controlled_path(raw_path: object, *, root: Path) -> tuple[Path, str]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("record path must be a non-empty local path")
    if raw_path.lower().startswith(("http://", "https://")):
        raise ValueError("remote image paths are not allowed")
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root)
    except FileNotFoundError as exc:
        raise ValueError(f"local image does not exist: {raw_path}") from exc
    except ValueError as exc:
        raise ValueError(f"local image escapes controlled root: {raw_path}") from exc
    if not resolved.is_file():
        raise ValueError(f"local image is not a file: {raw_path}")
    return resolved, relative.as_posix()


def _row_path(row: Mapping[str, object]) -> object:
    populated = [field_name for field_name in PATH_FIELDS if row.get(field_name)]
    if len(populated) != 1:
        raise ValueError("record must define exactly one of path, local_path, or image_path")
    return row[populated[0]]


def _metadata(row: Mapping[str, object]) -> dict[str, object]:
    reserved = set(PATH_FIELDS) | {"avatar_ref", "request_id", "content_sha256", "source_id"}
    return {
        str(key): value
        for key, value in row.items()
        if key not in reserved and value not in (None, "")
    }


def import_cravatar_backlog(
    manifest: Path,
    *,
    controlled_root: Path,
    image_limits: ImageLimits | None = None,
) -> CravatarBacklog:
    """Read and normalize a local Cravatar backlog without external I/O."""

    manifest = manifest.resolve(strict=True)
    root = controlled_root.resolve(strict=True)
    if not manifest.is_file():
        raise ValueError(f"manifest is not a file: {manifest}")
    if not root.is_dir():
        raise ValueError(f"controlled root is not a directory: {root}")

    rows = _read_rows(manifest)
    records: list[CravatarBacklogRecord] = []
    seen_hashes: set[str] = set()
    duplicate_count = 0
    for index, row in enumerate(rows, 1):
        try:
            image_path, relative_path = _controlled_path(_row_path(row), root=root)
            image_bytes = image_path.read_bytes()
            decode_image(image_bytes, image_limits or ImageLimits())
            digest = hashlib.sha256(image_bytes).hexdigest()
            declared_digest = row.get("content_sha256")
            if declared_digest not in (None, "") and declared_digest != digest:
                raise ValueError("declared content_sha256 does not match local image")
            if digest in seen_hashes:
                duplicate_count += 1
                continue

            avatar_ref = row.get("avatar_ref") or f"cravatar-backlog://{relative_path}"
            if not isinstance(avatar_ref, str) or not avatar_ref.strip():
                raise ValueError("avatar_ref must be a non-empty string")
            if avatar_ref.lower().startswith(("http://", "https://")):
                raise ValueError("remote avatar_ref values are not allowed")
            request_id = row.get("request_id") or f"cravatar-backlog-{digest[:24]}"
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError("request_id must be a non-empty string")
            source_id = row.get("source_id") or f"cravatar-sha256:{digest}"
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("source_id must be a non-empty string")
            if source_id.lower().startswith(("http://", "https://")):
                raise ValueError("remote source_id values are not allowed")

            seen_hashes.add(digest)
            records.append(
                CravatarBacklogRecord(
                    avatar_ref=avatar_ref,
                    request_id=request_id,
                    content_sha256=digest,
                    source_path=relative_path,
                    source_id=source_id,
                    source_metadata=_metadata(row),
                )
            )
        except (OSError, ValueError) as exc:
            raise ValueError(f"record {index}: {exc}") from exc

    return CravatarBacklog(tuple(records), source_count=len(rows), duplicate_count=duplicate_count)


def enqueue_cravatar_backlog(
    records: Iterable[CravatarBacklogRecord],
    callback: Callable[[dict[str, object]], Any],
) -> tuple[Any, ...]:
    """Enqueue already-normalized records through an injected callback only."""

    materialized = tuple(records)
    return CravatarBacklog(materialized, len(materialized), 0).enqueue(callback)


def submit_cravatar_backlog(
    backlog: CravatarBacklog,
    *,
    controlled_root: Path,
    callback: Callable[[CravatarBacklogRecord, bytes], Any],
    image_limits: ImageLimits | None = None,
) -> tuple[Any, ...]:
    """Submit validated local bytes to an injected WordYeah transport.

    The content hash is checked again immediately before submission to close
    the gap between manifest validation and processing. This function has no
    HTTP or WordPress dependency and never returns an avatar mutation.
    """

    if not callable(callback):
        raise TypeError("submission callback must be callable")
    root = controlled_root.resolve(strict=True)
    results: list[Any] = []
    for record in backlog.records:
        if record.mutates_avatar is not False or record.action != "record_only":
            raise RuntimeError("backlog contract must remain non-mutating")
        path, _ = _controlled_path(record.source_path, root=root)
        payload = path.read_bytes()
        decode_image(payload, image_limits or ImageLimits())
        if hashlib.sha256(payload).hexdigest() != record.content_sha256:
            raise ValueError(f"content changed after import: {record.source_path}")
        results.append(callback(record, payload))
    return tuple(results)
