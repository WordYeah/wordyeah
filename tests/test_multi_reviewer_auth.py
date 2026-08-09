from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from wy_api.app import ApiSettings, ReviewerProfile, create_app
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
    profiles = (
        ReviewerProfile(
            reviewer_id="reviewer-a",
            username="reviewer-a",
            display_name="Reviewer A",
            role="senior_reviewer",
            workspace_ids=("default",),
        ),
        ReviewerProfile(
            reviewer_id="reviewer-b",
            username="reviewer-b",
            display_name="Reviewer B",
            role="reviewer",
            workspace_ids=("default",),
        ),
        ReviewerProfile(
            reviewer_id="arbitrator",
            username="arbitrator",
            display_name="Arbitrator",
            role="arbitrator",
            workspace_ids=("default",),
        ),
    )
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
                reviewer_profiles=profiles,
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
            assert "盲审封存 · 提交独立结论后显示" in quality_page.text
            assert "待 AI 预标注" not in quality_page.text
            assert 'name="decision" value="allow"' in quality_page.text
            assert 'name="decision" value="review"' in quality_page.text
            assert 'name="decision" value="block"' in quality_page.text
            first = client.post(
                f"/review/quality/samples/{sample_id}/decision",
                json={"decision": "allow", "csrf_token": csrf_a},
                headers={"X-CSRF-Token": csrf_a},
            )
            assert first.json()["status"] == "awaiting_reviews"

            csrf_b = _login(client, "reviewer-b", credentials["reviewer-b"])
            independent_page = client.get("/review/quality")
            assert "reviewer-a:allow" not in independent_page.text
            assert "待双人复核" in independent_page.text
            assert "盲审封存 · 提交独立结论后显示" in independent_page.text
            assert "待 AI 预标注" not in independent_page.text
            second = client.post(
                f"/review/quality/samples/{sample_id}/decision",
                json={"decision": "block", "csrf_token": csrf_b},
                headers={"X-CSRF-Token": csrf_b},
            )
            assert second.status_code == 200
            assert second.json()["status"] == "arbitration_required"
            assert second.json()["arbitration_required"] is True
            forbidden = client.post(
                f"/review/quality/samples/{sample_id}/arbitrate",
                json={"decision": "allow", "csrf_token": csrf_b},
                headers={"X-CSRF-Token": csrf_b},
            )
            assert forbidden.status_code == 403

            csrf_c = _login(client, "arbitrator", credentials["arbitrator"])
            assert "arbitrator" in client.get("/review/account").text
            arbitration_page = client.get("/review/quality")
            assert "reviewer-a:allow" in arbitration_page.text
            assert "reviewer-b:block" in arbitration_page.text
            assert "盲审封存 · 提交独立结论后显示" in arbitration_page.text
            assert "待 AI 预标注" not in arbitration_page.text
            assert f'/review/quality/samples/{sample_id}/arbitrate' in arbitration_page.text
            final = client.post(
                f"/review/quality/samples/{sample_id}/arbitrate",
                json={"decision": "allow", "csrf_token": csrf_c},
                headers={"X-CSRF-Token": csrf_c},
            )
            assert final.status_code == 200
            assert final.json()["status"] == "resolved"
            assert final.json()["final_decision"] == "allow"
            resolved_page = client.get("/review/quality")
            assert "待 AI 预标注" in resolved_page.text
            assert 'data-blinded="false"' in resolved_page.text

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


def test_authenticated_account_uses_profile_and_cravatar() -> None:
    token = "token-a-1234567890"
    profile = ReviewerProfile(
        reviewer_id="reviewer-a",
        username="alice",
        display_name="Alice Chen",
        email="alice@example.com",
        role="senior_reviewer",
        workspace_ids=("default",),
    )
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(
            settings=ApiSettings(
                database_path=str(Path(directory) / "wordyeah.sqlite3"),
                media_root=Path(directory) / "media",
                reviewer_credentials=(("reviewer-a", token),),
                reviewer_profiles=(profile,),
                review_session_secret="session-secret-for-tests",
            ),
            service=MediaModerationService(Classifier()),
        )
        with TestClient(app) as client:
            _login(client, "reviewer-a", token)
            page = client.get("/review/account")
            assert page.status_code == 200
            assert "Alice Chen" in page.text
            assert "alice@example.com" in page.text
            assert "senior_reviewer" in page.text
            assert profile.avatar_url.replace("&", "&amp;") in page.text
            assert "当前活动" in page.text
            assert "会话 ID" in page.text


def test_logout_revokes_persisted_reviewer_session() -> None:
    token = "token-a-1234567890"
    profile = ReviewerProfile(
        reviewer_id="reviewer-a",
        username="alice",
        display_name="Alice Chen",
        role="reviewer",
        workspace_ids=("default",),
    )
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "wordyeah.sqlite3")
        app = create_app(
            settings=ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                reviewer_credentials=(("reviewer-a", token),),
                reviewer_profiles=(profile,),
                review_session_secret="session-secret-for-tests",
            ),
            service=MediaModerationService(Classifier()),
        )
        with TestClient(app) as client:
            csrf = _login(client, "reviewer-a", token)
            response = client.post(
                "/review/logout",
                json={"csrf_token": csrf},
                headers={"X-CSRF-Token": csrf},
            )
            assert response.status_code == 200

        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT revoked_at FROM reviewer_sessions WHERE reviewer_id = ?",
                ("reviewer-a",),
            ).fetchone()
        assert row is not None
        assert row[0] is not None


def test_reviewer_credentials_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "WORDYEAH_REVIEWERS_JSON",
        '{"reviewer-b":"token-b-1234567890","reviewer-a":"token-a-1234567890"}',
    )
    settings = ApiSettings.from_env()
    assert settings.reviewer_credentials == (
        ("reviewer-a", "token-a-1234567890"),
        ("reviewer-b", "token-b-1234567890"),
    )

    monkeypatch.setenv("WORDYEAH_REVIEWERS_JSON", '{"reviewer-a":"short"}')
    with pytest.raises(ValueError, match="at least 16 characters"):
        ApiSettings.from_env()


def test_reviewer_profiles_load_and_build_cravatar_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "WORDYEAH_REVIEWER_PROFILES_JSON",
        '{"reviewer-a":{"username":"alice","display_name":"Alice Chen",'
        '"email":"Alice@Example.com","role":"senior_reviewer",'
        '"workspace_ids":["cravatar","motucloud"]}}',
    )
    settings = ApiSettings.from_env()
    assert settings.reviewer_profiles == (
        ReviewerProfile(
            reviewer_id="reviewer-a",
            username="alice",
            display_name="Alice Chen",
            email="alice@example.com",
            role="senior_reviewer",
            workspace_ids=("cravatar", "motucloud"),
        ),
    )
    assert settings.reviewer_profiles[0].avatar_url == (
        "https://cn.cravatar.com/avatar/c160f8cc69a4f0bf2b0362752353d060?s=96&d=mp&r=g"
    )

    monkeypatch.setenv(
        "WORDYEAH_REVIEWER_PROFILES_JSON",
        '{"reviewer-a":{"email":"not-an-email"}}',
    )
    with pytest.raises(ValueError, match="invalid profile fields"):
        ApiSettings.from_env()
