from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from wy_cravatar import __main__ as cli


def fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "images"
    root.mkdir()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(root / "avatar.png")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"path": "avatar.png"}]), encoding="utf-8")
    return root, manifest


def test_endpoint_rejects_non_loopback() -> None:
    try:
        cli._endpoint("https://example.com")
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("remote endpoint was accepted")


def test_pause_resume_and_watermark_commands(tmp_path: Path, capsys) -> None:
    state = tmp_path / "cursor.json"
    base = ["--workspace", "cravatar", "--state", str(state)]
    assert cli.main(["pause", *base]) == 0
    paused = json.loads(capsys.readouterr().out)
    assert paused["watermark"]["paused"] is True
    assert paused["mutates_avatar"] is False
    assert cli.main(["resume", *base]) == 0
    assert json.loads(capsys.readouterr().out)["watermark"]["paused"] is False
    assert cli.main(["watermark", *base]) == 0


def test_run_is_incremental_and_persists_watermark(tmp_path: Path, monkeypatch, capsys) -> None:
    root, manifest = fixture(tmp_path)
    state = tmp_path / "cursor.json"
    submitted: list[str] = []

    monkeypatch.setattr(
        cli,
        "_submitter",
        lambda _endpoint: lambda record, _payload: submitted.append(record.source_id)
        or {"mutates_avatar": False},
    )
    arguments = [
        "run",
        "--workspace",
        "cravatar",
        "--state",
        str(state),
        "--manifest",
        str(manifest),
        "--root",
        str(root),
    ]
    assert cli.main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["outcomes"][0]["status"] == "submitted"
    assert cli.main(arguments) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["outcomes"] == []
    assert second["watermark"]["completed_count"] == 1
    assert len(submitted) == 1


def test_failed_submission_returns_nonzero_and_is_replayable(tmp_path: Path, monkeypatch, capsys) -> None:
    root, manifest = fixture(tmp_path)
    state = tmp_path / "cursor.json"
    monkeypatch.setattr(
        cli, "_submitter", lambda _endpoint: lambda *_args: (_ for _ in ()).throw(RuntimeError("down"))
    )
    arguments = [
        "run", "--workspace", "cravatar", "--state", str(state),
        "--manifest", str(manifest), "--root", str(root),
    ]
    assert cli.main(arguments) == 2
    assert json.loads(capsys.readouterr().out)["watermark"]["failed_count"] == 1
    monkeypatch.setattr(
        cli, "_submitter", lambda _endpoint: lambda *_args: {"mutates_avatar": False}
    )
    assert cli.main(["replay", *arguments[1:]]) == 0
    assert json.loads(capsys.readouterr().out)["watermark"]["failed_count"] == 0
