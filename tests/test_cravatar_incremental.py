import json
import hashlib
from pathlib import Path

from PIL import Image

from wy_cravatar import CravatarCursorStore, CravatarIncrementalImporter
from wy_cravatar.backlog import import_cravatar_backlog
from wy_core.contracts import ModerationResult
from wy_cravatar.shadow import CravatarShadowConnector


def _backlog(tmp_path: Path, count: int = 3):
    images = tmp_path / "images"
    images.mkdir(exist_ok=True)
    rows = []
    for index in range(count):
        path = images / f"{index}.png"
        Image.new("RGB", (8, 8), (index, index + 1, index + 2)).save(path)
        rows.append({"path": path.name, "avatar_ref": f"avatar:{index}"})
    manifest = tmp_path / "backlog.json"
    manifest.write_text(json.dumps(rows), encoding="utf-8")
    return images, import_cravatar_backlog(manifest, controlled_root=images)


def test_stable_source_ids_and_repeated_run_are_idempotent(tmp_path: Path) -> None:
    images, backlog = _backlog(tmp_path, 2)
    reimported = import_cravatar_backlog(tmp_path / "backlog.json", controlled_root=images)
    assert [record.source_id for record in backlog.records] == [
        record.source_id for record in reimported.records
    ]
    assert all(record.source_id.startswith("cravatar-sha256:") for record in backlog.records)

    importer = CravatarIncrementalImporter(
        CravatarCursorStore(tmp_path / "cursor.json"), workspace="consumer-a"
    )
    received: list[str] = []
    first = importer.run(
        backlog,
        controlled_root=images,
        callback=lambda record, _: received.append(record.source_id),
    )
    second = importer.run(
        backlog,
        controlled_root=images,
        callback=lambda record, _: received.append(record.source_id),
    )

    assert len(received) == 2
    assert [outcome.status for outcome in first.outcomes] == ["submitted", "submitted"]
    assert second.outcomes == ()
    assert second.watermark.completed_count == 2
    assert second.watermark.pending_count == 0
    assert second.watermark.mutates_avatar is False


def test_shadow_record_carries_the_same_stable_source_id() -> None:
    content_sha256 = hashlib.sha256(b"local-avatar").hexdigest()
    result = ModerationResult(
        request_id="request-1",
        media_type="image",
        content_sha256=content_sha256,
        decision="allow",
        reasons=(),
        top_score=0.99,
        model_versions={"test": "1"},
        elapsed_ms=1,
    )

    record = CravatarShadowConnector(enabled=True).submit("avatar:one", result)

    assert record is not None
    assert record.source_id == f"cravatar-sha256:{content_sha256}"
    assert record.to_dict()["mutates_avatar"] is False


def test_cursor_persists_across_instances_and_manifest_growth(tmp_path: Path) -> None:
    images, backlog = _backlog(tmp_path, 3)
    state_path = tmp_path / "state" / "cursor.json"
    received: list[str] = []
    importer = CravatarIncrementalImporter(CravatarCursorStore(state_path), workspace="one")

    partial = importer.run(
        backlog,
        controlled_root=images,
        callback=lambda record, _: received.append(record.source_id),
        limit=1,
    )
    assert partial.watermark.cursor == 1
    assert partial.watermark.pending_count == 2

    restored = CravatarIncrementalImporter(CravatarCursorStore(state_path), workspace="one")
    finished = restored.run(
        backlog,
        controlled_root=images,
        callback=lambda record, _: received.append(record.source_id),
    )
    assert len(received) == 3
    assert finished.watermark.cursor == 3
    assert finished.watermark.completed_count == 3

    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert len(raw["streams"]) == 1


