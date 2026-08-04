from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from wy_api.app import ApiSettings, create_app
from wy_core.contracts import ModerationResult
from wy_media.falconsai import ImageScores
from wy_media.service import MediaModerationService
from wy_review.store import ReviewStore


class Classifier:
    model_version = "fixture"
    ready = True

    def warmup(self) -> None:
        return None

    def classify(self, _payload: bytes) -> ImageScores:
        return ImageScores(normal=0.5, nsfw=0.5)


def _result(digest: str) -> ModerationResult:
    return ModerationResult(
        request_id="quality-request",
        content_sha256=digest,
        media_type="image",
        decision="review",
        reasons=("boundary",),
        model_versions={"fixture": "v1"},
    )


def test_reviewer_quality_sampling_labels_and_report_are_workspace_scoped() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "wordyeah.sqlite3")
        reviews = ReviewStore(database)
        default_item = reviews.enqueue(_result("a" * 64), "media://default.png", consumer_id="default")
        foreign_item = reviews.enqueue(_result("b" * 64), "media://foreign.png", consumer_id="other")
        app = create_app(
            settings=ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                local_review_no_auth=True,
            ),
            service=MediaModerationService(Classifier()),
            review_store=reviews,
        )
        with TestClient(app) as client:
            csrf = client.post("/review/login").json()["csrf_token"]
            headers = {"X-CSRF-Token": csrf}

            created = client.post(
                f"/review/items/{default_item.item_id}/quality-sample",
                json={"reason": "quality_sample", "stratum": "avatar", "csrf_token": csrf},
                headers=headers,
            )
            assert created.status_code == 201
            sample_id = created.json()["sample_id"]

            label = client.post(
                f"/review/items/{default_item.item_id}/quality-label",
                json={"label": "boundary", "note": "fixture", "csrf_token": csrf},
                headers=headers,
            )
            assert label.status_code == 201
            assert label.json()["label"] == "boundary"

            listing = client.get("/review/quality/samples")
            assert listing.status_code == 200
            assert listing.json()["report"]["status"] == "INCOMPLETE"
            assert [row["sample_id"] for row in listing.json()["samples"]] == [sample_id]
            assert sample_id[:12] in client.get("/review/quality").text

            first_review = client.post(
                f"/review/quality/samples/{sample_id}/decision",
                json={"decision": "allow", "csrf_token": csrf},
                headers=headers,
            )
            assert first_review.status_code == 200
            assert first_review.json()["status"] == "awaiting_reviews"

            forbidden = client.post(
                f"/review/items/{foreign_item.item_id}/quality-sample",
                json={"csrf_token": csrf},
                headers=headers,
            )
            assert forbidden.status_code == 404

            no_csrf = client.post(
                f"/review/items/{default_item.item_id}/quality-label",
                json={"label": "boundary"},
            )
            assert no_csrf.status_code == 403
