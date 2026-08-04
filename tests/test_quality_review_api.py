from __future__ import annotations

import hashlib
import io
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from wy_api.app import ApiSettings, create_app
from wy_core.contracts import ModerationResult
from wy_media.falconsai import ImageScores
from wy_media.service import MediaModerationService
from wy_review.store import ReviewStore
from wy_review.quality import QualityStore
from wy_review.corpus_quality_import import import_candidate_manifests


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
                json={"decision": "review", "csrf_token": csrf},
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


def test_imported_corpus_sample_has_session_protected_controlled_preview() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "candidates" / "images"
        source.mkdir(parents=True)
        output = io.BytesIO()
        Image.new("RGB", (24, 24), color="purple").save(output, format="PNG")
        payload = output.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        image = source / f"{digest}.png"
        image.write_bytes(payload)
        manifest = source.parent / "candidates.jsonl"
        manifest.write_text(
            json.dumps(
                {
                    "content_sha256": digest,
                    "path": str(image),
                    "review_status": "unreviewed",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        database = root / "wordyeah.sqlite3"
        media_root = root / "media"
        import_candidate_manifests(
            [("boundary", manifest)],
            database=database,
            media_root=media_root,
            consumer_id="corpus-avatar",
        )
        app = create_app(
            settings=ApiSettings(
                database_path=str(database),
                media_root=media_root,
                consumer_id="corpus-avatar",
                local_review_no_auth=True,
            ),
            service=MediaModerationService(Classifier()),
        )
        with TestClient(app) as client:
            page = client.get("/review/quality")
            assert page.status_code == 200
            sample_id = client.get("/review/quality/samples").json()["samples"][0]["sample_id"]
            preview_url = f"/review/quality/samples/{sample_id}/media"
            assert preview_url in page.text
            preview = client.get(preview_url)
            assert preview.status_code == 200
            assert preview.headers["content-type"] == "image/png"
            assert preview.headers["cache-control"] == "private, no-store"
            assert preview.content == payload
            controlled_original = media_root / "corpus" / "corpus-avatar" / f"{digest}.png"
            controlled_original.unlink()
            controlled_original.symlink_to(root / "outside.png")
            (root / "outside.png").write_bytes(payload)
            assert client.get(preview_url).status_code == 404
            thumbnail = client.get(
                f"/review/quality/samples/{sample_id}/thumbnail"
            )
            assert thumbnail.status_code == 200
            assert thumbnail.headers["content-type"] == "image/jpeg"
            assert len(thumbnail.content) < len(payload) or len(thumbnail.content) < 512 * 1024

            csrf = client.post("/review/login").json()["csrf_token"]
            decision = client.post(
                f"/review/quality/samples/{sample_id}/decision",
                data={"decision": "review", "csrf_token": csrf, "offset": "24"},
                headers={"Accept": "text/html"},
                follow_redirects=False,
            )
            assert decision.status_code == 303
            assert decision.headers["location"] == "/review/quality?offset=24"


def test_quality_page_defaults_to_frozen_batch_and_preserves_batch_navigation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database = root / "wordyeah.sqlite3"
        store = QualityStore(str(database))
        store.create_vocabulary(consumer_id="corpus-avatar")
        samples = [
            store.create_sample(
                consumer_id="corpus-avatar", item_id=f"sample-{index}",
                content_sha256=f"{index:064x}",
                media_ref=f"media://fixture/{index}.png", reason="quality_sample",
                stratum="boundary", retention_status="private_corpus",
            )
            for index in range(2)
        ]
        store.create_review_batch(
            consumer_id="corpus-avatar", batch_id="frozen-ui",
            source_sha256="a" * 64, fraction=0.5, seed="ui-seed",
            items=((samples[1].sample_id, "boundary"),),
        )
        store.create_review_batch(
            consumer_id="corpus-avatar", batch_id="primary-ui",
            source_sha256="a" * 64, fraction=1.0, seed="ui-seed",
            items=tuple((sample.sample_id, "boundary") for sample in samples),
            required_reviewers=1,
        )
        store.configure_review_requirements(
            consumer_id="corpus-avatar",
            primary_sample_ids=tuple(sample.sample_id for sample in samples),
            dual_review_sample_ids=(samples[1].sample_id,),
        )
        store.close()
        app = create_app(
            settings=ApiSettings(
                database_path=str(database), media_root=root / "media",
                consumer_id="corpus-avatar", local_review_no_auth=True,
            ),
            service=MediaModerationService(Classifier()),
        )
        with TestClient(app) as client:
            page = client.get("/review/quality")
            assert page.status_code == 200
            assert samples[1].sample_id[:12] in page.text
            assert samples[0].sample_id[:12] in page.text
            assert "2 / 2 样本" in page.text
            assert 'name="batch" value="primary-ui"' in page.text
            assert "全量主审" in page.text
            assert "10% 双审" in page.text
            assert "样本标注与仲裁" in page.text
            assert "第二位 reviewer 提交前看不到第一位结论" in page.text
            assert "完成进度" in page.text
            assert "data-quality-row" in page.text
            assert "data-quality-action" in page.text
            assert 'aria-keyshortcuts="A"' in page.text
            assert "J</kbd>/<kbd>K" in page.text
            dual_page = client.get("/review/quality?batch=frozen-ui")
            assert samples[1].sample_id[:12] in dual_page.text
            assert samples[0].sample_id[:12] not in dual_page.text
            assert client.get("/review/quality?batch=unknown").status_code == 404
            listing = client.get("/review/quality/samples?batch=frozen-ui")
            assert [row["sample_id"] for row in listing.json()["samples"]] == [
                samples[1].sample_id
            ]
            csrf = client.post("/review/login").json()["csrf_token"]
            decision = client.post(
                f"/review/quality/samples/{samples[1].sample_id}/decision",
                data={
                    "decision": "review", "csrf_token": csrf,
                    "offset": "0", "batch": "frozen-ui",
                },
                headers={"Accept": "text/html"}, follow_redirects=False,
            )
            assert decision.headers["location"] == "/review/quality?offset=0&batch=frozen-ui"
            primary_decision = client.post(
                f"/review/quality/samples/{samples[0].sample_id}/decision",
                data={
                    "decision": "allow", "csrf_token": csrf,
                    "offset": "0", "batch": "primary-ui",
                },
                headers={"Accept": "text/html"}, follow_redirects=False,
            )
            assert primary_decision.status_code == 303
            reports_store = QualityStore(str(database))
            try:
                primary_report = reports_store.review_batch_report(
                    consumer_id="corpus-avatar", batch_id="primary-ui"
                )
            finally:
                reports_store.close()
            assert primary_report["status"] == "PRIMARY_REVIEW_COMPLETE"
            assert primary_report["ground_truth"] is False
            switched = client.get("/review/quality")
            assert 'href="/review/quality?batch=frozen-ui" aria-current="page"' in switched.text
