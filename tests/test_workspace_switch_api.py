from __future__ import annotations

import io
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from wy_api.app import ApiSettings, ReviewerProfile, create_app
from wy_core.contracts import ModerationResult
from wy_media.falconsai import ImageScores
from wy_media.service import MediaModerationService
from wy_review.store import ReviewStore
from wy_review.workspace import WorkspaceStore


class Classifier:
    model_version = "fixture"
    ready = True

    def warmup(self) -> None:
        return None

    def classify(self, _payload: bytes) -> ImageScores:
        return ImageScores(normal=0.5, nsfw=0.5)


class AllowClassifier(Classifier):
    def classify(self, _payload: bytes) -> ImageScores:
        return ImageScores(normal=0.99, nsfw=0.01)


def result(digest: str) -> ModerationResult:
    return ModerationResult(
        request_id=f"request-{digest[0]}",
        content_sha256=digest,
        media_type="image",
        decision="review",
        reasons=("fixture",),
        model_versions={"policy": "avatar-default"},
    )


def test_reviewer_can_switch_between_isolated_workspace_queues() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "wordyeah.sqlite3")
        workspaces = WorkspaceStore(database)
        workspaces.create(
            workspace_id="default",
            consumer_id="default",
            name="Cravatar",
            adapter="cravatar",
            policy_profile="avatar-default",
        )
        workspaces.create(
            workspace_id="motucloud",
            consumer_id="default",
            name="MotuCloud",
            adapter="motucloud",
            policy_profile="avatar-default",
        )
        reviews = ReviewStore(database)
        default_item = reviews.enqueue(result("a" * 64), "media://default.png", consumer_id="default")
        motu_item = reviews.enqueue(result("b" * 64), "media://motu.png", consumer_id="motucloud")
        for consumer_id, item in (("default", default_item), ("motucloud", motu_item)):
            reviews.apply_route(
                item.item_id,
                stage="human_required",
                final_decision=None,
                reason_code="fixture",
                consumer_id=consumer_id,
            )
        app = create_app(
            settings=ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                local_review_no_auth=True,
            ),
            service=MediaModerationService(Classifier()),
            review_store=reviews,
            workspace_store=workspaces,
        )
        with TestClient(app) as client:
            csrf = client.post("/review/login").json()["csrf_token"]
            listing = client.get("/review/workspaces").json()
            assert listing["active_workspace_id"] == "default"
            assert {row["workspace_id"] for row in listing["workspaces"]} == {
                "default",
                "motucloud",
            }
            assert client.get("/review/items").json()["items"][0]["item_id"] == default_item.item_id
            page = client.get("/review")
            assert "/review/workspaces/motucloud/select" in page.text
            support_page = client.get("/review/quality")
            assert "/review/workspaces/motucloud/select" in support_page.text
            assert 'name="return_to" value="/review/quality"' in support_page.text

            selected = client.post(
                "/review/workspaces/motucloud/select",
                data={"csrf_token": csrf, "return_to": "/review/quality"},
                headers={"Accept": "text/html"},
                follow_redirects=False,
            )
            assert selected.status_code == 303
            assert selected.headers["location"] == "/review/quality"
            items = client.get("/review/items").json()["items"]
            assert [item["item_id"] for item in items] == [motu_item.item_id]
            assert client.get("/review/items/" + default_item.item_id).status_code == 404


