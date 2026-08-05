from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from wy_review.mvp_acceptance import audit_avatar_mvp


def _write(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _passing_evidence(tmp_path: Path) -> dict[str, Path]:
    strata = {
        name: {"status": "PASS"}
        for name in (
            "human",
            "illustration",
            "logo_text",
            "boundary",
            "explicit_violation",
        )
    }
    fault_names = (
        "database_restart_and_lease_recovery",
        "feature_flag_disabled",
        "provider_rate_limit",
        "provider_invalid_response",
        "cravatar_shadow_non_mutation",
    )
    browser_names = (
        "desktop_list_1440",
        "three_queue_views",
        "batch_mode_server_contract",
        "focus_actions_no_modal",
        "desktop_list_1280",
        "all_dropdowns_share_alignment_contract",
        "mobile_quality_workspace",
        "mobile_no_horizontal_overflow",
        "corpus_quality_1100_paginated_thumbnails",
        "isolated_fixture_non_mutation",
    )
    return {
        "corpus": _write(
            tmp_path / "corpus.json",
            {
                "status": "PASS",
                "strata": strata,
                "dual_review": {"status": "PASS"},
                "split_integrity": {"status": "PASS"},
            },
        ),
        "queue_load": _write(
            tmp_path / "load.json",
            {
                "status": "PASS",
                "duration_gate_met": True,
                "rate_gate_met": True,
                "active_jobs_after_run": 0,
            },
        ),
        "fault_drills": _write(
            tmp_path / "faults.json",
            {
                "status": "PASS",
                "external_model_calls": False,
                "mutates_avatar": False,
                "checks": [
                    {"name": name, "status": "PASS"} for name in fault_names
                ],
            },
        ),
        "browser": _write(
            tmp_path / "browser.json",
            {
                "status": "PASS",
                "reviewer_session": True,
                "mutates_review_decisions": False,
                "isolated_fixture": True,
                "source_database_mode": "read_only_backup",
                "source_database_mutated": False,
                "production_avatar_write": False,
                "checks": [
                    {"name": name, "status": "PASS"} for name in browser_names
                ],
            },
        ),
        "shadow": _write(
            tmp_path / "shadow.json",
            {
                "status": "PASS",
                "mutates_avatar": False,
                "source_count": 1100,
                "failed_count": 0,
                "stable_rerun": True,
                "production_state_unchanged": True,
                "feature_flag_stop_seconds": 1,
            },
        ),
        "vision_canary": _write(
            tmp_path / "vision.json",
            {
                "status": "PASS",
                "actual_provider_response": True,
                "image_count": 1,
                "decision": "review",
            },
        ),
    }


def test_acceptance_pass_requires_every_evidence_gate(tmp_path: Path) -> None:
    report = audit_avatar_mvp(**_passing_evidence(tmp_path))
    assert report["status"] == "PASS"
    assert all(check["status"] == "PASS" for check in report["checks"])


def test_missing_and_skip_evidence_stay_incomplete(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["corpus"] = _write(tmp_path / "corpus.json", {"status": "SKIP"})
    evidence["shadow"].unlink()
    report = audit_avatar_mvp(**evidence)
    assert report["status"] == "INCOMPLETE"
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["representative_corpus"]["status"] == "INCOMPLETE"
    assert checks["cravatar_shadow"]["status"] == "INCOMPLETE"


def test_enforce_or_invalid_claim_fails_acceptance(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["browser"] = _write(tmp_path / "browser.json", {"status": "PASS"})
    report = audit_avatar_mvp(**evidence, enforce=True)
    assert report["status"] == "FAIL"
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["browser_acceptance"]["status"] == "FAIL"
    assert checks["production_write_boundary"]["status"] == "FAIL"


def test_malformed_numeric_evidence_fails_without_crashing(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["shadow"] = _write(
        tmp_path / "shadow.json",
        {
            "status": "PASS",
            "mutates_avatar": False,
            "source_count": "not-a-number",
            "failed_count": 0,
            "stable_rerun": True,
            "production_state_unchanged": True,
            "feature_flag_stop_seconds": 1,
        },
    )
    report = audit_avatar_mvp(**evidence)
    checks = {check["name"]: check for check in report["checks"]}
    assert report["status"] == "FAIL"
    assert checks["cravatar_shadow"]["status"] == "FAIL"


def test_duplicate_check_names_cannot_overwrite_failure(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    payload = json.loads(evidence["fault_drills"].read_text(encoding="utf-8"))
    payload["checks"].extend(
        [
            {"name": "provider_rate_limit", "status": "FAIL"},
            {"name": "provider_rate_limit", "status": "PASS"},
        ]
    )
    evidence["fault_drills"] = _write(tmp_path / "faults.json", payload)
    report = audit_avatar_mvp(**evidence)
    checks = {check["name"]: check for check in report["checks"]}
    assert report["status"] == "FAIL"
    assert checks["fault_drills"]["status"] == "FAIL"


def test_malformed_check_row_cannot_be_ignored(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    payload = json.loads(evidence["browser"].read_text(encoding="utf-8"))
    payload["checks"].append({"status": "PASS"})
    evidence["browser"] = _write(tmp_path / "browser.json", payload)
    report = audit_avatar_mvp(**evidence)
    checks = {check["name"]: check for check in report["checks"]}
    assert report["status"] == "FAIL"
    assert checks["browser_acceptance"]["status"] == "FAIL"


def test_browser_evidence_requires_isolated_non_mutating_source(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    payload = json.loads(evidence["browser"].read_text(encoding="utf-8"))
    payload.pop("isolated_fixture")
    payload["source_database_mutated"] = True
    evidence["browser"] = _write(tmp_path / "browser.json", payload)
    report = audit_avatar_mvp(**evidence)
    checks = {check["name"]: check for check in report["checks"]}
    assert report["status"] == "FAIL"
    assert checks["browser_acceptance"]["status"] == "FAIL"


def test_invalid_utf8_evidence_is_a_structured_failure(tmp_path: Path) -> None:
    evidence = _passing_evidence(tmp_path)
    evidence["browser"].write_bytes(b"\xff\xfe")
    report = audit_avatar_mvp(**evidence)
    checks = {check["name"]: check for check in report["checks"]}
    assert report["status"] == "FAIL"
    assert checks["browser_acceptance"]["reason"].startswith("invalid_evidence:")


def test_cli_rejects_non_positive_shadow_minimum() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_avatar_mvp.py",
            "--shadow-minimum",
            "0",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 2
    assert "must be a positive integer" in result.stderr
    assert "Traceback" not in result.stderr
