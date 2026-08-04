from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from wy_review.corpus_candidates import (
    CandidateSourceError,
    collect_huggingface_archive_candidates,
    collect_huggingface_candidates,
)


def _image_bytes(color: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (24, 24), color=color).save(output, format="PNG")
    return output.getvalue()


def _options(tmp_path: Path) -> dict[str, object]:
    return {
        "dataset": "owner/avatars",
        "config": "default",
        "split": "test",
        "image_field": "image",
        "label_field": "label",
        "label": 0,
        "count": 2,
        "output_root": tmp_path,
        "source_url": "https://huggingface.co/datasets/owner/avatars",
        "license_name": "mit",
        "style_candidate": "real",
        "decision_candidate": "allow",
    }


def test_collects_filtered_unreviewed_candidates_atomically(tmp_path: Path) -> None:
    images = {0: _image_bytes("red"), 2: _image_bytes("blue")}

    def fetch_json(url: str, maximum: int) -> dict[str, object]:
        assert maximum == 4 * 1024 * 1024
        query = parse_qs(urlsplit(url).query)
        assert query["dataset"] == ["owner/avatars"]
        return {
            "num_rows_total": 3,
            "rows": [
                {
                    "row_idx": index,
                    "row": {
                        "label": 0 if index != 1 else 1,
                        "image": {
                            "src": "https://datasets-server.huggingface.co/"
                            f"cached-assets/owner/avatars/rev/default/test/{index}/image.png"
                        },
                    },
                }
                for index in range(3)
            ],
        }

    def fetch_bytes(url: str, maximum: int) -> bytes:
        assert maximum == 8 * 1024 * 1024
        index = int(urlsplit(url).path.split("/")[-2])
        return images[index]

    report = collect_huggingface_candidates(
        **_options(tmp_path), fetch_json=fetch_json, fetch_bytes=fetch_bytes
    )
    assert report["status"] == "READY_FOR_REVIEW"
    assert report["candidate_count"] == 2
    assert report["reviewed_count"] == 0
    assert report["ground_truth"] is False
    manifest = Path(str(report["manifest"]))
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    assert [row["source_row"] for row in rows] == [0, 2]
    assert all(row["review_status"] == "unreviewed" for row in rows)
    assert all("Expires=" not in json.dumps(row) for row in rows)
    assert all(Path(row["path"]).suffix == ".png" for row in rows)
    assert manifest.stat().st_mode & 0o777 == 0o600
    assert all(Path(row["path"]).stat().st_mode & 0o777 == 0o600 for row in rows)


def test_rejects_image_source_outside_allowlist(tmp_path: Path) -> None:
    def fetch_json(url: str, maximum: int) -> dict[str, object]:
        return {
            "num_rows_total": 1,
            "rows": [
                {
                    "row_idx": 0,
                    "row": {
                        "label": 0,
                        "image": {"src": "https://example.com/private.jpg"},
                    },
                }
            ],
        }

    with pytest.raises(CandidateSourceError, match="allowlist"):
        collect_huggingface_candidates(
            **_options(tmp_path), fetch_json=fetch_json, fetch_bytes=lambda url, maximum: b""
        )


def test_rejects_nonstandard_viewer_port(tmp_path: Path) -> None:
    def fetch_json(url: str, maximum: int) -> dict[str, object]:
        return {
            "num_rows_total": 1,
            "rows": [
                {
                    "row_idx": 0,
                    "row": {
                        "label": 0,
                        "image": {
                            "src": "https://datasets-server.huggingface.co:8443/"
                            "cached-assets/owner/avatars/rev/default/test/0/image.png"
                        },
                    },
                }
            ],
        }

    with pytest.raises(CandidateSourceError, match="allowlist"):
        collect_huggingface_candidates(
            **_options(tmp_path), fetch_json=fetch_json, fetch_bytes=lambda url, maximum: b""
        )


def test_incomplete_source_does_not_claim_ready(tmp_path: Path) -> None:
    options = _options(tmp_path)
    options["count"] = 2

    def fetch_json(url: str, maximum: int) -> dict[str, object]:
        return {
            "num_rows_total": 1,
            "rows": [
                {
                    "row_idx": 0,
                    "row": {
                        "label": 0,
                        "image": {
                            "src": "https://datasets-server.huggingface.co/"
                            "cached-assets/owner/avatars/rev/default/test/0/image.png"
                        },
                    },
                }
            ],
        }

    report = collect_huggingface_candidates(
        **options,
        fetch_json=fetch_json,
        fetch_bytes=lambda url, maximum: _image_bytes("green"),
    )
    assert report["status"] == "INCOMPLETE"
    assert report["candidate_count"] == 1
    assert report["ground_truth"] is False


def test_rejects_invalid_dataset_and_source_url(tmp_path: Path) -> None:
    options = _options(tmp_path)
    options["dataset"] = "https://internal/metadata"
    with pytest.raises(CandidateSourceError, match="owner/name"):
        collect_huggingface_candidates(**options)
    options = _options(tmp_path)
    options["source_url"] = "https://example.com/dataset"
    with pytest.raises(CandidateSourceError, match="huggingface.co"):
        collect_huggingface_candidates(**options)


def test_collects_bounded_archive_candidates(tmp_path: Path) -> None:
    archive = tmp_path / "dataset.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("images/002.png", _image_bytes("blue"))
        bundle.writestr("images/001.png", _image_bytes("red"))
        bundle.writestr("README.txt", "ignored")
    report = collect_huggingface_archive_candidates(
        archive=archive,
        dataset="owner/archive-avatars",
        count=1,
        output_root=tmp_path / "out",
        source_url="https://huggingface.co/datasets/owner/archive-avatars",
        license_name="cc0-1.0",
        style_candidate="anime",
        decision_candidate="allow",
    )
    assert report["status"] == "READY_FOR_REVIEW"
    rows = [
        json.loads(line)
        for line in Path(str(report["manifest"])).read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["source_member"] == "images/001.png"
    assert rows[0]["review_status"] == "unreviewed"


def test_archive_path_traversal_is_not_extracted(tmp_path: Path) -> None:
    archive = tmp_path / "dataset.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.png", _image_bytes("red"))
    report = collect_huggingface_archive_candidates(
        archive=archive,
        dataset="owner/archive-avatars",
        count=1,
        output_root=tmp_path / "out",
        source_url="https://huggingface.co/datasets/owner/archive-avatars",
        license_name="cc0-1.0",
        style_candidate="anime",
        decision_candidate="allow",
    )
    assert report["status"] == "INCOMPLETE"
    assert report["candidate_count"] == 0
    assert not (tmp_path / "escape.png").exists()
