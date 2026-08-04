"""Prepare private corpus candidates from the Hugging Face dataset viewer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from wy_media.image_safety import ImageLimits, decode_image


VIEWER_HOST = "datasets-server.huggingface.co"
VIEWER_BASE = f"https://{VIEWER_HOST}"
DATASET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MAX_TOTAL_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024

JsonFetcher = Callable[[str, int], dict[str, Any]]
BytesFetcher = Callable[[str, int], bytes]


class CandidateSourceError(ValueError):
    """Raised when remote candidate metadata violates the controlled contract."""


def collect_huggingface_archive_candidates(
    *,
    archive: Path,
    dataset: str,
    count: int,
    output_root: Path,
    source_url: str,
    license_name: str,
    style_candidate: str,
    decision_candidate: str,
) -> dict[str, object]:
    """Extract a bounded image subset from a locally downloaded dataset zip."""

    _validate_options(
        dataset=dataset,
        config="archive",
        split="archive",
        image_field="image",
        label_field="label",
        count=count,
        page_size=100,
        source_url=source_url,
        license_name=license_name,
        style_candidate=style_candidate,
        decision_candidate=decision_candidate,
    )
    resolved_archive = archive.expanduser().resolve()
    if not resolved_archive.is_file():
        raise CandidateSourceError("archive does not exist")
    if resolved_archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise CandidateSourceError("archive exceeds size limit")
    target = output_root.expanduser().resolve() / _dataset_slug(dataset)
    images = target / "images"
    images.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target, 0o700)
    os.chmod(images, 0o700)
    rows: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    total_output_bytes = 0
    try:
        with zipfile.ZipFile(resolved_archive) as bundle:
            members = sorted(bundle.infolist(), key=lambda item: item.filename)
            for member in members:
                if len(rows) >= count:
                    break
                if not _safe_zip_member(member):
                    continue
                with bundle.open(member) as source:
                    image_bytes = source.read(MAX_IMAGE_BYTES + 1)
                if len(image_bytes) > MAX_IMAGE_BYTES:
                    raise CandidateSourceError("archive image exceeds size limit")
                total_output_bytes += len(image_bytes)
                if total_output_bytes > MAX_TOTAL_OUTPUT_BYTES:
                    raise CandidateSourceError("candidate output exceeds total size limit")
                decode_image(image_bytes, ImageLimits(max_bytes=MAX_IMAGE_BYTES))
                digest = hashlib.sha256(image_bytes).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                destination = images / f"{digest}{_safe_suffix(image_bytes)}"
                _atomic_write(destination, image_bytes, mode=0o600)
                rows.append(
                    {
                        "sample_id": f"hf-{_dataset_slug(dataset)}-{len(rows):06d}",
                        "content_sha256": digest,
                        "path": str(destination),
                        "dataset": dataset,
                        "source_member": member.filename,
                        "source_url": source_url,
                        "license": license_name,
                        "style_candidate": style_candidate,
                        "decision_candidate": decision_candidate,
                        "review_status": "unreviewed",
                    }
                )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise CandidateSourceError(f"archive read failed: {type(exc).__name__}") from exc
    return _publish_candidates(target=target, rows=rows, count=count, dataset=dataset)


def collect_huggingface_candidates(
    *,
    dataset: str,
    config: str,
    split: str,
    image_field: str,
    label_field: str,
    label: int | str,
    count: int,
    output_root: Path,
    source_url: str,
    license_name: str,
    style_candidate: str,
    decision_candidate: str,
    page_size: int = 100,
    fetch_json: JsonFetcher | None = None,
    fetch_bytes: BytesFetcher | None = None,
) -> dict[str, object]:
    """Download bounded, unreviewed candidates without creating truth labels."""

    _validate_options(
        dataset=dataset,
        config=config,
        split=split,
        image_field=image_field,
        label_field=label_field,
        count=count,
        page_size=page_size,
        source_url=source_url,
        license_name=license_name,
        style_candidate=style_candidate,
        decision_candidate=decision_candidate,
    )
    json_fetcher = fetch_json or _fetch_json
    bytes_fetcher = fetch_bytes or _fetch_bytes
    target = output_root.expanduser().resolve() / _dataset_slug(dataset)
    images = target / "images"
    images.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target, 0o700)
    os.chmod(images, 0o700)

    rows: list[dict[str, object]] = []
    offset = 0
    total: int | None = None
    seen_hashes: set[str] = set()
    total_output_bytes = 0
    while len(rows) < count and (total is None or offset < total):
        length = min(page_size, count - len(rows) + page_size)
        payload = json_fetcher(
            _rows_url(dataset=dataset, config=config, split=split, offset=offset, length=length),
            MAX_METADATA_BYTES,
        )
        page = payload.get("rows")
        total_value = payload.get("num_rows_total")
        if not isinstance(page, list) or not isinstance(total_value, int) or total_value < 0:
            raise CandidateSourceError("viewer response has invalid rows or total")
        total = total_value
        if not page:
            break
        for wrapper in page:
            candidate = _candidate_row(
                wrapper,
                image_field=image_field,
                label_field=label_field,
                expected_label=label,
            )
            if candidate is None:
                continue
            source_row, image_url = candidate
            image_bytes = bytes_fetcher(image_url, MAX_IMAGE_BYTES)
            total_output_bytes += len(image_bytes)
            if total_output_bytes > MAX_TOTAL_OUTPUT_BYTES:
                raise CandidateSourceError("candidate output exceeds total size limit")
            decode_image(image_bytes, ImageLimits(max_bytes=MAX_IMAGE_BYTES))
            digest = hashlib.sha256(image_bytes).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            suffix = _safe_suffix(image_bytes)
            destination = images / f"{digest}{suffix}"
            _atomic_write(destination, image_bytes, mode=0o600)
            rows.append(
                {
                    "sample_id": f"hf-{_dataset_slug(dataset)}-{source_row}",
                    "content_sha256": digest,
                    "path": str(destination),
                    "dataset": dataset,
                    "config": config,
                    "split": split,
                    "source_row": source_row,
                    "source_label": label,
                    "source_url": source_url,
                    "license": license_name,
                    "style_candidate": style_candidate,
                    "decision_candidate": decision_candidate,
                    "review_status": "unreviewed",
                }
            )
            if len(rows) >= count:
                break
        offset += len(page)

    return _publish_candidates(target=target, rows=rows, count=count, dataset=dataset)


def _validate_options(**options: object) -> None:
    dataset = options["dataset"]
    if not isinstance(dataset, str) or not DATASET_RE.fullmatch(dataset):
        raise CandidateSourceError("dataset must use owner/name")
    for name in ("config", "split", "image_field", "label_field"):
        value = options[name]
        if not isinstance(value, str) or not NAME_RE.fullmatch(value):
            raise CandidateSourceError(f"invalid {name}")
    count = options["count"]
    page_size = options["page_size"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 5000:
        raise CandidateSourceError("count must be between 1 and 5000")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise CandidateSourceError("page_size must be between 1 and 100")
    for name in ("source_url", "license_name", "style_candidate", "decision_candidate"):
        value = options[name]
        if not isinstance(value, str) or not value.strip():
            raise CandidateSourceError(f"{name} is required")
    parsed_source = urllib.parse.urlsplit(str(options["source_url"]))
    try:
        source_port = parsed_source.port
    except ValueError as exc:
        raise CandidateSourceError("source_url has an invalid port") from exc
    if (
        parsed_source.scheme != "https"
        or parsed_source.hostname != "huggingface.co"
        or source_port not in {None, 443}
        or parsed_source.username is not None
        or parsed_source.password is not None
        or not parsed_source.path.startswith("/datasets/")
    ):
        raise CandidateSourceError("source_url must be an HTTPS huggingface.co URL")


def _rows_url(*, dataset: str, config: str, split: str, offset: int, length: int) -> str:
    query = urllib.parse.urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": length,
        }
    )
    return f"{VIEWER_BASE}/rows?{query}"


def _candidate_row(
    wrapper: object,
    *,
    image_field: str,
    label_field: str,
    expected_label: int | str,
) -> tuple[int, str] | None:
    if not isinstance(wrapper, dict):
        raise CandidateSourceError("viewer row wrapper must be an object")
    source_row = wrapper.get("row_idx")
    row = wrapper.get("row")
    if (
        isinstance(source_row, bool)
        or not isinstance(source_row, int)
        or source_row < 0
        or not isinstance(row, dict)
    ):
        raise CandidateSourceError("viewer row has invalid index or payload")
    if row.get(label_field) != expected_label:
        return None
    image = row.get(image_field)
    if not isinstance(image, dict) or not isinstance(image.get("src"), str):
        raise CandidateSourceError("matching row has no image source")
    image_url = str(image["src"])
    parsed = urllib.parse.urlsplit(image_url)
    try:
        image_port = parsed.port
    except ValueError as exc:
        raise CandidateSourceError("image source has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != VIEWER_HOST
        or image_port not in {None, 443}
        or not parsed.path.startswith("/cached-assets/")
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise CandidateSourceError("image source is outside the dataset viewer allowlist")
    return source_row, image_url


def _dataset_slug(dataset: str) -> str:
    return dataset.replace("/", "--")


def _safe_zip_member(member: zipfile.ZipInfo) -> bool:
    path = Path(member.filename)
    mode = member.external_attr >> 16
    if (
        member.is_dir()
        or path.is_absolute()
        or ".." in path.parts
        or stat.S_ISLNK(mode)
        or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
    ):
        return False
    if member.file_size < 1 or member.file_size > MAX_IMAGE_BYTES:
        raise CandidateSourceError("archive image has invalid size")
    if member.compress_size < 1 or member.file_size / member.compress_size > MAX_COMPRESSION_RATIO:
        raise CandidateSourceError("archive image exceeds compression ratio limit")
    return True


def _publish_candidates(
    *,
    target: Path,
    rows: list[dict[str, object]],
    count: int,
    dataset: str,
) -> dict[str, object]:
    manifest = target / "candidates.jsonl"
    rendered = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    _atomic_write(manifest, rendered.encode("utf-8"), mode=0o600)
    return {
        "kind": "wordyeah_huggingface_corpus_candidates",
        "status": "READY_FOR_REVIEW" if len(rows) == count else "INCOMPLETE",
        "dataset": dataset,
        "requested_count": count,
        "candidate_count": len(rows),
        "reviewed_count": 0,
        "ground_truth": False,
        "manifest": str(manifest),
    }


def _safe_suffix(payload: bytes) -> str:
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
    raise CandidateSourceError("decoded image has an unsupported signature")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _fetch_json(url: str, maximum: int) -> dict[str, Any]:
    payload = _fetch(url, maximum)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateSourceError(f"invalid viewer JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateSourceError("viewer response must be an object")
    return value


def _fetch_bytes(url: str, maximum: int) -> bytes:
    return _fetch(url, maximum)


def _fetch(url: str, maximum: int) -> bytes:
    opener = urllib.request.build_opener(_NoRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "WordYeah-Corpus/0.1"})
    try:
        with opener.open(request, timeout=30) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None and int(declared) > maximum:
                raise CandidateSourceError("remote payload exceeds size limit")
            payload = response.read(maximum + 1)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise CandidateSourceError(f"remote fetch failed: {type(exc).__name__}") from exc
    if len(payload) > maximum:
        raise CandidateSourceError("remote payload exceeds size limit")
    return payload


def _atomic_write(path: Path, payload: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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
