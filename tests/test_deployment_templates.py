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
    assert "WORDYEAH_ENDPOINT=http://127.0.0.1:8000" in environment
    assert "systemctl enable" not in service


def test_cavalcade_exporter_is_bounded_and_read_only() -> None:
    exporter = (ROOT / "scripts/cravatar_cavalcade_export.php").read_text(encoding="utf-8")
    normalized = exporter.lower()
    assert "select id, status, start, args" in normalized
    assert "limit %d" in normalized
    assert "mutates_avatar'  => false" in normalized
    for mutation_method in ("->insert(", "->update(", "->delete(", "->replace(", "->query("):
        assert mutation_method not in normalized
