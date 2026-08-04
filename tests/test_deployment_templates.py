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
