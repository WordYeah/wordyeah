import io
import tempfile
import time
import sqlite3
import unittest
from pathlib import Path

from PIL import Image

from wy_core.database import open_database
from wy_media.falconsai import ImageScores
from wy_media.service import MediaModerationService
from wy_jobs.store import JobStore
from wy_jobs.worker import JobWorker
from wy_api.app import ApiSettings, create_app


class FakeClassifier:
    model_version = "test/avatar"
    ready = True

    def warmup(self) -> None:
        return

    def classify(self, image_bytes: bytes) -> ImageScores:
        return ImageScores(normal=0.05, nsfw=0.95)


class JobsAndApiTest(unittest.TestCase):
    def test_job_lease_can_be_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "wordyeah.sqlite3")
            first_store = JobStore(database)
            first = first_store.enqueue("moderate_image", {"media_ref": "media://a.png"}, "cravatar")
            claimed = first_store.claim("worker-a", lease_seconds=1)
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.job_id, first.job_id)
            time.sleep(1.05)
            second_store = JobStore(database)
            recovered = second_store.claim("worker-b", lease_seconds=30)
            self.assertIsNotNone(recovered)
            self.assertEqual(recovered.job_id, first.job_id)
            self.assertEqual(recovered.attempts, 2)
            first_store.close()
            second_store.close()

    def test_job_heartbeat_validates_lease_duration(self) -> None:
        store = JobStore(":memory:")
        try:
            job = store.enqueue("fixture", {}, "consumer-a")
            store.claim("worker-a")
            with self.assertRaisesRegex(ValueError, "between 1 and 86400"):
                store.heartbeat(job.job_id, "worker-a", lease_seconds=0)
        finally:
            store.close()

    def test_job_persists_after_store_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "wordyeah.sqlite3")
            store = JobStore(database)
            created = store.enqueue("moderate_image", {"media_ref": "media://a.png"}, "cravatar")
            store.close()
            reopened = JobStore(database)
            loaded = reopened.get(created.job_id)
            self.assertEqual(loaded.status, "queued")
            self.assertEqual(loaded.payload["media_ref"], "media://a.png")
            reopened.close()

    def test_job_store_counts_active_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(str(Path(directory) / "wordyeah.sqlite3"))
            store.enqueue("moderate_image", {"media_ref": "media://a.png"}, "cravatar")
            self.assertEqual(store.count_active("cravatar"), 1)
            self.assertEqual(store.count_active("other"), 0)
            store.close()

    def test_job_claim_can_isolate_consumer_and_controlled_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(str(Path(directory) / "wordyeah.sqlite3"))
            ordinary = store.enqueue(
                "vision_review_1",
                {"context": "consumer=corpus-avatar; ground_truth=false"},
                "corpus-avatar",
            )
            selected = store.enqueue(
                "vision_review_1",
                {
                    "context": (
                        "consumer=corpus-avatar; quality_ai_prelabel=true; "
                        "ground_truth=false"
                    )
                },
                "corpus-avatar",
            )
            store.enqueue(
                "vision_review_1",
                {"context": "quality_ai_prelabel=true"},
                "other",
            )

            claimed = store.claim(
                "quality-worker",
                kinds=("vision_review_1",),
                consumer_id="corpus-avatar",
                context_marker="quality_ai_prelabel=true",
            )

            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.job_id, selected.job_id)
            self.assertEqual(store.get(ordinary.job_id).status, "queued")
            with self.assertRaisesRegex(ValueError, "context_marker"):
                store.claim("quality-worker", context_marker="")
            store.close()

    def test_worker_completes_claimed_job_with_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(str(Path(directory) / "wordyeah.sqlite3"))
            created = store.enqueue("moderate_image", {"media_ref": "media://a.png"}, "cravatar")
            worker = JobWorker(store, worker_id="worker-a")
            completed = worker.run_once(lambda job: {"job_id": job.job_id, "decision": "allow"})
            self.assertIsNotNone(completed)
            self.assertEqual(completed.status, "succeeded")
            self.assertEqual(store.get(created.job_id).result["decision"], "allow")
            store.close()

    def test_fastapi_image_and_controlled_job_contract(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover - optional api extra
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "wordyeah.sqlite3")
            settings = ApiSettings(database_path=database, media_root=Path(directory) / "media")
            app = create_app(settings=settings, service=MediaModerationService(FakeClassifier()))
            with TestClient(app) as client:
                self.assertEqual(client.get("/health/live").status_code, 200)
                self.assertEqual(client.get("/health/ready").status_code, 200)
                image = io.BytesIO()
                Image.new("RGB", (8, 8), (20, 40, 60)).save(image, format="PNG")
                response = client.post(
                    "/v1/moderate/image",
                    content=image.getvalue(),
                    headers={"Content-Type": "image/png"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["decision"], "block")

                job = client.post(
                    "/v1/jobs",
                    json={"kind": "moderate_image", "media_ref": "media://avatar.png"},
                )
                self.assertEqual(job.status_code, 202)
                self.assertEqual(client.get(f"/v1/jobs/{job.json()['job_id']}").status_code, 200)
                invalid = client.post(
                    "/v1/jobs",
                    json={"kind": "moderate_image", "media_ref": "https://example.invalid/a.png"},
                )
                self.assertEqual(invalid.status_code, 400)

    def test_fastapi_rejects_jobs_after_consumer_queue_limit(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover - optional api extra
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "wordyeah.sqlite3")
            settings = ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                max_queue_depth=1,
            )
            app = create_app(settings=settings, service=MediaModerationService(FakeClassifier()))
            with TestClient(app) as client:
                payload = {"kind": "moderate_image", "media_ref": "media://avatar.png"}
                self.assertEqual(client.post("/v1/jobs", json=payload).status_code, 202)
                response = client.post("/v1/jobs", json=payload)
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.headers["Retry-After"], "1")

    def test_missing_policy_keeps_api_alive_but_not_ready(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover - optional api extra
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            settings = ApiSettings(
                database_path=str(Path(directory) / "wordyeah.sqlite3"),
                media_root=Path(directory) / "media",
                policy_path=str(Path(directory) / "missing-policy.json"),
            )
            app = create_app(settings=settings)
            with TestClient(app) as client:
                self.assertEqual(client.get("/health/live").status_code, 200)
                ready = client.get("/health/ready")
                self.assertEqual(ready.status_code, 503)
                self.assertIn("policy file does not exist", ready.text)

    def test_non_loopback_bind_requires_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = ApiSettings(
                bind="0.0.0.0",
                database_path=str(Path(directory) / "wordyeah.sqlite3"),
                media_root=Path(directory) / "media",
            )
            with self.assertRaisesRegex(ValueError, "non-loopback bind"):
                create_app(settings=settings, service=MediaModerationService(FakeClassifier()))

    def test_schema_bootstrap_has_required_p1_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = open_database(str(Path(directory) / "wordyeah.sqlite3"))
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertTrue(
                {"submissions", "model_runs", "findings", "jobs", "policy_versions", "review_attempts"}
                <= names
            )
            connection.close()

    def test_schema_v1_database_is_upgraded_for_review_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.sqlite3"
            legacy = sqlite3.connect(database_path)
            legacy.executescript(Path("migrations/001_initial.sql").read_text(encoding="utf-8"))
            legacy.close()
            connection = open_database(str(database_path))
            columns = {row[1] for row in connection.execute("PRAGMA table_info(review_items)")}
            self.assertTrue(
                {
                    "consumer_id",
                    "policy_version",
                    "version",
                    "stage",
                    "final_decision",
                    "avatar_action",
                    "assignee",
                    "claim_until",
                    "quality_sample",
                    "arbitration_required",
                    "appealed",
                    "source_metadata_json",
                }
                <= columns
            )
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 6)
            connection.close()


if __name__ == "__main__":
    unittest.main()
