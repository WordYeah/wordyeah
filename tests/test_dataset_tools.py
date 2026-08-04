import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def _write_image(path: Path, color: tuple[int, int, int]) -> str:
    Image.new("RGB", (16, 16), color).save(path, format="PNG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_validator(manifest: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/dataset_validate.py", str(manifest), *extra],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _entry(sample_id: str, digest: str, split: str = "calibration") -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "content_sha256": digest,
        "local_ref": f"dataset://avatars/{sample_id}.png",
        "media_type": "image",
        "style": "real",
        "expected_decision": "allow",
        "categories": [],
        "source": "internal-consented",
        "license": "private",
        "reviewer_count": 2,
        "split": split,
        "duplicate_group": sample_id,
    }


def test_dataset_validator_reports_skip_without_treating_it_as_pass(tmp_path: Path) -> None:
    image = tmp_path / "avatar.png"
    digest = _write_image(image, (30, 40, 50))
    entry = _entry("sample-1", digest)
    entry["path"] = str(image)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    result = _run_validator(manifest, "--root", str(tmp_path), "--check-files")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["error_count"] == 0
    assert report["acceptance"]["status"] == "INCOMPLETE_OR_SKIPPED"
    assert report["acceptance"]["gates"]["explicit_block"]["status"] == "SKIP_NO_SAMPLES"


def test_dataset_validator_rejects_cross_split_duplicate_group(tmp_path: Path) -> None:
    first = _entry("sample-1", "1" * 64, split="train")
    second = _entry("sample-2", "2" * 64, split="test")
    first["duplicate_group"] = second["duplicate_group"] = "near-1"
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("\n".join(json.dumps(item) for item in (first, second)) + "\n", encoding="utf-8")

    result = _run_validator(manifest)

    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert any("duplicate_group_crosses_splits" in item for item in report["errors"])


def test_dataset_validator_rejects_hash_mismatch_and_path_escape(tmp_path: Path) -> None:
    image = tmp_path / "avatar.png"
    _write_image(image, (1, 2, 3))
    entry = _entry("sample-1", "0" * 64)
    entry["path"] = str(tmp_path.parent / "outside.png")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    result = _run_validator(manifest, "--root", str(tmp_path), "--check-files")

    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert any(
        "ManifestError" in item or "local_file_missing" in item for item in report["errors"]
    )


def test_dataset_import_and_deduplicate_report_exact_duplicates(tmp_path: Path) -> None:
    source = tmp_path / "raw" / "real" / "allow"
    source.mkdir(parents=True)
    first = source / "one.png"
    second = source / "two.png"
    _write_image(first, (10, 20, 30))
    second.write_bytes(first.read_bytes())
    manifest = tmp_path / "manifest.jsonl"

    imported = subprocess.run(
        [
            sys.executable,
            "scripts/dataset_import.py",
            str(tmp_path / "raw"),
            "--output",
            str(manifest),
            "--source",
            "internal-consented",
            "--license",
            "private",
            "--reviewer-count",
            "2",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr

    deduplicated = subprocess.run(
        [
            sys.executable,
            "scripts/dataset_deduplicate.py",
            str(manifest),
            "--fail-on-exact",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert deduplicated.returncode == 3, deduplicated.stderr
    report = json.loads(deduplicated.stdout)
    assert report["exact_duplicate_groups"][0]["size"] == 2
