import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from wy_api.app import ApiSettings, create_app
from wy_media.falconsai import ImageScores
from wy_media.service import MediaModerationService
from wy_media.vision_provider import VisionReviewConclusion


class BoundaryClassifier:
    model_version = "test/boundary"
    ready = True

    def warmup(self) -> None:
        return

    def classify(self, image_bytes: bytes) -> ImageScores:
        return ImageScores(normal=0.45, nsfw=0.55)


class FakeAdvancedProvider:
    provider_name = "fake-advanced"
    model_id = "vision-test"
    enabled = True

    def review(self, request):
        return VisionReviewConclusion(
            decision="allow",
            confidence=0.97,
            reasons=("safe_avatar",),
            findings=(),
            evidence=(),
            provider=self.provider_name,
            model_id=self.model_id,
            model_version="1",
            prompt_version="avatar-v1",
            request_id=request.request_id,
        )


class DisabledAdvancedProvider(FakeAdvancedProvider):
    enabled = False


class AdvancedVisionApiTest(unittest.TestCase):
    def _image(self) -> bytes:
        output = io.BytesIO()
        Image.new("RGB", (8, 8), (80, 80, 80)).save(output, format="PNG")
        return output.getvalue()

    def _app(self, directory: str, provider):
        return create_app(
            settings=ApiSettings(
                database_path=str(Path(directory) / "wordyeah.sqlite3"),
                media_root=Path(directory) / "media",
                reviewer_token="review-test",
                review_session_secret="session-test",
            ),
            service=MediaModerationService(BoundaryClassifier()),
            advanced_vision_provider=provider,
        )

    def test_router_selected_stage_runs_provider_and_persists_attempt(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as directory:
            with TestClient(self._app(directory, FakeAdvancedProvider())) as client:
                moderated = client.post(
                    "/v1/moderate/image",
                    content=self._image(),
                    headers={"Content-Type": "image/png"},
                )
                self.assertEqual(moderated.status_code, 200)
                client.post("/review/login", json={"token": "review-test"})
                item_id = client.get("/review/items?status=all").json()["items"][0]["item_id"]
                response = client.post(f"/v1/review/items/{item_id}/advanced-vision")
                self.assertEqual(response.status_code, 201)
                payload = response.json()
                self.assertEqual(payload["attempt"]["stage"], "vision_review_1")
                self.assertEqual(payload["attempt"]["provider"], "fake-advanced")
                self.assertEqual(payload["route"]["state"], "auto_approved")

    def test_disabled_provider_fails_without_creating_attempt(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as directory:
            with TestClient(self._app(directory, DisabledAdvancedProvider())) as client:
                client.post(
                    "/v1/moderate/image",
                    content=self._image(),
                    headers={"Content-Type": "image/png"},
                )
                client.post("/review/login", json={"token": "review-test"})
                item_id = client.get("/review/items?status=all").json()["items"][0]["item_id"]
                response = client.post(f"/v1/review/items/{item_id}/advanced-vision")
                self.assertEqual(response.status_code, 503)
                attempts = client.get(f"/review/items/{item_id}/attempts").json()
                self.assertEqual(attempts["count"], 1)


if __name__ == "__main__":
    unittest.main()
