from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from wy_core.database import open_database


class WorkspaceConflictError(RuntimeError):
    """Raised when a consumer already has a workspace with the requested ID."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required(value: str, field: str, *, maximum: int = 128) -> str:
    if not value or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be between 1 and {maximum} characters")
    return value


@dataclass(frozen=True)
class Workspace:
    workspace_id: str
    consumer_id: str
    name: str
    adapter: str
    policy_profile: str
    enabled: bool
    created_at: str
    updated_at: str


class WorkspaceStore:
    """Consumer-scoped SQLite persistence for review workspace configuration."""

    def __init__(self, database: str = ":memory:") -> None:
        self.connection = open_database(database)
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
                workspace_id TEXT NOT NULL,
                consumer_id TEXT NOT NULL,
                name TEXT NOT NULL,
                adapter TEXT NOT NULL,
                policy_profile TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (workspace_id, consumer_id)
            );

            CREATE INDEX IF NOT EXISTS idx_workspaces_consumer
                ON workspaces(consumer_id, created_at, workspace_id);
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def create(
        self,
        *,
        workspace_id: str,
        consumer_id: str,
        name: str,
        adapter: str,
        policy_profile: str,
        enabled: bool = True,
    ) -> Workspace:
        self._validate_fields(
            workspace_id=workspace_id,
            consumer_id=consumer_id,
            name=name,
            adapter=adapter,
            policy_profile=policy_profile,
        )
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        now = _now()
        try:
            self.connection.execute(
                """
                INSERT INTO workspaces
                  (workspace_id, consumer_id, name, adapter, policy_profile,
                   enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    consumer_id,
                    name,
                    adapter,
                    policy_profile,
                    int(enabled),
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise WorkspaceConflictError(
                f"workspace already exists for consumer: {workspace_id}/{consumer_id}"
            ) from exc
        return self.get(workspace_id=workspace_id, consumer_id=consumer_id)

    def get(self, workspace_id: str, consumer_id: str) -> Workspace:
        _required(workspace_id, "workspace_id")
        _required(consumer_id, "consumer_id")
        row = self.connection.execute(
            """
            SELECT * FROM workspaces
            WHERE workspace_id = ? AND consumer_id = ?
            """,
            (workspace_id, consumer_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"workspace not found: {workspace_id}")
        return self._row(row)

    def list_workspaces(self, consumer_id: str) -> list[Workspace]:
        _required(consumer_id, "consumer_id")
        rows = self.connection.execute(
            """
            SELECT * FROM workspaces
            WHERE consumer_id = ?
            ORDER BY created_at, workspace_id
            """,
            (consumer_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def list_for_consumer(self, consumer_id: str) -> list[Workspace]:
        return self.list_workspaces(consumer_id)

    def update(
        self,
        workspace_id: str,
        consumer_id: str,
        *,
        name: str | None = None,
        adapter: str | None = None,
        policy_profile: str | None = None,
        enabled: bool | None = None,
    ) -> Workspace:
        _required(workspace_id, "workspace_id")
        _required(consumer_id, "consumer_id")
        changes: list[str] = []
        values: list[object] = []
        for field, value in (
            ("name", name),
            ("adapter", adapter),
            ("policy_profile", policy_profile),
        ):
            if value is not None:
                changes.append(f"{field} = ?")
                values.append(_required(value, field, maximum=256))
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be a boolean")
            changes.append("enabled = ?")
            values.append(int(enabled))
        if not changes:
            return self.get(workspace_id=workspace_id, consumer_id=consumer_id)

        changes.append("updated_at = ?")
        values.extend((_now(), workspace_id, consumer_id))
        cursor = self.connection.execute(
            f"""
            UPDATE workspaces SET {', '.join(changes)}
            WHERE workspace_id = ? AND consumer_id = ?
            """,
            values,
        )
        if cursor.rowcount != 1:
            self.connection.rollback()
            raise KeyError(f"workspace not found: {workspace_id}")
        self.connection.commit()
        return self.get(workspace_id=workspace_id, consumer_id=consumer_id)

    def set_enabled(
        self, workspace_id: str, consumer_id: str, enabled: bool
    ) -> Workspace:
        return self.update(
            workspace_id=workspace_id,
            consumer_id=consumer_id,
            enabled=enabled,
        )

    @staticmethod
    def _validate_fields(
        *,
        workspace_id: str,
        consumer_id: str,
        name: str,
        adapter: str,
        policy_profile: str,
    ) -> None:
        _required(workspace_id, "workspace_id")
        _required(consumer_id, "consumer_id")
        _required(name, "name", maximum=256)
        _required(adapter, "adapter", maximum=256)
        _required(policy_profile, "policy_profile", maximum=256)

    @staticmethod
    def _row(row: sqlite3.Row) -> Workspace:
        return Workspace(
            workspace_id=row["workspace_id"],
            consumer_id=row["consumer_id"],
            name=row["name"],
            adapter=row["adapter"],
            policy_profile=row["policy_profile"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
