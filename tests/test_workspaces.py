from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wy_review import WorkspaceConflictError, WorkspaceStore


class WorkspaceStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = WorkspaceStore()

    def tearDown(self) -> None:
        self.store.close()

    def create(self, workspace_id: str, consumer_id: str):
        return self.store.create(
            workspace_id=workspace_id,
            consumer_id=consumer_id,
            name=f"Workspace {workspace_id}",
            adapter="cravatar",
            policy_profile="avatar-default",
        )

    def test_create_get_and_list_are_scoped_to_consumer(self) -> None:
        first = self.create("avatars", "consumer-a")
        second = self.create("avatars", "consumer-b")

        self.assertEqual(
            self.store.get("avatars", "consumer-a").consumer_id,
            "consumer-a",
        )
        self.assertEqual(self.store.list_workspaces("consumer-a"), [first])
        self.assertEqual(self.store.list_workspaces("consumer-b"), [second])
        self.assertEqual(self.store.list_workspaces("consumer-c"), [])

    def test_workspace_is_not_visible_to_another_consumer(self) -> None:
        self.create("private", "consumer-a")

        with self.assertRaises(KeyError):
            self.store.get("private", "consumer-b")

    def test_duplicate_workspace_id_and_consumer_is_rejected(self) -> None:
        self.create("avatars", "consumer-a")

        with self.assertRaises(WorkspaceConflictError):
            self.create("avatars", "consumer-a")

    def test_workspace_persists_when_database_is_reopened(self) -> None:
        with TemporaryDirectory() as directory:
            database = str(Path(directory) / "wordyeah.sqlite3")
            first_store = WorkspaceStore(database)
            created = first_store.create(
                workspace_id="avatars",
                consumer_id="consumer-a",
                name="Avatars",
                adapter="cravatar",
                policy_profile="avatar-default",
            )
            first_store.close()

            reopened = WorkspaceStore(database)
            self.assertEqual(reopened.get("avatars", "consumer-a"), created)
            reopened.close()

    def test_update_and_enable_changes_are_consumer_scoped(self) -> None:
        first = self.create("avatars", "consumer-a")
        second = self.create("avatars", "consumer-b")

        updated = self.store.update(
            "avatars",
            "consumer-a",
            name="Primary avatars",
            adapter="cravatar-shadow",
            policy_profile="avatar-strict",
            enabled=False,
        )
        self.assertEqual(updated.name, "Primary avatars")
        self.assertEqual(updated.adapter, "cravatar-shadow")
        self.assertEqual(updated.policy_profile, "avatar-strict")
        self.assertFalse(updated.enabled)
        self.assertEqual(updated.created_at, first.created_at)
        self.assertGreaterEqual(updated.updated_at, first.updated_at)

        untouched = self.store.get("avatars", "consumer-b")
        self.assertEqual(untouched, second)

        enabled = self.store.set_enabled("avatars", "consumer-a", True)
        self.assertTrue(enabled.enabled)
        with self.assertRaises(KeyError):
            self.store.set_enabled("avatars", "consumer-c", False)


if __name__ == "__main__":
    unittest.main()