def test_reviewer_workspace_scope_is_enforced_server_side() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "wordyeah.sqlite3")
        workspaces = WorkspaceStore(database)
        for workspace_id in ("default", "motucloud"):
            workspaces.create(
                workspace_id=workspace_id,
                consumer_id="default",
                name=workspace_id.title(),
                adapter="generic",
                policy_profile="avatar-default",
            )
        app = create_app(
            settings=ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                local_review_no_auth=True,
                reviewer_id="reviewer-a",
                reviewer_profiles=(
                    ReviewerProfile(
                        "reviewer-a",
                        "alice",
                        "Alice",
                        role="reviewer",
                        workspace_ids=("default",),
                    ),
                ),
            ),
            service=MediaModerationService(Classifier()),
            workspace_store=workspaces,
        )
        with TestClient(app) as client:
            csrf = client.post("/review/login").json()["csrf_token"]
            listing = client.get("/review/workspaces").json()
            assert [item["workspace_id"] for item in listing["workspaces"]] == ["default"]
            assert "/review/workspaces/motucloud/select" not in client.get("/review").text
            denied = client.post(
                "/review/workspaces/motucloud/select",
                data={"csrf_token": csrf},
                headers={"Accept": "text/html"},
            )
            assert denied.status_code == 403


def test_reviewer_role_blocks_blacklist_but_allows_normal_decision() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "wordyeah.sqlite3")
        reviews = ReviewStore(database)
        item = reviews.enqueue(result("c" * 64), "media://fixture.png", consumer_id="default")
        item = reviews.apply_route(
            item.item_id,
            stage="human_required",
            final_decision=None,
            reason_code="fixture",
            consumer_id="default",
        )
        app = create_app(
            settings=ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                local_review_no_auth=True,
                reviewer_id="reviewer-a",
                reviewer_profiles=(
                    ReviewerProfile(
                        "reviewer-a", "alice", "Alice", role="reviewer"
                    ),
                ),
            ),
            service=MediaModerationService(Classifier()),
            review_store=reviews,
        )
        with TestClient(app) as client:
            csrf = client.post("/review/login").json()["csrf_token"]
            denied = client.post(
                f"/review/items/{item.item_id}/blacklist",
                json={"csrf_token": csrf, "version": item.version},
                headers={"X-CSRF-Token": csrf},
            )
            assert denied.status_code == 403
            allowed = client.post(
                f"/review/items/{item.item_id}/approve",
                json={"csrf_token": csrf, "version": item.version},
                headers={"X-CSRF-Token": csrf},
            )
            assert allowed.status_code == 200
            assert allowed.json()["final_decision"] == "allow"


def test_api_submission_is_persisted_and_routed_to_requested_workspace() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "wordyeah.sqlite3")
        workspaces = WorkspaceStore(database)
        workspaces.create(
            workspace_id="default",
            consumer_id="default",
            name="Default",
            adapter="generic",
            policy_profile="avatar-default",
        )
        workspaces.create(
            workspace_id="cravatar",
            consumer_id="default",
            name="Cravatar",
            adapter="cravatar",
            policy_profile="avatar-default",
        )
        app = create_app(
            settings=ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                local_review_no_auth=True,
            ),
            service=MediaModerationService(Classifier()),
            workspace_store=workspaces,
        )
        image = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(image, format="PNG")
        headers = {
            "Content-Type": "image/png",
            "Content-Length": str(len(image.getvalue())),
            "X-WordYeah-Workspace": "cravatar",
            "X-WordYeah-Source-ID": "cravatar-job%3A123",
            "X-WordYeah-Source-Ref": "cravatar-avatar%3A123",
            "X-WordYeah-Source-Metadata": (
                "%7B%22avatar_origin%22%3A%22gravatar%22%2C"
                "%22origin_verified%22%3Atrue%2C"
                "%22image_md5%22%3A%22bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb%22%7D"
            ),
        }
        with TestClient(app) as client:
            response = client.post("/v1/moderate/image", content=image.getvalue(), headers=headers)
            assert response.status_code == 200
            assert response.headers["X-WordYeah-Workspace"] == "cravatar"
            assert app.state.result_store.decision_summary("cravatar") == {
                "total": 1,
                "allow": 0,
                "review": 1,
                "block": 0,
                "error": 0,
            }
            assert app.state.result_store.decision_summary("default")["total"] == 0
            review_items = app.state.review_store.list_items(consumer_id="cravatar")
            assert len(review_items) == 1
            assert review_items[0].source_id == "cravatar-job:123"
            assert review_items[0].source_ref == "cravatar-avatar:123"
            assert review_items[0].source_metadata == {
                "avatar_origin": "gravatar",
                "origin_verified": True,
                "image_md5": "b" * 32,
            }
            assert app.state.review_store.list_items(consumer_id="default") == []

            duplicate = client.post(
                "/v1/moderate/image", content=image.getvalue(), headers=headers
            )
            assert duplicate.status_code == 200
            assert app.state.result_store.decision_summary("cravatar")["total"] == 1
            assert len(app.state.review_store.list_items(consumer_id="cravatar")) == 1

            missing = client.post(
                "/v1/moderate/image",
                content=image.getvalue(),
                headers={**headers, "X-WordYeah-Workspace": "missing"},
            )
            assert missing.status_code == 404


