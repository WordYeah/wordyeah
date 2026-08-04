"""Read-only Cravatar export collection into a controlled local shadow manifest."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image


MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}


@dataclass(frozen=True)
class ExportRecord:
    job_id: int
    source_status: str
    source_start: str
    avatar_url: str
    email_hash: str
    image_md5: str


def read_export(path: Path) -> list[ExportRecord]:
    """Parse the metadata-only JSONL produced by the read-only WP exporter."""

    records: list[ExportRecord] = []
    seen: set[int] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            job_id = int(row["job_id"])
            email_hash = str(row["email_hash"]).lower()
            image_md5 = str(row["image_md5"]).lower()
            avatar_url = str(row["avatar_url"])
            source_status = str(row["source_status"])
            source_start = str(row["source_start"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid export row {line_number}: {exc}") from exc
        if job_id < 1 or job_id in seen:
            raise ValueError(f"invalid or duplicate job_id on row {line_number}")
        if len(email_hash) not in {32, 64} or not _is_hex(email_hash):
            raise ValueError(f"invalid email_hash on row {line_number}")
        if len(image_md5) != 32 or not _is_hex(image_md5):
            raise ValueError(f"invalid image_md5 on row {line_number}")
        if source_status not in {"completed", "failed", "waiting", "running"}:
            raise ValueError(f"invalid source_status on row {line_number}")
        _normalized_avatar_url(avatar_url, email_hash)
        seen.add(job_id)
        records.append(
            ExportRecord(
                job_id=job_id,
                source_status=source_status,
                source_start=source_start,
                avatar_url=avatar_url,
                email_hash=email_hash,
                image_md5=image_md5,
            )
        )
    return records


def collect_export(
    records: Iterable[ExportRecord],
    *,
    controlled_root: Path,
    manifest_path: Path,
    fetch: Callable[[str], bytes] | None = None,
) -> dict[str, object]:
    """Fetch allowlisted public avatars and atomically publish a shadow manifest."""

    controlled_root.mkdir(parents=True, exist_ok=True)
    os.chmod(controlled_root, 0o700)
    fetch_image = fetch or _fetch_image
    rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for record in records:
        public_url = _normalized_avatar_url(record.avatar_url, record.email_hash)
        try:
            payload = fetch_image(public_url)
            _validate_image(payload)
            digest = hashlib.sha256(payload).hexdigest()
            filename = f"{record.job_id}-{digest[:12]}.img"
            _atomic_write(controlled_root / filename, payload, mode=0o600)
            rows.append(
                {
                    "path": filename,
                    "avatar_ref": f"cravatar-job:{record.job_id}",
                    "request_id": f"cravatar-shadow-{record.job_id}",
                    "source_id": f"cravatar-job:{record.job_id}",
                    "content_sha256": digest,
                    "source_status": record.source_status,
                    "source_start": record.source_start,
                    "source_kind": "cavalcade-read-only-export",
                    "email_hash": record.email_hash,
                    "image_md5": record.image_md5,
                    "mutates_avatar": False,
                }
            )
        except Exception as exc:  # one bad remote object must not hide the rest of the export
            failures.append({"job_id": record.job_id, "error": str(exc)})

    manifest = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    _atomic_write(manifest_path, manifest.encode("utf-8"), mode=0o600)
    return {
        "kind": "cravatar_shadow_collection",
        "exported": len(rows),
        "failed": len(failures),
        "failures": failures,
        "manifest": str(manifest_path),
        "mutates_avatar": False,
    }


def _normalized_avatar_url(value: str, email_hash: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "cravatar.cn"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != f"/avatar/{email_hash}"
    ):
        raise ValueError("avatar_url must be the exact Cravatar public avatar path")
    return f"https://cn.cravatar.com/avatar/{email_hash}?s=256&d=404&r=x"


def _fetch_image(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "WordYeah-Cravatar-Shadow/1.0"})
    with urlopen(request, timeout=15) as response:  # noqa: S310 - URL is exact allowlisted above
        if response.geturl() != url:
            raise ValueError("avatar endpoint redirected outside the exact request URL")
        payload = response.read(MAX_IMAGE_BYTES + 1)
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("avatar exceeds byte limit")
    return payload


def _validate_image(payload: bytes) -> None:
    if not payload:
        raise ValueError("empty avatar response")
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("avatar exceeds byte limit")
    with Image.open(io.BytesIO(payload)) as image:
        if image.format not in ALLOWED_FORMATS:
            raise ValueError("unsupported avatar format")
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("avatar exceeds pixel limit")
        image.verify()


def _atomic_write(path: Path, payload: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
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


def _is_hex(value: str) -> bool:
    return all(character in "0123456789abcdef" for character in value)
