from __future__ import annotations

import base64
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(shutil.which("php") is None, reason="PHP CLI is unavailable")
def test_cavalcade_export_preserves_gravatar_registry_origin(tmp_path: Path) -> None:
    exporter = ROOT / "scripts" / "cravatar_cavalcade_export.php"
    harness = tmp_path / "export-harness.php"
    harness.write_text(
        """<?php
define('ABSPATH', __DIR__);
define('ARRAY_A', 'ARRAY_A');
function maybe_unserialize($value) { return $value; }
function wp_json_encode($value) { return json_encode($value, JSON_UNESCAPED_SLASHES); }
class FakeWpdb {
    public $base_prefix = 'wp_';
    private $calls = 0;
    public function prepare($sql, $parameters) { return $sql; }
    public function get_blog_prefix($site_id) { return 'wp_' . $site_id . '_'; }
    public function get_results($sql, $format) {
        $this->calls++;
        if ($this->calls === 1) {
            return [[
                'id' => 42,
                'status' => 'completed',
                'start' => '2026-08-05 00:00:00',
                'args' => [
                    'url' => 'https://cravatar.cn/avatar/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                    'image_md5' => 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                    'email_hash' => 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                ],
            ]];
        }
        return [[
            'image_md5' => 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
            'type' => 'gravatar',
            'status' => 0,
            'url' => 'https://cravatar.cn/avatar/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        ]];
    }
}
$wpdb = new FakeWpdb();
require """
        + repr(str(exporter))
        + ";\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["php", str(harness)], check=True, capture_output=True, text=True
    )
    row = json.loads(result.stdout)
    assert row["avatar_origin"] == "gravatar"
    assert row["registry_status"] == 0
    assert row["avatar_url"].startswith("https://cravatar.com/avatar/")
    assert row["registry_url"].startswith("https://cravatar.com/avatar/")


@pytest.mark.skipif(shutil.which("php") is None, reason="PHP CLI is unavailable")
def test_cavalcade_tsv_converter_handles_wrapped_base64(tmp_path: Path) -> None:
    email_hash = "a" * 32
    image_md5 = "b" * 32
    url = f"https://cravatar.com/avatar/{email_hash}"
    serialized = (
        f'a:3:{{s:3:"url";s:{len(url)}:"{url}";'
        f's:9:"image_md5";s:32:"{image_md5}";'
        f's:10:"email_hash";s:32:"{email_hash}";}}'
    ).encode()
    encoded = base64.b64encode(serialized).decode()
    source = tmp_path / "export.tsv"
    source.write_text(
        f"42\tcompleted\t2026-08-05 00:00:00\t{encoded[:76]}\n{encoded[76:]}\n"
    )
    result = subprocess.run(
        ["php", str(ROOT / "scripts/cravatar_cavalcade_tsv_convert.php"), str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    row = json.loads(result.stdout)
    assert row["source_id"] == "cravatar-job:42"
    assert row["avatar_url"] == url
    assert row["mutates_avatar"] is False


def test_shadow_audit_requires_stable_complete_non_mutating_run(tmp_path: Path) -> None:
    source_id = "cravatar-job:42"
    export_row = {
        "source_id": source_id,
        "job_id": 42,
        "source_status": "completed",
        "source_start": "2026-08-05 00:00:00",
        "avatar_url": f"https://cravatar.com/avatar/{'a' * 32}",
        "email_hash": "a" * 32,
        "image_md5": "b" * 32,
        "avatar_origin": "gravatar",
        "registry_status": 0,
        "registry_url": f"https://cravatar.com/avatar/{'a' * 32}",
        "mutates_avatar": False,
    }
    manifest_row = {
        "source_id": source_id,
        "content_sha256": "c" * 64,
        "mutates_avatar": False,
    }

    def write_json(name: str, value: object) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(value) + "\n")
        return path

    before = write_json("before.jsonl", export_row)
    after = write_json("after.jsonl", export_row)
    manifest = write_json("manifest.jsonl", manifest_row)
    watermark = {
        "source_count": 1,
        "completed_count": 1,
        "failed_count": 0,
        "pending_count": 0,
        "mutates_avatar": False,
    }
    first = write_json(
        "first.json",
        {"watermark": watermark, "outcomes": [{"source_id": source_id, "status": "submitted"}]},
    )
    second = write_json("second.json", {"watermark": watermark, "outcomes": []})
    pause = write_json("pause.json", {"watermark": {**watermark, "paused": True}})
    collection = write_json("collection.json", {"exported": 1, "failed": 0, "mutates_avatar": False})
    pause_time = tmp_path / "pause.time"
    pause_time.write_text("real 0.10\n")
    output = tmp_path / "evidence.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/audit_cravatar_shadow.py"),
            "--before", str(before),
            "--after", str(after),
            "--manifest", str(manifest),
            "--first-run", str(first),
            "--second-run", str(second),
            "--pause", str(pause),
            "--pause-time", str(pause_time),
            "--collection", str(collection),
            "--minimum", "1",
            "--output", str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = json.loads(output.read_text())
    assert evidence["status"] == "PASS"
    assert evidence["production_state_unchanged"] is True
    assert evidence["feature_flag_stop_seconds"] == 0.1


def test_vision_canary_is_disabled_without_explicit_provider_config(tmp_path: Path) -> None:
    image = tmp_path / "canary.png"
    Image.new("RGB", (8, 8), "white").save(image)
    output = tmp_path / "vision.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_vision_canary.py"),
            str(image),
            "--output", str(output),
        ],
        capture_output=True,
        text=True,
        env={},
    )
    assert result.returncode == 1
    evidence = json.loads(output.read_text())
    assert evidence["status"] == "FAIL"
    assert evidence["actual_provider_response"] is False
    assert evidence["error_kind"] == "disabled"


def test_reviewer_runtime_audit_rejects_non_loopback_url() -> None:
    module = _load_script("audit_reviewer_runtime.py")
    with pytest.raises(ValueError, match="loopback"):
        module._loopback_base("https://review.example.com")


def test_reviewer_runtime_audit_requires_private_exact_config(tmp_path: Path) -> None:
    module = _load_script("audit_reviewer_runtime.py")
    path = tmp_path / "runtime.json"
    value = {
        "reviewers": {
            "reviewer-a": "a" * 16,
            "reviewer-b": "b" * 16,
            "arbitrator": "c" * 16,
        },
        "session_secret": "s" * 32,
    }
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    assert module._load_runtime(path) == value
    path.chmod(0o644)
    with pytest.raises(ValueError, match="group or others"):
        module._load_runtime(path)
    path.chmod(0o600)
    link = tmp_path / "runtime-link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        module._load_runtime(link)