def test_cursor_retains_source_to_decision_audit_mapping(tmp_path: Path) -> None:
    images, backlog = _backlog(tmp_path, 1)
    state_path = tmp_path / "cursor.json"
    importer = CravatarIncrementalImporter(CravatarCursorStore(state_path), workspace="cravatar")
    importer.run(
        backlog,
        controlled_root=images,
        callback=lambda _record, _payload: {
            "request_id": "request-123",
            "decision": "review",
            "mutates_avatar": False,
        },
    )

    raw = json.loads(state_path.read_text(encoding="utf-8"))
    stream = next(iter(raw["streams"].values()))
    completed = next(iter(stream["completed"].values()))
    assert completed["request_id"] == "request-123"
    assert completed["decision"] == "review"


def test_failures_are_recorded_and_explicitly_replayed(tmp_path: Path) -> None:
    images, backlog = _backlog(tmp_path, 2)
    importer = CravatarIncrementalImporter(
        CravatarCursorStore(tmp_path / "cursor.json"), workspace="failures"
    )
    failed_id = backlog.records[0].source_id
    attempts: list[str] = []

    def flaky(record, _payload):
        attempts.append(record.source_id)
        if record.source_id == failed_id and attempts.count(failed_id) == 1:
            raise RuntimeError("shadow queue unavailable")

    run = importer.run(backlog, controlled_root=images, callback=flaky)
    assert [outcome.status for outcome in run.outcomes] == ["failed", "submitted"]
    assert run.watermark.failed_count == 1
    assert run.watermark.completed_count == 1

    replay = importer.replay_failed(backlog, controlled_root=images, callback=flaky)
    assert [outcome.status for outcome in replay.outcomes] == ["submitted"]
    assert replay.watermark.failed_count == 0
    assert replay.watermark.completed_count == 2
    assert attempts.count(failed_id) == 2


def test_pause_resume_and_workspace_isolation(tmp_path: Path) -> None:
    images, backlog = _backlog(tmp_path, 1)
    store = CravatarCursorStore(tmp_path / "cursor.json")
    first = CravatarIncrementalImporter(store, workspace="one")
    second = CravatarIncrementalImporter(store, workspace="two")
    received: list[str] = []

    paused = first.pause()
    assert paused.paused is True
    blocked = first.run(
        backlog,
        controlled_root=images,
        callback=lambda record, _: received.append(record.source_id),
    )
    assert blocked.outcomes == ()
    assert received == []

    assert second.watermark().paused is False
    second.run(
        backlog,
        controlled_root=images,
        callback=lambda record, _: received.append(record.source_id),
    )
    first.resume()
    resumed = first.run(
        backlog,
        controlled_root=images,
        callback=lambda record, _: received.append(record.source_id),
    )
    assert resumed.watermark.completed_count == 1
    assert len(received) == 2
    assert all(outcome.mutates_avatar is False for outcome in resumed.outcomes)


def test_changed_local_content_is_a_replayable_failure(tmp_path: Path) -> None:
    images, backlog = _backlog(tmp_path, 1)
    Image.new("RGB", (8, 8), (90, 91, 92)).save(images / "0.png")
    importer = CravatarIncrementalImporter(
        CravatarCursorStore(tmp_path / "cursor.json"), workspace="changed"
    )

    run = importer.run(backlog, controlled_root=images, callback=lambda *_: None)

    assert run.outcomes[0].status == "failed"
    assert "content changed after import" in (run.outcomes[0].error or "")
    assert run.watermark.failed_count == 1
    assert run.mutates_avatar is False


def test_mutating_callback_result_is_rejected_and_recorded(tmp_path: Path) -> None:
    images, backlog = _backlog(tmp_path, 1)
    importer = CravatarIncrementalImporter(
        CravatarCursorStore(tmp_path / "cursor.json"), workspace="mutation-guard"
    )

    run = importer.run(
        backlog,
        controlled_root=images,
        callback=lambda *_: {"mutates_avatar": True},
    )

    assert run.outcomes[0].status == "failed"
    assert "mutating result" in (run.outcomes[0].error or "")
    assert run.watermark.completed_count == 0
    assert run.watermark.failed_count == 1
