from __future__ import annotations

from pathlib import Path

from wy_review.fault_drills import run_fault_drills


def test_avatar_fault_drills_cover_required_fail_closed_paths(tmp_path: Path) -> None:
    report = run_fault_drills(tmp_path / "fault-drills.sqlite3")
    assert report["status"] == "PASS"
    assert report["external_model_calls"] is False
    assert report["mutates_avatar"] is False
    checks = {check["name"]: check for check in report["checks"]}
    assert set(checks) == {
        "database_restart_and_lease_recovery",
        "feature_flag_disabled",
        "provider_rate_limit",
        "provider_invalid_response",
        "cravatar_shadow_non_mutation",
    }
    assert checks["database_restart_and_lease_recovery"]["recovered_attempts"] == 2
    assert checks["database_restart_and_lease_recovery"]["dead_lettered"] is True
    assert checks["feature_flag_disabled"]["transport_called"] is False
    assert checks["provider_rate_limit"]["decision"] is None
    assert checks["provider_invalid_response"]["decision"] is None
