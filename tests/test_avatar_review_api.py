import tempfile
import unittest
import io
from pathlib import Path
from urllib.parse import urlencode

from PIL import Image

from wy_api.app import ApiSettings, create_app
from wy_api.review_ui import _avatar_state, _default_avatar_url
from wy_core.contracts import ModerationResult
from wy_media.falconsai import ImageScores
from wy_media.service import MediaModerationService
from wy_core.result_store import ResultStore
from wy_review.store import ReviewStore


class BlockClassifier:
    model_version = "test/avatar"
    ready = True

    def warmup(self) -> None:
        return

    def classify(self, image_bytes: bytes) -> ImageScores:
        return ImageScores(normal=0.45, nsfw=0.55)


class HighRiskClassifier(BlockClassifier):
    def classify(self, image_bytes: bytes) -> ImageScores:
        return ImageScores(normal=0.05, nsfw=0.95)


class AvatarReviewApiTest(unittest.TestCase):
    def test_avatar_state_uses_cravatar_default_and_blocked_semantics(self) -> None:
        default_url = _default_avatar_url(size=160)
        self.assertEqual(
            default_url,
            "https://cn.cravatar.com/avatar/00000000000000000000000000000000?s=160&d=mp&f=y",
        )
        self.assertIn('alt="默认头像"', _avatar_state("default", size=160))
        blocked = _avatar_state("blocked", size=512)
        self.assertIn('class="avatar-state is-blocked"', blocked)
        self.assertIn('alt="已屏蔽头像"', blocked)

    def _moderate_png(self, client, color: tuple[int, int, int]) -> dict[str, object]:
        image = io.BytesIO()
        Image.new("RGB", (8, 8), color).save(image, format="PNG")
        response = client.post(
            "/v1/moderate/image",
            content=image.getvalue(),
            headers={"Content-Type": "image/png"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _route_item_to_human_required(
        self,
        client,
        item_id: str,
        *,
        evidence: bool = True,
        category: str = "adult_nudity",
    ) -> dict[str, object]:
        evidence_rows = [{"kind": "crop", "ref": "media://review/evidence.png"}] if evidence else []
        first = client.post(
            f"/v1/review/items/{item_id}/attempts",
            json={
                "stage": "vision_review_1",
                "attempt_number": 1,
                "provider": "test",
                "model_id": "vision-a",
                "model_version": "1",
                "prompt_version": "avatar-v1",
                "decision": "review",
                "confidence": 0.60,
                "findings": [{"category": category, "label": "nsfw", "score": 0.60, "source": "vision-a"}],
                "evidence": evidence_rows,
            },
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["route"]["state"], "vision_review_2")
        second = client.post(
            f"/v1/review/items/{item_id}/attempts",
            json={
                "stage": "vision_review_2",
                "attempt_number": 1,
                "provider": "test",
                "model_id": "vision-b",
                "model_version": "1",
                "prompt_version": "avatar-v1",
                "decision": "review",
                "confidence": 0.58,
                "findings": [{"category": category, "label": "nsfw", "score": 0.58, "source": "vision-b"}],
                "evidence": evidence_rows,
            },
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["route"]["state"], "human_required")
        return second.json()["item"]

    def test_cravatar_refs_render_as_allowlisted_api_previews(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover - optional api extra
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "wordyeah.sqlite3")
            store = ReviewStore(database)
            avatar_hash = "0123456789abcdef0123456789abcdef"
            item = store.enqueue(
                ModerationResult(
                    request_id="cravatar-preview",
                    content_sha256="f" * 64,
                    media_type="image",
                    decision="review",
                    reasons=("manual_review",),
                    model_versions={"policy": "avatar-default"},
                ),
                f"cravatar://{avatar_hash}",
            )
            store.apply_route(
                item.item_id,
                stage="human_required",
                final_decision=None,
                reason_code="manual_review_queue",
            )
            settings = ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                reviewer_token="review-secret",
                review_session_secret="session-secret",
            )
            app = create_app(
                settings=settings,
                service=MediaModerationService(BlockClassifier()),
                review_store=store,
            )
            with TestClient(app) as client:
                client.post("/review/login", json={"token": "review-secret"})
                page = client.get("/review")
                self.assertIn(
                    f"https://cn.cravatar.com/avatar/{avatar_hash}?s=160&amp;d=404",
                    page.text,
                )
                self.assertIn("img-src 'self' https://cn.cravatar.com", page.headers["Content-Security-Policy"])

    def test_cravatar_sha256_refs_render_as_allowlisted_api_previews(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover - optional api extra
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "wordyeah.sqlite3")
            store = ReviewStore(database)
            avatar_hash = "0d8a67708287f0fed005312e85d66d6d8e965adec4b0e6055db632b5f2af2ca6"
            item = store.enqueue(
                ModerationResult(
                    request_id="cravatar-sha256-preview",
                    content_sha256="e" * 64,
                    media_type="image",
                    decision="review",
                    reasons=("manual_review",),
                    model_versions={"policy": "avatar-default"},
                ),
                f"cravatar://{avatar_hash}",
            )
            store.apply_route(
                item.item_id,
                stage="human_required",
                final_decision=None,
                reason_code="manual_review_queue",
            )
            settings = ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                reviewer_token="review-secret",
                review_session_secret="session-secret",
            )
            app = create_app(
                settings=settings,
                service=MediaModerationService(BlockClassifier()),
                review_store=store,
            )
            with TestClient(app) as client:
                client.post("/review/login", json={"token": "review-secret"})
                page = client.get("/review")
                self.assertIn(
                    f"https://cn.cravatar.com/avatar/{avatar_hash}?s=160&amp;d=404",
                    page.text,
                )

    def test_queue_views_and_bounded_batch_review(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover - optional api extra
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            settings = ApiSettings(
                database_path=str(Path(directory) / "wordyeah.sqlite3"),
                media_root=Path(directory) / "media",
                reviewer_token="review-secret",
                review_session_secret="session-secret",
                reviewer_id="alice",
            )
            app = create_app(settings=settings, service=MediaModerationService(BlockClassifier()))
            with TestClient(app) as client:
                for color in ((120, 80, 40), (40, 80, 120)):
                    self._moderate_png(client, color)

                login = client.post("/review/login", json={"token": "review-secret"})
                csrf = login.json()["csrf_token"]
                for item in client.get("/review/items?status=all").json()["items"]:
                    self._route_item_to_human_required(client, item["item_id"])
                items = client.get("/review/items").json()["items"]
                selected = [f"{item['item_id']}:{item['version']}" for item in items]

                queue_page = client.get("/review")
                self.assertEqual(queue_page.status_code, 200)
                self.assertIn('data-view="list"', queue_page.text)

                invalid_view = client.get("/review?view=bogus")
                self.assertEqual(invalid_view.status_code, 200)
                self.assertIn('data-view="list"', invalid_view.text)

                grid = client.get("/review?view=grid&batch=1")
                self.assertEqual(grid.status_code, 200)
                self.assertIn('data-view="grid"', grid.text)
                self.assertIn('data-batch-form', grid.text)
                self.assertEqual(grid.text.count('name="selected"'), 2)

                focus = client.get("/review?view=focus")
                self.assertEqual(focus.status_code, 200)
                self.assertIn("A 通过 · R 拒绝 · H 留置", focus.text)

                batch = client.post(
                    "/review/batch",
                    content=urlencode(
                        {"csrf_token": csrf, "action": "hold", "selected": selected},
                        doseq=True,
                    ),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                self.assertEqual(batch.status_code, 200)
                self.assertEqual(len(batch.json()["processed"]), 2)
                self.assertEqual(batch.json()["failures"], [])
                self.assertTrue(all(item["status"] == "held" for item in client.get("/review/items?status=held").json()["items"]))

    def test_login_review_and_optimistic_action(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover - optional api extra
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "wordyeah.sqlite3")
            settings = ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                reviewer_token="review-secret",
                review_session_secret="session-secret",
                reviewer_id="alice",
            )
            app = create_app(settings=settings, service=MediaModerationService(BlockClassifier()))
            with TestClient(app) as client:
                self.assertEqual(client.get("/review").status_code, 401)
                browser_unauthenticated = client.get(
                    "/review",
                    headers={"Accept": "text/html"},
                    follow_redirects=False,
                )
                self.assertEqual(browser_unauthenticated.status_code, 303)
                self.assertEqual(browser_unauthenticated.headers["location"], "/review/login?expired=1")
                moderation = self._moderate_png(client, (120, 80, 40))
                self.assertEqual(moderation["decision"], "review")

                login = client.post("/review/login", json={"token": "review-secret"})
                self.assertEqual(login.status_code, 200)
                csrf = login.json()["csrf_token"]
                pending_item = client.get("/review/items?status=all").json()["items"][0]
                self._route_item_to_human_required(client, pending_item["item_id"])
                for route in (
                    "overview", "agents", "policies", "quality", "history", "health", "account", "guide"
                ):
                    support_page = client.get(f"/review/{route}")
                    self.assertEqual(support_page.status_code, 200, route)
                    self.assertIn('class="side-nav"', support_page.text)

                listing = client.get("/review/items")
                self.assertEqual(listing.status_code, 200)
                self.assertEqual(listing.json()["count"], 1)
                item = listing.json()["items"][0]
                self.assertEqual(item["status"], "pending")
                self.assertEqual(item["stage"], "human_required")
                self.assertGreaterEqual(item["version"], 4)
                self.assertTrue(item["media_ref"].startswith("media://review/"))

                queue_page = client.get("/review")
                self.assertEqual(queue_page.status_code, 200)
                self.assertIn("审核队列", queue_page.text)
                self.assertIn('class="queue-list"', queue_page.text)
                self.assertIn('data-view="list"', queue_page.text)
                self.assertIn("page-tabs", queue_page.text)
                self.assertIn('class="side-nav"', queue_page.text)
                self.assertNotIn("Create Avatar", queue_page.text)
                self.assertNotIn("Agent plans", queue_page.text)

                reviewed_page = client.get("/review?status=reviewed")
                self.assertEqual(reviewed_page.status_code, 200)
                self.assertIn("已处理", reviewed_page.text)

                risk_page = client.get("/review?status=pending&risk=guarded&q=nsfw")
                self.assertEqual(risk_page.status_code, 200)
                self.assertIn(item["item_id"], risk_page.text)

                page = client.get(f"/review?focus={item['item_id']}")
                self.assertEqual(page.status_code, 200)
                self.assertIn("Controlled media preview", page.text)
                self.assertIn("Model finding summary", page.text)
                self.assertIn("Agent action log", page.text)
                self.assertIn("留置人工复核", page.text)
                self.assertIn('name="csrf_token"', page.text)
                self.assertIn('action="/review/logout"', page.text)

                preview = client.get(f"/review/items/{item['item_id']}/media")
                self.assertEqual(preview.status_code, 200)
                self.assertEqual(preview.headers["content-type"], "image/jpeg")

                missing_csrf = client.post(
                    f"/review/items/{item['item_id']}/approve",
                    json={"version": item["version"]},
                )
                self.assertEqual(missing_csrf.status_code, 403)

                approved = client.post(
                    f"/review/items/{item['item_id']}/approve",
                    json={"version": item["version"], "note": "manual safe"},
                    headers={"X-CSRF-Token": csrf, "X-Request-ID": "review-action-1"},
                )
                self.assertEqual(approved.status_code, 200)
                self.assertEqual(approved.json()["status"], "approved")
                self.assertEqual(approved.json()["version"], item["version"] + 1)

                stale = client.post(
                    f"/review/items/{item['item_id']}/approve",
                    json={"version": item["version"]},
                    headers={"X-CSRF-Token": csrf},
                )
                self.assertEqual(stale.status_code, 409)

                detail = client.get(f"/review/items/{item['item_id']}")
                self.assertEqual(detail.status_code, 200)
                self.assertEqual([event for event in detail.json()["events"] if event["action"] == "approve"][0]["request_id"], "review-action-1")
                page = client.get("/review")
                self.assertEqual(page.status_code, 200)
                self.assertIn("Content-Security-Policy", page.headers)

            result_store = ResultStore(database)
            self.assertEqual(result_store.count_runs("default"), 1)
            result_store.close()

    def test_high_confidence_block_is_rejected_without_human_review(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            settings = ApiSettings(
                database_path=str(Path(directory) / "wordyeah.sqlite3"),
                media_root=Path(directory) / "media",
                reviewer_token="review-secret",
            )
            app = create_app(settings=settings, service=MediaModerationService(HighRiskClassifier()))
            with TestClient(app) as client:
                image = io.BytesIO()
                Image.new("RGB", (8, 8), (180, 30, 30)).save(image, format="PNG")
                response = client.post(
                    "/v1/moderate/image",
                    content=image.getvalue(),
                    headers={"Content-Type": "image/png"},
                )
                self.assertEqual(response.status_code, 200)
                client.post("/review/login", json={"token": "review-secret"})
                listing = client.get("/review/items?status=all").json()
                self.assertEqual(listing["count"], 1)
                item = listing["items"][0]
                self.assertEqual(item["status"], "rejected")
                self.assertEqual(item["stage"], "auto_rejected")
                self.assertEqual(item["final_decision"], "block")
                attempts = client.get(f"/review/items/{item['item_id']}/attempts").json()
                self.assertEqual(attempts["count"], 1)
                self.assertEqual(attempts["attempts"][0]["stage"], "fast_scan")

    def test_agent_attempts_drive_first_and_second_visual_review(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            settings = ApiSettings(
                database_path=str(Path(directory) / "wordyeah.sqlite3"),
                media_root=Path(directory) / "media",
                reviewer_token="review-secret",
            )
            app = create_app(settings=settings, service=MediaModerationService(BlockClassifier()))
            with TestClient(app) as client:
                self._moderate_png(client, (80, 80, 80))
                client.post("/review/login", json={"token": "review-secret"})
                item = client.get("/review/items?status=all").json()["items"][0]
                first = client.post(
                    f"/v1/review/items/{item['item_id']}/attempts",
                    json={
                        "stage": "vision_review_1", "attempt_number": 1,
                        "provider": "test", "model_id": "vision-a", "model_version": "1",
                        "prompt_version": "avatar-v1", "decision": "review", "confidence": 0.60,
                    },
                )
                self.assertEqual(first.status_code, 201)
                self.assertEqual(first.json()["route"]["state"], "vision_review_2")
                second = client.post(
                    f"/v1/review/items/{item['item_id']}/attempts",
                    json={
                        "stage": "vision_review_2", "attempt_number": 1,
                        "provider": "test", "model_id": "vision-b", "model_version": "1",
                        "prompt_version": "avatar-v1", "decision": "allow", "confidence": 0.97,
                    },
                )
                self.assertEqual(second.status_code, 201)
                self.assertEqual(second.json()["route"]["state"], "auto_approved")
                self.assertEqual(second.json()["item"]["status"], "approved")
                self.assertEqual(second.json()["item"]["final_decision"], "allow")

    def test_review_media_serves_only_safe_controlled_image(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover - optional api extra
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "media"
            root.mkdir()
            output = io.BytesIO()
            Image.new("RGB", (3, 3), (40, 80, 120)).save(output, format="PNG")
            (root / "avatar.png").write_bytes(output.getvalue())
            database = str(Path(directory) / "wordyeah.sqlite3")
            review_store = ReviewStore(database)
            item = review_store.enqueue(
                ModerationResult(
                    request_id="media-review",
                    content_sha256="e" * 64,
                    media_type="image",
                    decision="review",
                    model_versions={"policy": "policy-test"},
                ),
                "media://avatar.png",
            )
            item = review_store.apply_route(
                item.item_id,
                stage="human_required",
                final_decision=None,
                reason_code="manual_review_queue",
            )
            review_store.close()
            settings = ApiSettings(
                database_path=database,
                media_root=root,
                reviewer_token="review-secret",
            )
            app = create_app(settings=settings, service=MediaModerationService(BlockClassifier()))
            with TestClient(app) as client:
                login = client.post("/review/login", json={"token": "review-secret"})
                self.assertEqual(login.status_code, 200)
                page = client.get(f"/review?focus={item.item_id}")
                self.assertEqual(page.status_code, 200)
                self.assertIn("Controlled media preview", page.text)
                self.assertIn(f'/review/items/{item.item_id}/media', page.text)
                media = client.get(f"/review/items/{item.item_id}/media")
                self.assertEqual(media.status_code, 200)
                self.assertEqual(media.headers["content-type"], "image/png")

                unsafe = client.get("/review/items/not-an-item/media")
                self.assertEqual(unsafe.status_code, 404)

    def test_focus_html_action_preserves_safe_return_to_and_advances_to_next_item(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            settings = ApiSettings(
                database_path=str(Path(directory) / "wordyeah.sqlite3"),
                media_root=Path(directory) / "media",
                reviewer_token="review-secret",
                review_session_secret="session-secret",
                reviewer_id="alice",
            )
            app = create_app(settings=settings, service=MediaModerationService(BlockClassifier()))
            with TestClient(app) as client:
                self._moderate_png(client, (20, 40, 60))
                self._moderate_png(client, (60, 40, 20))
                login = client.post("/review/login", json={"token": "review-secret"})
                csrf = login.json()["csrf_token"]
                for item in client.get("/review/items?status=all").json()["items"]:
                    self._route_item_to_human_required(client, item["item_id"])
                items = client.get("/review/items").json()["items"]
                current = items[0]
                next_item = items[1]
                return_to = (
                    f"/review?status=pending&risk=guarded&q=nsfw&view=focus&focus={current['item_id']}"
                )
                moved = client.post(
                    f"/review/items/{current['item_id']}/approve",
                    content=urlencode(
                        {
                            "csrf_token": csrf,
                            "version": current["version"],
                            "note": "manual safe",
                            "return_to": return_to,
                        }
                    ),
                    headers={
                        "Accept": "text/html",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    follow_redirects=False,
                )
                self.assertEqual(moved.status_code, 303)
                self.assertEqual(
                    moved.headers["location"],
                    f"/review?status=pending&risk=guarded&q=nsfw&view=focus&focus={next_item['item_id']}",
                )

                unsafe = client.post(
                    f"/review/items/{next_item['item_id']}/hold",
                    content=urlencode(
                        {
                            "csrf_token": csrf,
                            "version": next_item["version"],
                            "note": "need manual follow-up",
                            "return_to": "https://example.com/escape",
                        }
                    ),
                    headers={
                        "Accept": "text/html",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    follow_redirects=False,
                )
                self.assertEqual(unsafe.status_code, 303)
                self.assertEqual(unsafe.headers["location"], "/review")

    def test_batch_review_rejects_special_cases_and_reports_partial_failures(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError as exc:  # pragma: no cover
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "wordyeah.sqlite3")
            review_store = ReviewStore(database)
            settings = ApiSettings(
                database_path=database,
                media_root=Path(directory) / "media",
                reviewer_token="review-secret",
                review_session_secret="session-secret",
                reviewer_id="alice",
            )
            app = create_app(
                settings=settings,
                service=MediaModerationService(BlockClassifier()),
                review_store=review_store,
            )
            with TestClient(app) as client:
                for color in (
                    (10, 20, 30),
                    (30, 20, 10),
                    (40, 50, 60),
                    (60, 50, 40),
                    (70, 80, 90),
                ):
                    self._moderate_png(client, color)
                login = client.post("/review/login", json={"token": "review-secret"})
                csrf = login.json()["csrf_token"]
                staged_items = client.get("/review/items?status=all").json()["items"]
                ok_item = self._route_item_to_human_required(client, staged_items[0]["item_id"])
                appealed_item = self._route_item_to_human_required(client, staged_items[1]["item_id"])
                minor_item = self._route_item_to_human_required(
                    client, staged_items[2]["item_id"], category="minor_identity"
                )
                missing_evidence_item = self._route_item_to_human_required(
                    client, staged_items[3]["item_id"], evidence=False
                )
                non_human_item = client.get(f"/review/items/{staged_items[4]['item_id']}").json()["item"]

                review_store.connection.execute(
                    "UPDATE review_items SET appealed = 1 WHERE item_id = ?",
                    (appealed_item["item_id"],),
                )
                review_store.connection.commit()

                selected = [
                    f"{ok_item['item_id']}:{ok_item['version']}",
                    f"{appealed_item['item_id']}:{appealed_item['version']}",
                    f"{minor_item['item_id']}:{minor_item['version']}",
                    f"{missing_evidence_item['item_id']}:{missing_evidence_item['version']}",
                    f"{non_human_item['item_id']}:{non_human_item['version']}",
                ]

                missing_csrf = client.post(
                    "/review/batch",
                    content=urlencode({"action": "reject", "selected": selected}, doseq=True),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                self.assertEqual(missing_csrf.status_code, 403)

                over_limit = client.post(
                    "/review/batch",
                    content=urlencode(
                        {"csrf_token": csrf, "action": "reject", "selected": [selected[0]] * 51},
                        doseq=True,
                    ),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                self.assertEqual(over_limit.status_code, 400)
                self.assertIn("limited to 50 items", over_limit.json()["detail"])

                batch = client.post(
                    "/review/batch",
                    content=urlencode(
                        {"csrf_token": csrf, "action": "reject", "selected": selected},
                        doseq=True,
                    ),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                self.assertEqual(batch.status_code, 200)
                self.assertEqual(batch.json()["processed"], [ok_item["item_id"]])
                failures = {entry["item"]: entry["error"] for entry in batch.json()["failures"]}
                self.assertEqual(len(failures), 4)
                self.assertIn("appealed item cannot use ordinary batch review", failures[appealed_item["item_id"]])
                self.assertIn(
                    "political or minor-sensitive item cannot use ordinary batch review",
                    failures[minor_item["item_id"]],
                )
                self.assertIn(
                    "item is missing review evidence for ordinary batch review",
                    failures[missing_evidence_item["item_id"]],
                )
                self.assertIn(
                    "only pending human_required items can use batch review",
                    failures[non_human_item["item_id"]],
                )


if __name__ == "__main__":
    unittest.main()
