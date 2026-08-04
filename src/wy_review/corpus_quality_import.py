"""Import unreviewed corpus candidates into the private quality-review inbox."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
from pathlib import Path
from typing import Iterable

from wy_media.image_safety import ImageLimits, decode_image
from wy_review.quality import QualityConflictError, QualityStore


MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_CANDIDATES = 10_000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_MEDIA_BYTES = 2 * 1024 * 1024 * 1024
STRATA = frozenset({"human", "anime", "logo_text", "boundary", "explicit_violation"})
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CorpusQualityImportError(ValueError):
    """Raised when a candidate manifest violates the private import contract."""


def import_candidate_manifests(
    manifests: Iterable[tuple[str, Path]],
    *,
    database: Path,
    media_root: Path,
    consumer_id: str,
    vocabulary_version: str = "v1",
    actor_id: str = "corpus-import",
) -> dict[str, object]:
    """Copy verified candidates under ``media_root`` and create idempotent samples."""

    if not SAFE_NAME.fullmatch(consumer_id):
        raise CorpusQualityImportError("consumer_id must be a safe name")
    manifest_specs = list(manifests)
    if not manifest_specs:
        raise CorpusQualityImportError("at least one stratum manifest is required")
    prepared: list[tuple[str, str, Path, str]] = []
    seen: set[str] = set()
    total_media_bytes = 0
    for stratum, manifest in manifest_specs:
        if stratum not in STRATA:
            raise CorpusQualityImportError(f"unsupported stratum: {stratum}")
        manifest_path = manifest.expanduser().absolute()
        for row in _candidate_rows(manifest_path):
            digest, source = _validated_candidate(row, manifest_path)
            if digest in seen:
                raise CorpusQualityImportError(f"duplicate candidate digest: {digest}")
            seen.add(digest)
            suffix = _verify_source(source, digest)
            prepared.append((stratum, digest, source, suffix))
            total_media_bytes += source.stat().st_size
            if total_media_bytes > MAX_TOTAL_MEDIA_BYTES:
                raise CorpusQualityImportError("candidate import exceeds total media size limit")
            if len(prepared) > MAX_CANDIDATES:
                raise CorpusQualityImportError("candidate import has too many rows")

    controlled_root = _controlled_media_root(media_root, consumer_id)
    thumbnail_root = controlled_root / "thumbs"
    thumbnail_root.mkdir(mode=0o700, exist_ok=True)
    if thumbnail_root.is_symlink() or not thumbnail_root.is_dir():
        raise CorpusQualityImportError("controlled thumbnail directory is invalid")
    thumbnail_root.chmod(0o700)
    database_path = _private_database_path(database)
    store = QualityStore(str(database_path))
    imported = 0
    reused = 0
    by_stratum: dict[str, int] = {stratum: 0 for stratum, _ in manifest_specs}
    try:
        store.create_vocabulary(
            consumer_id=consumer_id,
            version=vocabulary_version,
            actor_id=actor_id,
        )
        for stratum, digest, source, suffix in prepared:
            destination = controlled_root / f"{digest}{suffix}"
            thumbnail = thumbnail_root / f"{digest}.jpg"
            created = _copy_verified(source, destination, thumbnail, digest)
            media_ref = f"media://corpus/{consumer_id}/{destination.name}"
            sample = store.create_sample(
                consumer_id=consumer_id,
                item_id=f"corpus-{digest}",
                content_sha256=digest,
                media_ref=media_ref,
                reason="quality_sample",
                vocabulary_version=vocabulary_version,
                stratum=stratum,
                retention_status="private_corpus",
                actor_id=actor_id,
            )
            if sample.stratum != stratum or sample.retention_status != "private_corpus":
                raise QualityConflictError(
                    "quality sample already exists with different corpus metadata"
                )
            imported += int(created)
            reused += int(not created)
            by_stratum[stratum] = by_stratum.get(stratum, 0) + 1
    finally:
        store.close()
        database_path.chmod(0o600)
    return {
        "kind": "wordyeah_corpus_quality_import",
        "status": "READY_FOR_HUMAN_REVIEW",
        "consumer_id": consumer_id,
        "sample_count": sum(by_stratum.values()),
        "copied_count": imported,
        "reused_count": reused,
        "by_stratum": by_stratum,
        "ground_truth": False,
        "production_write": False,
    }


def _controlled_media_root(media_root: Path, consumer_id: str) -> Path:
    root = media_root.expanduser()
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise CorpusQualityImportError("media_root must be a real directory")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    corpus_root = root / "corpus"
    corpus_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if corpus_root.is_symlink() or not corpus_root.is_dir():
        raise CorpusQualityImportError("controlled corpus root is invalid")
    corpus_root.chmod(0o700)
    target = corpus_root / consumer_id
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.is_symlink() or not target.is_dir():
        raise CorpusQualityImportError("controlled corpus directory is invalid")
    target.chmod(0o700)
    return target.resolve()


def _private_database_path(database: Path) -> Path:
    path = database.expanduser().absolute()
    parent = path.parent
    if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
        raise CorpusQualityImportError("database parent must be a real directory")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise CorpusQualityImportError("database must be a regular file")
        path.chmod(0o600)
    else:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    return path


def _candidate_rows(manifest: Path) -> list[dict[str, object]]:
    path = manifest.expanduser()
    if path.is_symlink() or not path.is_file():
        raise CorpusQualityImportError(f"manifest is not a regular file: {path}")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise CorpusQualityImportError("candidate manifest exceeds size limit")
    rows: list[dict[str, object]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise CorpusQualityImportError(
                    f"manifest row {line_number} must be an object"
                )
            rows.append(value)
            if len(rows) > MAX_CANDIDATES:
                raise CorpusQualityImportError("candidate manifest has too many rows")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusQualityImportError("candidate manifest could not be read") from exc
    if not rows:
        raise CorpusQualityImportError("candidate manifest is empty")
    return rows


def _validated_candidate(row: dict[str, object], manifest: Path) -> tuple[str, Path]:
    if row.get("review_status") != "unreviewed" or "expected_decision" in row:
        raise CorpusQualityImportError("candidate rows must remain unreviewed suggestions")
    digest = row.get("content_sha256")
    source_value = row.get("path")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise CorpusQualityImportError("candidate content_sha256 is invalid")
    if not isinstance(source_value, str) or not source_value:
        raise CorpusQualityImportError("candidate path is invalid")
    images_root = (manifest.expanduser().parent / "images")
    if images_root.is_symlink() or not images_root.is_dir():
        raise CorpusQualityImportError("candidate images directory is invalid")
    source = Path(source_value).expanduser()
    try:
        source.relative_to(images_root)
    except ValueError as exc:
        raise CorpusQualityImportError("candidate path escapes manifest images directory") from exc
    if source.is_symlink() or not source.is_file():
        raise CorpusQualityImportError("candidate path is not a regular file")
    relative = source.relative_to(images_root)
    current = images_root
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise CorpusQualityImportError("candidate path contains a symlink")
    mode = os.lstat(source).st_mode
    if not stat.S_ISREG(mode):
        raise CorpusQualityImportError("candidate path is not a regular file")
    resolved_root = images_root.resolve()
    resolved_source = source.resolve()
    if resolved_root not in resolved_source.parents:
        raise CorpusQualityImportError("candidate path escapes manifest images directory")
    return digest, resolved_source


def _copy_verified(
    source: Path, destination: Path, thumbnail: Path, digest: str
) -> bool:
    _verify_source(source, digest)
    payload = source.read_bytes()
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise CorpusQualityImportError("controlled media destination is invalid")
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise CorpusQualityImportError("controlled media hash conflict")
        created = False
    else:
        _atomic_private_write(destination, payload)
        created = True
    _write_thumbnail(payload, thumbnail)
    return created


def _write_thumbnail(payload: bytes, destination: Path) -> None:
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise CorpusQualityImportError("controlled thumbnail destination is invalid")
        existing = destination.read_bytes()
        image = decode_image(
            existing,
            ImageLimits(max_bytes=512 * 1024, max_width=192, max_height=192),
        )
        if image.width > 192 or image.height > 192:
            raise CorpusQualityImportError("controlled thumbnail dimensions are invalid")
        return
    image = decode_image(payload, ImageLimits(max_bytes=MAX_IMAGE_BYTES))
    image.thumbnail((192, 192))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=82, optimize=True)
    _atomic_private_write(destination, output.getvalue())


def _atomic_private_write(destination: Path, payload: bytes) -> None:
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
        destination.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _verify_source(source: Path, digest: str) -> str:
    if source.stat().st_size > MAX_IMAGE_BYTES:
        raise CorpusQualityImportError("candidate image exceeds size limit")
    payload = source.read_bytes()
    if len(payload) > MAX_IMAGE_BYTES:
        raise CorpusQualityImportError("candidate image exceeds size limit")
    decode_image(payload, ImageLimits(max_bytes=MAX_IMAGE_BYTES))
    if hashlib.sha256(payload).hexdigest() != digest:
        raise CorpusQualityImportError("candidate image hash does not match manifest")
    return _image_suffix(source)


def _image_suffix(path: Path) -> str:
    payload = path.read_bytes()[:12]
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if payload.startswith(b"BM"):
        return ".bmp"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return ".webp"
    raise CorpusQualityImportError("candidate image signature is unsupported")
