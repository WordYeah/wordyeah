from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cravatar_console_entrypoint_is_packaged() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["scripts"]["wordyeah-cravatar"] == "wy_cravatar.__main__:main"


def test_shadow_service_template_is_loopback_non_mutating_and_disabled_by_default() -> None:
    service = (
        ROOT / "deploy/systemd/wordyeah-cravatar-shadow.service"
    ).read_text(encoding="utf-8")
    environment = (
        ROOT / "deploy/systemd/cravatar-shadow.env.example"
    ).read_text(encoding="utf-8")

    assert "wordyeah-cravatar watch" in service
    assert "WantedBy=multi-user.target" in service
    assert "ReadOnlyPaths=/var/lib/wordyeah/inbox" in service
    assert "ReadWritePaths=/var/lib/wordyeah/state /var/lib/wordyeah/status" in service
    assert "WORDYEAH_API_KEY=" not in service
    assert "enforce" not in service.lower()
    assert "WORDYEAH_ENDPOINT=http://127.0.0.1:18765" in environment
    assert "systemctl enable" not in service


def test_runtime_service_templates_share_the_real_api_port_and_private_state() -> None:
    environment = (ROOT / "deploy/systemd/wordyeah.env.example").read_text(encoding="utf-8")
    api = (ROOT / "deploy/systemd/wordyeah-api.service").read_text(encoding="utf-8")
    worker = (ROOT / "deploy/systemd/wordyeah-worker.service").read_text(encoding="utf-8")
    vision = (ROOT / "deploy/systemd/wordyeah-vision-worker.service").read_text(encoding="utf-8")

    assert "WORDYEAH_BIND=127.0.0.1" in environment
    assert "WORDYEAH_PORT=18765" in environment
    assert "WORDYEAH_G2A_ENABLED=false" in environment
    assert "WORDYEAH_G2A_SECONDARY_ENABLED=false" in environment
    assert "WORDYEAH_API_KEY=" not in api + worker + vision
    assert "ReadWritePaths=/var/lib/wordyeah" in api
    assert all("UMask=0077" in unit for unit in (api, worker, vision))
    assert "wordyeah-worker --database" in worker
    assert "wordyeah-worker --vision" in vision
    assert "--vision-exclude-context-marker quality_ai_prelabel=true" in vision
    assert "systemctl enable" not in api + worker + vision


def test_cavalcade_exporter_is_bounded_and_read_only() -> None:
    exporter = (ROOT / "scripts/cravatar_cavalcade_export.php").read_text(encoding="utf-8")
    normalized = exporter.lower()
    assert "select id, status, start, args" in normalized
    assert "limit %d" in normalized
    assert "mutates_avatar'  => false" in normalized
    for mutation_method in ("->insert(", "->update(", "->delete(", "->replace(", "->query("):
        assert mutation_method not in normalized
