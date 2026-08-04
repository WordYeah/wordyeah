from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from wy_api.app import ApiSettings, create_app
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
