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


def _login(client: TestClient, reviewer_id: str, token: str) -> str:
    response = client.post(
        "/review/login",
        json={"reviewer_id": reviewer_id, "token": token},
    )
    assert response.status_code == 200
    assert response.json()["reviewer"] == reviewer_id
    return response.json()["csrf_token"]


def test_three_reviewer_sessions_complete_independent_dual_review_and_arbitration() -> None:
    credentials = {
        "reviewer-a": "token-a-1234567890",
        "reviewer-b": "token-b-1234567890",
        "arbitrator": "token-c-1234567890",
    }
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "wordyeah.sqlite3")
        reviews = ReviewStore(database)
        item = reviews.enqueue(
            ModerationResult(
                request_id="multi-reviewer",
                content_sha256="c" * 64,
                media_type="image",
                decision="review",
                reasons=("boundary",),
                model_versions={"fixture": "v1"},
            ),
            "media://fixture.png",
            consumer_id="default",
        )
        app = create_app(
            settings=ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                reviewer_credentials=tuple(sorted(credentials.items())),
                review_session_secret="session-secret-for-tests",
            ),
            service=MediaModerationService(Classifier()),
            review_store=reviews,
        )
        with TestClient(app) as client:
            csrf_a = _login(client, "reviewer-a", credentials["reviewer-a"])
            sample_response = client.post(
                f"/review/items/{item.item_id}/quality-sample",
                json={"csrf_token": csrf_a},
                headers={"X-CSRF-Token": csrf_a},
            )
            assert sample_response.status_code == 201
            sample_id = sample_response.json()["sample_id"]
            quality_page = client.get("/review/quality")
            assert f'/review/quality/samples/{sample_id}/decision' in quality_page.text
            assert 'name="decision" value="allow"' in quality_page.text
            first = client.post(
                f"/review/quality/samples/{sample_id}/decision",
                json={"decision": "allow", "csrf_token": csrf_a},
                headers={"X-CSRF-Token": csrf_a},
            )
            assert first.json()["status"] == "awaiting_reviews"

            csrf_b = _login(client, "reviewer-b", credentials["reviewer-b"])
            second = client.post(
                f"/review/quality/samples/{sample_id}/decision",
                json={"decision": "block", "csrf_token": csrf_b},
                headers={"X-CSRF-Token": csrf_b},
            )
            assert second.status_code == 200
            assert second.json()["status"] == "arbitration_required"
            assert second.json()["arbitration_required"] is True

            csrf_c = _login(client, "arbitrator", credentials["arbitrator"])
            assert "arbitrator" in client.get("/review/account").text
            arbitration_page = client.get("/review/quality")
            assert f'/review/quality/samples/{sample_id}/arbitrate' in arbitration_page.text
            final = client.post(
                f"/review/quality/samples/{sample_id}/arbitrate",
                json={"decision": "allow", "csrf_token": csrf_c},
                headers={"X-CSRF-Token": csrf_c},
            )
            assert final.status_code == 200
            assert final.json()["status"] == "resolved"
            assert final.json()["final_decision"] == "allow"

            bad = client.post(
                "/review/login",
                json={"reviewer_id": "reviewer-a", "token": credentials["reviewer-b"]},
            )
            assert bad.status_code == 401


def test_multi_reviewer_login_page_requires_reviewer_id() -> None:
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(
            settings=ApiSettings(
                database_path=str(Path(directory) / "wordyeah.sqlite3"),
                reviewer_credentials=(
                    ("reviewer-a", "token-a-1234567890"),
                    ("reviewer-b", "token-b-1234567890"),
                ),
                review_session_secret="session-secret-for-tests",
            ),
            service=MediaModerationService(Classifier()),
        )
        with TestClient(app) as client:
            page = client.get("/review/login")
            assert page.status_code == 200
            assert 'name="reviewer_id"' in page.text
            assert 'autocomplete="username"' in page.text