def test_historical_allow_submission_is_forced_into_ai_review() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "wordyeah.sqlite3")
        workspaces = WorkspaceStore(database)
        workspaces.create(
            workspace_id="cravatar",
            consumer_id="default",
            name="Cravatar",
            adapter="cravatar",
            policy_profile="avatar-default",
        )
        app = create_app(
            settings=ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                local_review_no_auth=True,
            ),
            service=MediaModerationService(AllowClassifier()),
            workspace_store=workspaces,
        )
        image = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(image, format="PNG")
        headers = {
            "Content-Type": "image/png",
            "Content-Length": str(len(image.getvalue())),
            "X-WordYeah-Workspace": "cravatar",
            "X-WordYeah-Source-ID": "cravatar-job%3A456",
            "X-WordYeah-Source-Ref": "cravatar-avatar%3A456",
            "X-WordYeah-Source-Metadata": "%7B%22requires_ai_review%22%3Atrue%7D",
        }
        with TestClient(app) as client:
            response = client.post("/v1/moderate/image", content=image.getvalue(), headers=headers)
            assert response.status_code == 200
            assert response.json()["decision"] == "allow"

            items = app.state.review_store.list_items(
                status=None, consumer_id="cravatar"
            )
            assert len(items) == 1
            assert items[0].stage == "vision_review_1"
            assert items[0].source_metadata["requires_ai_review"] is True
            jobs = app.state.job_store.connection.execute(
                "SELECT kind, status FROM jobs WHERE consumer_id = ?",
                ("cravatar",),
            ).fetchall()
            assert [(row["kind"], row["status"]) for row in jobs] == [
                ("vision_review_1", "queued")
            ]

            invalid = client.post(
                "/v1/moderate/image",
                content=image.getvalue(),
                headers={
                    **headers,
                    "X-WordYeah-Source-ID": "cravatar-job%3A457",
                    "X-WordYeah-Source-Metadata": (
                        "%7B%22requires_ai_review%22%3A%22yes%22%7D"
                    ),
                },
            )
            assert invalid.status_code == 400


