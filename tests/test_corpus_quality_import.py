from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from wy_review.corpus_quality_import import (
    CorpusQualityImportError,
    import_candidate_manifests,
)
from wy_review.quality import QualityStore


def _candidate_manifest(root: Path, name: str, color: str) -> tuple[Path, str]:
    dataset = root / name
    images = dataset / "images"
    images.mkdir(parents=True)
    output = io.BytesIO()
    Image.new("RGB", (32, 32), color=color).save(output, format="PNG")
    payload = output.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    image = images / f"{digest}.png"
    image.write_bytes(payload)
    manifest = dataset / "candidates.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "sample_id": f"candidate-{name}",
                "content_sha256": digest,
                "path": str(image),
                "style_candidate": "other",
                "decision_candidate": "review",
                "review_status": "unreviewed",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest, digest


def test_imports_candidates_idempotently_without_promoting_source_suggestions(
    tmp_path: Path,
) -> None:
    human, human_digest = _candidate_manifest(tmp_path, "human", "green")
    boundary, boundary_digest = _candidate_manifest(tmp_path, "boundary", "orange")
    database = tmp_path / "quality.sqlite3"
    media_root = tmp_path / "media"
    specs = [("human", human), ("boundary", boundary)]

    first = import_candidate_manifests(
        specs,
        database=database,
        media_root=media_root,
        consumer_id="corpus-avatar",
    )
    second = import_candidate_manifests(
        specs,
        database=database,
        media_root=media_root,
        consumer_id="corpus-avatar",
    )

    assert first == {
        "kind": "wordyeah_corpus_quality_import",
        "status": "READY_FOR_HUMAN_REVIEW",
        "consumer_id": "corpus-avatar",
        "sample_count": 2,
        "copied_count": 2,
        "reused_count": 0,
        "by_stratum": {"human": 1, "boundary": 1},
        "ground_truth": False,
        "production_write": False,
    }
    assert second["copied_count"] == 0
    assert second["reused_count"] == 2
    store = QualityStore(str(database))
    try:
        samples = store.list_samples(consumer_id="corpus-avatar")
        assert {sample.content_sha256 for sample in samples} == {
            human_digest,
            boundary_digest,
        }
        assert {sample.final_decision for sample in samples} == {None}
        assert {sample.status for sample in samples} == {"awaiting_reviews"}
        assert {sample.retention_status for sample in samples} == {"private_corpus"}
        assert {sample.stratum for sample in samples} == {"human", "boundary"}
    finally:
        store.close()
    copied = sorted((media_root / "corpus" / "corpus-avatar").glob("*.png"))
    assert len(copied) == 2
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in copied)
    assert (media_root / "corpus" / "corpus-avatar").stat().st_mode & 0o777 == 0o700
    assert database.stat().st_mode & 0o777 == 0o600
    thumbnails = sorted(
        (media_root / "corpus" / "corpus-avatar" / "thumbs").glob("*.jpg")
    )
    assert len(thumbnails) == 2
    assert all(path.stat().st_size < 512 * 1024 for path in thumbnails)
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in thumbnails)


def test_rejects_truth_labels_and_hash_mismatches_before_writing(tmp_path: Path) -> None:
    manifest, _ = _candidate_manifest(tmp_path, "unsafe", "red")
    row = json.loads(manifest.read_text(encoding="utf-8"))
    row["expected_decision"] = "block"
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")
    database = tmp_path / "quality.sqlite3"
    media_root = tmp_path / "media"
    with pytest.raises(CorpusQualityImportError, match="unreviewed suggestions"):
        import_candidate_manifests(
            [("explicit_violation", manifest)],
            database=database,
            media_root=media_root,
            consumer_id="corpus-avatar",
        )
    assert not database.exists()
    assert not media_root.exists()

    row.pop("expected_decision")
    row["content_sha256"] = "0" * 64
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(CorpusQualityImportError, match="hash does not match"):
        import_candidate_manifests(
            [("explicit_violation", manifest)],
            database=database,
            media_root=media_root,
            consumer_id="corpus-avatar",
        )
    assert not database.exists()
    assert not media_root.exists()


def test_rejects_candidate_path_outside_manifest_images_directory(tmp_path: Path) -> None:
    manifest, _ = _candidate_manifest(tmp_path, "source", "blue")
    outside = tmp_path / "outside.png"
    outside.write_bytes(next((manifest.parent / "images").iterdir()).read_bytes())
    row = json.loads(manifest.read_text(encoding="utf-8"))
    row["path"] = str(outside)
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(CorpusQualityImportError, match="escapes"):
        import_candidate_manifests(
            [("human", manifest)],
            database=tmp_path / "quality.sqlite3",
            media_root=tmp_path / "media",
            consumer_id="corpus-avatar",
        )
