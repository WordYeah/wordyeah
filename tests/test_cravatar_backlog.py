import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from wy_cravatar.backlog import import_cravatar_backlog, submit_cravatar_backlog


ROOT = Path(__file__).resolve().parents[1]


def _image(path: Path, color: tuple[int, int, int]) -> str:
    Image.new("RGB", (12, 12), color).save(path, format="PNG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_jsonl_import_normalizes_and_deduplicates_by_content(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    first = images / "one.png"
    duplicate = images / "copy.png"
    digest = _image(first, (10, 20, 30))
    duplicate.write_bytes(first.read_bytes())
    manifest = tmp_path / "backlog.jsonl"
    manifest.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {"path": "one.png", "avatar_ref": "avatar:one", "consumer": "cravatar"},
                {"path": "copy.png", "avatar_ref": "avatar:duplicate"},
            )
        )
        + "\n",
        encoding="utf-8",
    )

    backlog = import_cravatar_backlog(manifest, controlled_root=images)

    assert backlog.source_count == 2
    assert backlog.duplicate_count == 1
    assert len(backlog.records) == 1
    record = backlog.records[0].to_dict()
    assert record["content_sha256"] == digest
    assert record["source_path"] == "one.png"
    assert record["source_metadata"] == {"consumer": "cravatar"}
    assert record["action"] == "record_only"
    assert record["mutates_avatar"] is False


def test_csv_and_json_manifests_are_supported(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _image(images / "one.png", (1, 2, 3))
    csv_manifest = tmp_path / "backlog.csv"
    with csv_manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["local_path", "request_id"])
        writer.writeheader()
        writer.writerow({"local_path": "one.png", "request_id": "req-1"})
    json_manifest = tmp_path / "backlog.json"
    json_manifest.write_text(json.dumps({"records": [{"image_path": "one.png"}]}), encoding="utf-8")

    csv_backlog = import_cravatar_backlog(csv_manifest, controlled_root=images)
    json_backlog = import_cravatar_backlog(json_manifest, controlled_root=images)

    assert csv_backlog.records[0].request_id == "req-1"
    assert json_backlog.records[0].avatar_ref == "cravatar-backlog://one.png"


@pytest.mark.parametrize(
    "row,error",
    [
        ({"path": "https://example.test/avatar.png"}, "remote image paths"),
        ({"path": "../outside.png"}, "escapes controlled root"),
        ({"path": "inside.png", "avatar_ref": "https://example.test/a"}, "remote avatar_ref"),
        ({"path": "inside.png", "content_sha256": "0" * 64}, "does not match"),
    ],
)
def test_import_rejects_remote_escape_and_hash_mismatch(
    tmp_path: Path, row: dict[str, str], error: str
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _image(images / "inside.png", (4, 5, 6))
    _image(tmp_path / "outside.png", (7, 8, 9))
    manifest = tmp_path / "backlog.json"
    manifest.write_text(json.dumps(row), encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        import_cravatar_backlog(manifest, controlled_root=images)


def test_enqueue_uses_only_injected_callback_and_stops_on_failure(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _image(images / "one.png", (11, 12, 13))
    _image(images / "two.png", (14, 15, 16))
    manifest = tmp_path / "backlog.json"
    manifest.write_text(json.dumps([{"path": "one.png"}, {"path": "two.png"}]), encoding="utf-8")
    backlog = import_cravatar_backlog(manifest, controlled_root=images)
    received: list[dict[str, object]] = []

    def enqueue(payload: dict[str, object]) -> str:
        assert payload["mutates_avatar"] is False
        assert payload["action"] == "record_only"
        received.append(payload)
        if len(received) == 2:
            raise RuntimeError("queue unavailable")
        return str(payload["request_id"])

    with pytest.raises(RuntimeError, match="queue unavailable"):
        backlog.enqueue(enqueue)
    assert len(received) == 2


def test_cli_writes_shadow_jsonl_and_reports_duplicates(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    first = images / "one.png"
    second = images / "two.png"
    _image(first, (20, 30, 40))
    second.write_bytes(first.read_bytes())
    manifest = tmp_path / "backlog.json"
    output = tmp_path / "normalized.jsonl"
    manifest.write_text(json.dumps([{"path": "one.png"}, {"path": "two.png"}]), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/cravatar_backlog_import.py",
            str(manifest),
            "--root",
            str(images),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stderr)
    assert report["record_count"] == 1
    assert report["duplicate_count"] == 1
    assert report["mutates_avatar"] is False
    normalized = json.loads(output.read_text(encoding="utf-8"))
    assert normalized["mutates_avatar"] is False


def test_submission_rechecks_content_and_stays_non_mutating(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    _image(images / "one.png", (23, 24, 25))
    manifest = tmp_path / "backlog.json"
    manifest.write_text(json.dumps([{"path": "one.png", "avatar_ref": "avatar:one"}]))
    backlog = import_cravatar_backlog(manifest, controlled_root=images)
    received: list[tuple[str, int]] = []

    results = submit_cravatar_backlog(
        backlog,
        controlled_root=images,
        callback=lambda record, payload: received.append((record.avatar_ref, len(payload))),
    )

    assert results == (None,)
    assert received[0][0] == "avatar:one"
    assert backlog.records[0].mutates_avatar is False

    _image(images / "one.png", (90, 91, 92))
    with pytest.raises(ValueError, match="content changed after import"):
        submit_cravatar_backlog(backlog, controlled_root=images, callback=lambda *_: None)
