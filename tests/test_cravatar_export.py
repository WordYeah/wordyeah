from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from wy_cravatar import export as export_module
from wy_cravatar.backlog import import_cravatar_backlog
from wy_cravatar.export import collect_export, read_export


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(output, format="PNG")
    return output.getvalue()


def _export(path: Path, *, url: str | None = None, origin: str = "gravatar") -> None:
    email_hash = "a" * 32
    path.write_text(
        json.dumps(
            {
                "job_id": 42,
                "source_status": "completed",
                "source_start": "2026-08-03 12:00:00",
                "avatar_url": url or f"https://cravatar.com/avatar/{email_hash}",
                "email_hash": email_hash,
                "image_md5": "b" * 32,
                "avatar_origin": origin,
                "registry_status": 0,
                "registry_url": url or f"https://cravatar.com/avatar/{email_hash}",
                "mutates_avatar": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_collect_export_publishes_atomic_non_mutating_manifest(tmp_path: Path) -> None:
    source = tmp_path / "export.jsonl"
    root = tmp_path / "images"
    manifest = tmp_path / "manifest.jsonl"
    _export(source)
    payload = _png()
    urls: list[str] = []

    report = collect_export(
        read_export(source),
        controlled_root=root,
        manifest_path=manifest,
        fetch=lambda url: urls.append(url) or payload,
    )

    assert report["exported"] == 1
    assert report["failed"] == 0
    assert report["mutates_avatar"] is False
    assert urls == [f"https://cn.cravatar.com/avatar/{'a' * 32}?s=256&d=404&r=x"]
    row = json.loads(manifest.read_text(encoding="utf-8"))
    assert row["source_id"] == "cravatar-job:42"
    assert row["content_sha256"] == hashlib.sha256(payload).hexdigest()
    assert row["mutates_avatar"] is False
    assert row["avatar_origin"] == "gravatar"
    assert row["origin_verified"] is True
    assert row["collected_content_md5"] == hashlib.md5(
        payload, usedforsecurity=False
    ).hexdigest()
    assert row["matches_queued_image_md5"] is False
    assert row["requires_ai_review"] is True
    assert (root / row["path"]).read_bytes() == payload
    assert manifest.stat().st_mode & 0o777 == 0o600
    backlog = import_cravatar_backlog(manifest, controlled_root=root)
    assert backlog.records[0].source_id == "cravatar-job:42"
    assert backlog.records[0].mutates_avatar is False
    assert backlog.records[0].action == "record_only"


@pytest.mark.parametrize(
    "url",
    (
        "http://cravatar.com/avatar/" + "a" * 32,
        "https://evil.example/avatar/" + "a" * 32,
        "https://cravatar.com/avatar/" + "a" * 32 + "?x=1",
        "https://cravatar.com/avatar/" + "c" * 32,
    ),
)
def test_export_rejects_non_exact_avatar_urls(tmp_path: Path, url: str) -> None:
    source = tmp_path / "export.jsonl"
    _export(source, url=url)
    with pytest.raises(ValueError, match="exact Cravatar public avatar path"):
        read_export(source)


def test_bad_image_is_reported_without_publishing_it(tmp_path: Path) -> None:
    source = tmp_path / "export.jsonl"
    manifest = tmp_path / "manifest.jsonl"
    _export(source)
    report = collect_export(
        read_export(source),
        controlled_root=tmp_path / "images",
        manifest_path=manifest,
        fetch=lambda _url: b"not-an-image",
    )
    assert report["exported"] == 0
    assert report["failed"] == 1
    assert manifest.read_text(encoding="utf-8") == ""


def test_collect_export_rejects_unbounded_worker_count(tmp_path: Path) -> None:
    source = tmp_path / "export.jsonl"
    _export(source)
    with pytest.raises(ValueError, match="workers must be between"):
        collect_export(
            read_export(source),
            controlled_root=tmp_path / "images",
            manifest_path=tmp_path / "manifest.jsonl",
            fetch=lambda _url: _png(),
            workers=33,
        )


def test_export_requires_explicit_valid_avatar_origin(tmp_path: Path) -> None:
    source = tmp_path / "export.jsonl"
    _export(source, origin="mirror")
    with pytest.raises(ValueError, match="invalid avatar_origin"):
        read_export(source)


def test_network_fetch_rejects_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self) -> str:
            return "https://evil.example/avatar"

        def read(self, _limit: int) -> bytes:
            return _png()

    monkeypatch.setattr(export_module, "urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(ValueError, match="redirected"):
        export_module._fetch_image(
            f"https://cn.cravatar.com/avatar/{'a' * 32}?s=256&d=404&r=x"
        )
