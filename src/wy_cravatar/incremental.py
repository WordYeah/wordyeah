from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from wy_media.image_safety import ImageLimits, decode_image

from .backlog import CravatarBacklog, CravatarBacklogRecord, _controlled_path


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_fingerprint(backlog: CravatarBacklog) -> str:
    digest = hashlib.sha256()
    for record in backlog.records:
        digest.update(record.source_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(record.content_sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _stream_key(workspace: str, source: str) -> str:
    if not workspace.strip() or not source.strip():
        raise ValueError("workspace and source must be non-empty")
    return json.dumps([workspace, source], ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class IncrementalOutcome:
    source_id: str
    status: Literal["submitted", "duplicate", "failed"]
    error: str | None = None
    mutates_avatar: Literal[False] = False


@dataclass(frozen=True)
class WatermarkSummary:
    workspace: str
    source: str
    paused: bool
    cursor: int
    source_count: int
    completed_count: int
    failed_count: int
    pending_count: int
    last_source_id: str | None
    updated_at: str
    mutates_avatar: Literal[False] = False

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace": self.workspace,
            "source": self.source,
            "paused": self.paused,
            "cursor": self.cursor,
            "source_count": self.source_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "pending_count": self.pending_count,
            "last_source_id": self.last_source_id,
            "updated_at": self.updated_at,
            "mutates_avatar": False,
        }


@dataclass(frozen=True)
class IncrementalRun:
    outcomes: tuple[IncrementalOutcome, ...]
    watermark: WatermarkSummary
    mutates_avatar: Literal[False] = False


class CravatarCursorStore:
    """Atomic local JSON cursor/failure store, isolated by workspace and source."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    @contextmanager
    def locked(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = self._read()
            try:
                yield state
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "streams": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid Cravatar cursor state: {exc}") from exc
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported Cravatar cursor state schema")
        if not isinstance(value.get("streams"), dict):
            raise ValueError("invalid Cravatar cursor streams")
        return value

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        fd, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


class CravatarIncrementalImporter:
    """Incrementally submit a local backlog without network or avatar mutation code.

    The injected callback is the only external boundary. ``source_id`` is the
    callback's durable idempotency key; successful IDs are persisted before a
    later run can submit them again.
    """

    def __init__(
        self,
        store: CravatarCursorStore,
        *,
        workspace: str,
        source: str = "cravatar",
    ) -> None:
        self.store = store
        self.workspace = workspace
        self.source = source
        self._key = _stream_key(workspace, source)

    def pause(self) -> WatermarkSummary:
        with self.store.locked() as state:
            stream = self._stream(state)
            stream["paused"] = True
            stream["updated_at"] = _now()
            self.store.save(state)
            return self._summary(stream)

    def resume(self) -> WatermarkSummary:
        with self.store.locked() as state:
            stream = self._stream(state)
            stream["paused"] = False
            stream["updated_at"] = _now()
            self.store.save(state)
            return self._summary(stream)

    def watermark(self) -> WatermarkSummary:
        with self.store.locked() as state:
            return self._summary(self._stream(state))

    def run(
        self,
        backlog: CravatarBacklog,
        *,
        controlled_root: Path,
        callback: Callable[[CravatarBacklogRecord, bytes], Any],
        limit: int | None = None,
        image_limits: ImageLimits | None = None,
    ) -> IncrementalRun:
        if not callable(callback):
            raise TypeError("submission callback must be callable")
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        root = controlled_root.resolve(strict=True)
        self._validate_backlog(backlog)

        with self.store.locked() as state:
            stream = self._prepare_stream(self._stream(state), backlog)
            if stream["paused"]:
                return IncrementalRun((), self._summary(stream))

            outcomes: list[IncrementalOutcome] = []
            examined = 0
            start = int(stream["cursor"])
            for index in range(start, len(backlog.records)):
                if limit is not None and examined >= limit:
                    break
                examined += 1
                record = backlog.records[index]
                stream["cursor"] = index + 1
                if record.source_id in stream["completed"]:
                    completed_hash = stream["completed"][record.source_id].get("content_sha256")
                    if completed_hash != record.content_sha256:
                        raise ValueError(
                            f"source_id content conflict: {record.source_id} was already completed"
                        )
                    outcomes.append(IncrementalOutcome(record.source_id, "duplicate"))
                    self._touch_and_save(state, stream)
                    continue
                outcome = self._submit_one(stream, record, root, callback, image_limits)
                outcomes.append(outcome)
                self._touch_and_save(state, stream)
            return IncrementalRun(tuple(outcomes), self._summary(stream))

    def replay_failed(
        self,
        backlog: CravatarBacklog,
        *,
        controlled_root: Path,
        callback: Callable[[CravatarBacklogRecord, bytes], Any],
        limit: int | None = None,
        image_limits: ImageLimits | None = None,
    ) -> IncrementalRun:
        if not callable(callback):
            raise TypeError("submission callback must be callable")
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        root = controlled_root.resolve(strict=True)
        self._validate_backlog(backlog)
        records = {record.source_id: record for record in backlog.records}

        with self.store.locked() as state:
            stream = self._prepare_stream(self._stream(state), backlog)
            if stream["paused"]:
                return IncrementalRun((), self._summary(stream))
            outcomes: list[IncrementalOutcome] = []
            failed_ids = list(stream["failures"])
            for source_id in failed_ids[:limit]:
                record = records.get(source_id)
                if record is None:
                    continue
                outcomes.append(self._submit_one(stream, record, root, callback, image_limits))
                self._touch_and_save(state, stream)
            return IncrementalRun(tuple(outcomes), self._summary(stream))

    def _stream(self, state: dict[str, Any]) -> dict[str, Any]:
        streams = state["streams"]
        stream = streams.get(self._key)
        if stream is None:
            stream = {
                "workspace": self.workspace,
                "source": self.source,
                "paused": False,
                "cursor": 0,
                "source_count": 0,
                "manifest_fingerprint": "",
                "completed": {},
                "failures": {},
                "last_source_id": None,
                "updated_at": _now(),
            }
            streams[self._key] = stream
        return stream

    def _prepare_stream(self, stream: dict[str, Any], backlog: CravatarBacklog) -> dict[str, Any]:
        fingerprint = _manifest_fingerprint(backlog)
        if stream["manifest_fingerprint"] != fingerprint:
            stream["cursor"] = 0
            stream["manifest_fingerprint"] = fingerprint
        stream["source_count"] = len(backlog.records)
        return stream

    @staticmethod
    def _validate_backlog(backlog: CravatarBacklog) -> None:
        source_ids: set[str] = set()
        for record in backlog.records:
            if not record.source_id:
                raise ValueError("incremental backlog records require source_id")
            if record.source_id in source_ids:
                raise ValueError(f"duplicate source_id in backlog: {record.source_id}")
            if record.mutates_avatar is not False or record.action != "record_only":
                raise RuntimeError("incremental contract must remain non-mutating")
            source_ids.add(record.source_id)

    @staticmethod
    def _submit_one(
        stream: dict[str, Any],
        record: CravatarBacklogRecord,
        root: Path,
        callback: Callable[[CravatarBacklogRecord, bytes], Any],
        image_limits: ImageLimits | None,
    ) -> IncrementalOutcome:
        try:
            path, _ = _controlled_path(record.source_path, root=root)
            payload = path.read_bytes()
            decode_image(payload, image_limits or ImageLimits())
            if hashlib.sha256(payload).hexdigest() != record.content_sha256:
                raise ValueError(f"content changed after import: {record.source_path}")
            callback_result = callback(record, payload)
            mutates_avatar = (
                callback_result.get("mutates_avatar")
                if isinstance(callback_result, dict)
                else getattr(callback_result, "mutates_avatar", False)
            )
            if mutates_avatar is not False and mutates_avatar is not None:
                raise RuntimeError("incremental callback returned a mutating result")
        except Exception as exc:  # The failure ledger must include injected transport failures.
            previous = stream["failures"].get(record.source_id, {})
            attempts = int(previous.get("attempts", 0)) + 1
            message = f"{type(exc).__name__}: {exc}"[:1000]
            stream["failures"][record.source_id] = {
                "attempts": attempts,
                "error": message,
                "failed_at": _now(),
                "content_sha256": record.content_sha256,
            }
            return IncrementalOutcome(record.source_id, "failed", message)

        completed_at = _now()
        stream["completed"][record.source_id] = {
            "content_sha256": record.content_sha256,
            "completed_at": completed_at,
        }
        stream["failures"].pop(record.source_id, None)
        stream["last_source_id"] = record.source_id
        return IncrementalOutcome(record.source_id, "submitted")

    def _touch_and_save(self, state: dict[str, Any], stream: dict[str, Any]) -> None:
        stream["updated_at"] = _now()
        self.store.save(state)

    def _summary(self, stream: dict[str, Any]) -> WatermarkSummary:
        source_count = int(stream["source_count"])
        completed_count = len(stream["completed"])
        failed_count = len(stream["failures"])
        pending_count = max(source_count - completed_count - failed_count, 0)
        return WatermarkSummary(
            workspace=self.workspace,
            source=self.source,
            paused=bool(stream["paused"]),
            cursor=int(stream["cursor"]),
            source_count=source_count,
            completed_count=completed_count,
            failed_count=failed_count,
            pending_count=pending_count,
            last_source_id=stream["last_source_id"],
            updated_at=str(stream["updated_at"]),
        )
