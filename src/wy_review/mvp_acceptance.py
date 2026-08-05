"""Aggregate avatar MVP evidence without converting missing evidence into success."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping


Evidence = Mapping[str, object]


def audit_avatar_mvp(
    *,
    corpus: Path,
    queue_load: Path,
    fault_drills: Path,
    browser: Path,
    reviewer_runtime: Path,
    shadow: Path,
    vision_canary: Path,
    shadow_minimum: int = 1100,
    enforce: bool = False,
) -> dict[str, object]:
    """Evaluate all durable MVP gates and preserve missing/partial states."""

    if shadow_minimum < 1:
        raise ValueError("shadow_minimum must be positive")
    checks = [
        _evidence_check("representative_corpus", corpus, _corpus_pass),
        _evidence_check("queue_load_15m", queue_load, _queue_load_pass),
        _evidence_check("fault_drills", fault_drills, _fault_drills_pass),
        _evidence_check("browser_acceptance", browser, _browser_pass),
        _evidence_check(
            "reviewer_runtime", reviewer_runtime, _reviewer_runtime_pass
        ),
        _evidence_check(
            "cravatar_shadow",
            shadow,
            lambda value: _shadow_pass(value, minimum=shadow_minimum),
        ),
        _evidence_check("advanced_vision_canary", vision_canary, _vision_canary_pass),
        {
            "name": "production_write_boundary",
            "status": "FAIL" if enforce else "PASS",
            "reason": "enforce_must_remain_false" if enforce else "enforce_false",
        },
    ]
    statuses = {str(check["status"]) for check in checks}
    status = "FAIL" if "FAIL" in statuses else "INCOMPLETE" if "INCOMPLETE" in statuses else "PASS"
    return {
        "kind": "wordyeah_avatar_mvp_acceptance",
        "status": status,
        "shadow_minimum": shadow_minimum,
        "enforce": enforce,
        "checks": checks,
    }


def _evidence_check(
    name: str,
    path: Path,
    predicate: Callable[[Evidence], tuple[bool, str]],
) -> dict[str, object]:
    if not path.is_file():
        return {
            "name": name,
            "status": "INCOMPLETE",
            "reason": "evidence_missing",
            "path": str(path),
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "name": name,
            "status": "FAIL",
            "reason": f"invalid_evidence: {exc}",
            "path": str(path),
        }
    if not isinstance(value, dict):
        return {
            "name": name,
            "status": "FAIL",
            "reason": "evidence_must_be_object",
            "path": str(path),
        }
    source_status = str(value.get("status", ""))
    if source_status in {"SKIP", "INCOMPLETE"}:
        return {
            "name": name,
            "status": "INCOMPLETE",
            "reason": f"source_status_{source_status.lower()}",
            "path": str(path),
        }
    passed, reason = predicate(value)
    return {
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "reason": reason,
        "path": str(path),
    }


def _corpus_pass(value: Evidence) -> tuple[bool, str]:
    required = {"human", "illustration", "logo_text", "boundary", "explicit_violation"}
    strata = value.get("strata")
    dual = value.get("dual_review")
    split = value.get("split_integrity")
    passed = (
        value.get("status") == "PASS"
        and isinstance(strata, dict)
        and required.issubset(strata)
        and all(
            isinstance(strata[name], dict) and strata[name].get("status") == "PASS"
            for name in required
        )
        and isinstance(dual, dict)
        and dual.get("status") == "PASS"
        and isinstance(split, dict)
        and split.get("status") == "PASS"
    )
    return passed, "all_corpus_gates_pass" if passed else "corpus_gate_failed"


def _queue_load_pass(value: Evidence) -> tuple[bool, str]:
    passed = (
        value.get("status") == "PASS"
        and value.get("duration_gate_met") is True
        and value.get("rate_gate_met") is True
        and _integer(value.get("active_jobs_after_run")) == 0
    )
    return passed, "duration_rate_and_residue_pass" if passed else "queue_load_gate_failed"


def _fault_drills_pass(value: Evidence) -> tuple[bool, str]:
    required = {
        "database_restart_and_lease_recovery",
        "feature_flag_disabled",
        "provider_rate_limit",
        "provider_invalid_response",
        "cravatar_shadow_non_mutation",
    }
    rows = value.get("checks")
    checks = _unique_named_checks(rows)
    passed = (
        value.get("status") == "PASS"
        and value.get("external_model_calls") is False
        and value.get("mutates_avatar") is False
        and checks is not None
        and required.issubset(checks)
        and all(checks[name].get("status") == "PASS" for name in required)
    )
    return passed, "required_fault_drills_pass" if passed else "fault_drill_gate_failed"


def _browser_pass(value: Evidence) -> tuple[bool, str]:
    required = {
        "desktop_list_1440",
        "three_queue_views",
        "batch_mode_server_contract",
        "focus_actions_no_modal",
        "desktop_list_1280",
        "all_dropdowns_share_alignment_contract",
        "quality_blind_keyboard_contract",
        "mobile_quality_workspace",
        "mobile_no_horizontal_overflow",
        "corpus_quality_1100_paginated_thumbnails",
        "isolated_fixture_non_mutation",
    }
    rows = value.get("checks")
    checks = _unique_named_checks(rows)
    passed = (
        value.get("status") == "PASS"
        and value.get("reviewer_session") is True
        and value.get("mutates_review_decisions") is False
        and value.get("isolated_fixture") is True
        and value.get("source_database_mode") == "read_only_backup"
        and value.get("source_database_mutated") is False
        and value.get("production_avatar_write") is False
        and checks is not None
        and required.issubset(checks)
        and all(checks[name].get("status") == "PASS" for name in required)
    )
    return passed, "required_browser_flows_pass" if passed else "browser_gate_failed"


def _reviewer_runtime_pass(value: Evidence) -> tuple[bool, str]:
    required = {"reviewer-a", "reviewer-b", "arbitrator"}
    checks = _unique_named_checks(value.get("checks"))
    passed = (
        value.get("kind") == "reviewer_runtime_acceptance"
        and value.get("status") == "PASS"
        and value.get("consumer_id") == "corpus-avatar"
        and value.get("secrets_emitted") is False
        and checks is not None
        and set(checks) == required
        and all(
            checks[name].get("status") == "PASS"
            and checks[name].get("csrf_present") is True
            and checks[name].get("account_identity_present") is True
            and checks[name].get("quality_batches_present") is True
            and _integer(checks[name].get("cookie_count")) == 1
            for name in required
        )
    )
    return passed, (
        "three_isolated_reviewer_sessions_pass"
        if passed
        else "reviewer_runtime_gate_failed"
    )


def _shadow_pass(value: Evidence, *, minimum: int) -> tuple[bool, str]:
    passed = (
        value.get("status") == "PASS"
        and value.get("mutates_avatar") is False
        and _integer(value.get("source_count"), default=0) >= minimum
        and _integer(value.get("failed_count")) == 0
        and value.get("stable_rerun") is True
        and value.get("production_state_unchanged") is True
        and _number(value.get("feature_flag_stop_seconds"), default=61) <= 60
    )
    return passed, "shadow_scale_and_safety_pass" if passed else "shadow_gate_failed"


def _vision_canary_pass(value: Evidence) -> tuple[bool, str]:
    passed = (
        value.get("status") == "PASS"
        and value.get("actual_provider_response") is True
        and _integer(value.get("image_count"), default=0) >= 1
        and value.get("decision") in {"allow", "review", "block"}
    )
    return passed, "actual_visual_response_pass" if passed else "vision_canary_gate_failed"


def _unique_named_checks(value: object) -> dict[str, Mapping[str, object]] | None:
    if not isinstance(value, list):
        return None
    checks: dict[str, Mapping[str, object]] = {}
    for row in value:
        if not isinstance(row, dict):
            return None
        name = row.get("name")
        if not isinstance(name, str) or not name or name in checks:
            return None
        checks[name] = row
    return checks


def _integer(value: object, *, default: int = -1) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _number(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
