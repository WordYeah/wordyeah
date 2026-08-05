from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_browser_acceptance.py"
SPEC = importlib.util.spec_from_file_location("audit_browser_acceptance", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_browser_acceptance_only_allows_loopback() -> None:
    assert MODULE._loopback_base("http://127.0.0.1:18765") == "http://127.0.0.1:18765"
    with pytest.raises(ValueError, match="loopback"):
        MODULE._loopback_base("https://review.example.com")
    with pytest.raises(ValueError, match="loopback"):
        MODULE._loopback_base("http://user:secret@127.0.0.1:18765")


def test_browser_acceptance_runtime_requires_private_three_role_file(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "reviewers": {
                    "reviewer-a": "a" * 16,
                    "reviewer-b": "b" * 16,
                    "arbitrator": "c" * 16,
                },
                "session_secret": "s" * 32,
            }
        ),
        encoding="utf-8",
    )
    runtime.chmod(0o600)
    assert set(MODULE._load_runtime(runtime)["reviewers"]) == {
        "reviewer-a",
        "reviewer-b",
        "arbitrator",
    }
    runtime.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        MODULE._load_runtime(runtime)
