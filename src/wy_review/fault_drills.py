"""Deterministic avatar MVP fault drills with no external network calls."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from wy_core.contracts import ModerationResult
from wy_cravatar.adapter import CravatarAdapter
from wy_jobs.store import JobStore
from wy_media.g2a import G2AConfig, G2AVisionProvider, HttpResponse
from wy_media.vision_provider import VisionErrorKind, VisionProviderError, VisionReviewRequest


def run_fault_drills(database: str | Path) -> dict[str, object]:
    """Run persistence, lease, provider and non-mutation failure drills."""

    checks = [
        _database_and_lease_drill(str(database)),
        _disabled_provider_drill(),
        _rate_limit_drill(),
        _invalid_response_drill(),
        _shadow_non_mutation_drill(),
    ]
    return {
        "kind": "wordyeah_avatar_fault_drills",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL",
        "external_model_calls": False,
        "mutates_avatar": False,
        "checks": checks,
    }


def _database_and_lease_drill(database: str) -> dict[str, object]:
    store = JobStore(database)
    job = store.enqueue(
        "vision_review_1",
        {"item_id": "fault-drill-item"},
        "fault-drill",
        max_attempts=3,
        idempotency_key="fault-drill:persistence-lease:v1",
    )
    store.close()

    reopened = JobStore(database)
    persisted = reopened.get(job.job_id)
    first = reopened.claim("fault-worker-a", lease_seconds=30, kinds=("vision_review_1",))
    if first is None:
        reopened.close()
        return _failed("database_restart_and_lease_recovery", "queued job could not be claimed")
    reopened.connection.execute(
        "UPDATE jobs SET lease_until = ? WHERE job_id = ?",
        ("1970-01-01T00:00:00+00:00", first.job_id),
    )
    reopened.connection.commit()
    reopened.close()

    recovered_store = JobStore(database)
    recovered = recovered_store.claim(
        "fault-worker-b", lease_seconds=30, kinds=("vision_review_1",)
    )
    if recovered is None:
        recovered_store.close()
        return _failed("database_restart_and_lease_recovery", "expired lease was not recovered")
    terminal = recovered_store.fail(
        recovered.job_id,
        "fault-worker-b",
        "simulated non-retryable provider failure",
        error_kind="invalid_response",
        retryable=False,
    )
    recovered_store.close()
    passed = (
        persisted.status == "queued"
        and recovered.worker_id == "fault-worker-b"
        and recovered.attempts == 2
        and terminal.dead_lettered
        and terminal.status == "failed"
    )
    return {
        "name": "database_restart_and_lease_recovery",
        "status": "PASS" if passed else "FAIL",
        "persisted_status": persisted.status,
        "recovered_attempts": recovered.attempts,
        "recovered_worker": recovered.worker_id,
        "terminal_status": terminal.status,
        "dead_lettered": terminal.dead_lettered,
    }


def _disabled_provider_drill() -> dict[str, object]:
    called = False

    def transport(_request, _timeout):
        nonlocal called
        called = True
        raise AssertionError("disabled provider attempted a network call")

    provider = G2AVisionProvider(G2AConfig(), transport=transport)
    error = _provider_error(provider)
    passed = error is not None and error.kind is VisionErrorKind.DISABLED and not called
    return {
        "name": "feature_flag_disabled",
        "status": "PASS" if passed else "FAIL",
        "error_kind": error.kind.value if error else None,
        "transport_called": called,
    }


def _rate_limit_drill() -> dict[str, object]:
    provider = G2AVisionProvider(
        _enabled_config(),
        transport=lambda _request, _timeout: HttpResponse(429, b"{}", {"Retry-After": "7"}),
    )
    error = _provider_error(provider)
    passed = (
        error is not None
        and error.kind is VisionErrorKind.RATE_LIMIT
        and error.retryable
        and error.retry_after_seconds == 7.0
    )
    return {
        "name": "provider_rate_limit",
        "status": "PASS" if passed else "FAIL",
        "error_kind": error.kind.value if error else None,
        "retryable": error.retryable if error else None,
        "retry_after_seconds": error.retry_after_seconds if error else None,
        "decision": None,
    }


def _invalid_response_drill() -> dict[str, object]:
    provider = G2AVisionProvider(
        _enabled_config(), transport=lambda _request, _timeout: HttpResponse(200, b"{}")
    )
    error = _provider_error(provider)
    passed = (
        error is not None
        and error.kind is VisionErrorKind.INVALID_RESPONSE
        and not error.retryable
    )
    return {
        "name": "provider_invalid_response",
        "status": "PASS" if passed else "FAIL",
        "error_kind": error.kind.value if error else None,
        "retryable": error.retryable if error else None,
        "decision": None,
    }


def _shadow_non_mutation_drill() -> dict[str, object]:
    decisions = ("allow", "review", "block", "error")
    digest_characters = {"allow": "a", "review": "b", "block": "c", "error": "d"}
    actions: list[dict[str, object]] = []
    for decision in decisions:
        result = ModerationResult(
            request_id=f"fault-{decision}",
            content_sha256=digest_characters[decision] * 64,
            media_type="image",
            decision=decision,  # type: ignore[arg-type]
            error="simulated classifier failure" if decision == "error" else None,
        )
        translated = CravatarAdapter("shadow").translate(result)
        actions.append(
            {
                "decision": decision,
                "action": translated.action,
                "mutates_avatar": translated.mutates_avatar,
            }
        )
    passed = all(
        row["action"] == "record_only" and row["mutates_avatar"] is False
        for row in actions
    )
    return {
        "name": "cravatar_shadow_non_mutation",
        "status": "PASS" if passed else "FAIL",
        "actions": actions,
    }


def _provider_error(provider: G2AVisionProvider) -> VisionProviderError | None:
    try:
        provider.review(
            VisionReviewRequest(
                image_bytes=b"fault-drill-image",
                media_type="image/png",
                request_id="fault-drill-provider",
                categories=("sexual_content",),
            )
        )
    except VisionProviderError as exc:
        return exc
    return None


def _enabled_config() -> G2AConfig:
    return G2AConfig(
        enabled=True,
        endpoint="https://127.0.0.1/fault-drill",
        api_key="fault-drill-not-a-secret",
        model_id="fault-drill-model",
    )


def _failed(name: str, reason: str) -> dict[str, object]:
    return {"name": name, "status": "FAIL", "reason": reason}