def test_registry_shadow_provenance_is_validated_and_persisted() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "wordyeah.sqlite3")
        workspaces = WorkspaceStore(database)
        workspaces.create(
            workspace_id="cravatar",
            consumer_id="default",
            name="Cravatar",
            adapter="cravatar",
            policy_profile="avatar-default",
        )
        app = create_app(
            settings=ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                local_review_no_auth=True,
            ),
            service=MediaModerationService(AllowClassifier()),
            workspace_store=workspaces,
        )
        image = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(image, format="PNG")
        metadata = (
            '{"source_kind":"registry-read-only-keyset",'
            '"registry_snapshot_id":"registry-canary-20260809-1000",'
            '"avatar_origin":"gravatar","origin_verified":true,'
            '"registry_status":0,"hash_type":"sha256",'
            f'"url_hash":"{"c" * 64}",'
            '"collection_url_host":"cn.cravatar.com",'
            f'"image_md5":"{"b" * 32}",'
            f'"collected_content_md5":"{"d" * 32}",'
            '"matches_registry_image_md5":false,"requires_ai_review":true}'
        )
        headers = {
            "Content-Type": "image/png",
            "Content-Length": str(len(image.getvalue())),
            "X-WordYeah-Workspace": "cravatar",
            "X-WordYeah-Source-ID": "cravatar-registry%3Afixture",
            "X-WordYeah-Source-Metadata": metadata,
        }
        with TestClient(app) as client:
            response = client.post("/v1/moderate/image", content=image.getvalue(), headers=headers)
            assert response.status_code == 200
            items = app.state.review_store.list_items(status=None, consumer_id="cravatar")
            assert len(items) == 1
            assert items[0].source_metadata["registry_snapshot_id"] == (
                "registry-canary-20260809-1000"
            )
            assert items[0].source_metadata["matches_registry_image_md5"] is False

            for invalid_metadata in (
                metadata.replace("cn.cravatar.com", "cravatar.example"),
                metadata.replace("registry-canary-20260809-1000", "bad snapshot"),
                metadata.replace("c" * 64, "C" * 64),
            ):
                invalid = client.post(
                    "/v1/moderate/image",
                    content=image.getvalue(),
                    headers={
                        **headers,
                        "X-WordYeah-Source-ID": "cravatar-registry%3Ainvalid",
                        "X-WordYeah-Source-Metadata": invalid_metadata,
                    },
                )
                assert invalid.status_code == 400


def test_forced_ai_submission_backpressure_is_replayable() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "wordyeah.sqlite3")
        workspaces = WorkspaceStore(database)
        workspaces.create(
            workspace_id="cravatar",
            consumer_id="default",
            name="Cravatar",
            adapter="cravatar",
            policy_profile="avatar-default",
        )
        app = create_app(
            settings=ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                local_review_no_auth=True,
                max_queue_depth=1,
            ),
            service=MediaModerationService(AllowClassifier()),
            workspace_store=workspaces,
        )
        app.state.job_store.enqueue("fixture", {"fixture": True}, "cravatar")
        image = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(image, format="PNG")
        headers = {
            "Content-Type": "image/png",
            "Content-Length": str(len(image.getvalue())),
            "X-WordYeah-Workspace": "cravatar",
            "X-WordYeah-Source-ID": "cravatar-registry%3Abackpressure",
            "X-WordYeah-Source-Metadata": "%7B%22requires_ai_review%22%3Atrue%7D",
        }
        with TestClient(app) as client:
            full = client.post("/v1/moderate/image", content=image.getvalue(), headers=headers)
            assert full.status_code == 429
            held = app.state.review_store.get_by_source_id(
                "cravatar-registry:backpressure", consumer_id="cravatar"
            )
            assert held.stage == "model_error"

            fixture_job = app.state.job_store.connection.execute(
                "SELECT job_id FROM jobs WHERE kind='fixture'"
            ).fetchone()["job_id"]
            app.state.job_store.cancel(fixture_job)
            replay = client.post("/v1/moderate/image", content=image.getvalue(), headers=headers)
            assert replay.status_code == 200
            recovered = app.state.review_store.get_by_source_id(
                "cravatar-registry:backpressure", consumer_id="cravatar"
            )
            assert recovered.stage == "vision_review_1"
            assert recovered.status == "pending"
            jobs = app.state.job_store.connection.execute(
                "SELECT kind, status FROM jobs WHERE kind='vision_review_1'"
            ).fetchall()
            assert [(row["kind"], row["status"]) for row in jobs] == [
                ("vision_review_1", "queued")
            ]


def test_workspace_definitions_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "WORDYEAH_WORKSPACES_JSON",
        '{"cravatar":{"name":"Cravatar","adapter":"cravatar"},'
        '"motucloud":{"name":"MotuCloud","adapter":"motucloud","enabled":false}}',
    )
    settings = ApiSettings.from_env()
    assert settings.workspace_definitions == (
        ("cravatar", "Cravatar", "cravatar", "avatar-default", True),
        ("motucloud", "MotuCloud", "motucloud", "avatar-default", False),
    )
