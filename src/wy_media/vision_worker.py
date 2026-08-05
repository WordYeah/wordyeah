from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from wy_jobs.store import Job, JobStore
from wy_jobs.vision import VISION_JOB_KINDS, VisionJobKind, VisionReviewJobPayload, enqueue_vision_review
from wy_review.corpus_ai_prelabels import (
    corpus_ai_prelabel_attempts,
    is_corpus_ai_prelabel,
    is_corpus_ai_prelabel_context,
)
from wy_review.attempt_store import ReviewAttempt, ReviewAttemptStore
from wy_review.router import ReviewRouter, RouteResult
from wy_review.store import ReviewStore

from .vision_provider import AdvancedVisionProvider, VisionErrorKind, VisionProviderError, VisionReviewConclusion, VisionReviewRequest


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class VisionReviewWorker:
    """Claims advanced-vision jobs, records attempts, and converges routing."""

    job_store: JobStore
    attempt_store: ReviewAttemptStore
    review_store: ReviewStore
    providers: Mapping[str, AdvancedVisionProvider]
    media_root: Path
    router: ReviewRouter = field(default_factory=ReviewRouter)
    worker_id: str = ""
    lease_seconds: int = 120
    consumer_id: str | None = None
    context_marker: str | None = None
    job_kinds: tuple[VisionJobKind, ...] = VISION_JOB_KINDS
    backoff_base_seconds: float = 1.0
    backoff_cap_seconds: float = 300.0
    stage_provider_slots: Mapping[str, str] = field(
        default_factory=lambda: {"vision_review_1": "primary", "vision_review_2": "secondary"}
    )

    def __post_init__(self) -> None:
        self.worker_id = self.worker_id or f"vision-worker-{uuid4().hex}"
        self.media_root = self.media_root.expanduser().resolve()
        if not self.job_kinds or any(kind not in VISION_JOB_KINDS for kind in self.job_kinds):
            raise ValueError("job_kinds must contain only advanced vision stages")
        self.job_kinds = tuple(dict.fromkeys(self.job_kinds))

    def run_once(self) -> Job | None:
        job = self.job_store.claim(
            self.worker_id,
            self.lease_seconds,
            kinds=self.job_kinds,
            consumer_id=self.consumer_id,
            context_marker=self.context_marker,
        )
        if job is None:
            return None
        try:
            payload = VisionReviewJobPayload.from_mapping(job.payload)
            self._validate_job(job, payload)
            return self._execute(job, payload)
        except VisionProviderError as exc:
            payload = self._payload_or_none(job)
            return self._record_provider_failure(job, payload, exc)
        except Exception as exc:
            return self.job_store.fail(
                job.job_id,
                self.worker_id,
                f"{type(exc).__name__}: {exc}",
                error_kind="worker_error",
                retryable=False,
            )

    def _execute(self, job: Job, payload: VisionReviewJobPayload) -> Job:
        provider = self.providers.get(payload.provider_slot)
        if provider is None:
            raise VisionProviderError(
                VisionErrorKind.CONFIGURATION,
                "vision provider slot is not configured",
                retryable=False,
            )
        if not provider.enabled:
            raise VisionProviderError(
                VisionErrorKind.DISABLED,
                "vision provider is disabled",
                retryable=False,
            )
        path = self._safe_media_path(payload.media_ref)
        try:
            image_bytes = path.read_bytes()
        except OSError as exc:
            raise VisionProviderError(
                VisionErrorKind.BAD_REQUEST,
                "controlled media could not be read",
                retryable=False,
            ) from exc
        expected_media_sha256 = payload.media_sha256 or payload.content_sha256
        if hashlib.sha256(image_bytes).hexdigest() != expected_media_sha256:
            raise VisionProviderError(
                VisionErrorKind.BAD_REQUEST,
                "controlled media hash does not match the queued payload",
                retryable=False,
            )

        attempt_number = payload.attempt_number + job.attempts - 1
        request_id = f"{payload.request_id}:try-{job.attempts}"
        started_at = _stamp()
        started = time.perf_counter()
        conclusion = provider.review(
            VisionReviewRequest(
                image_bytes=image_bytes,
                media_type=payload.media_type,
                request_id=request_id,
                categories=payload.categories,
                context=payload.context,
            )
        )
        self._assert_independent_second_review(payload, conclusion, job.consumer_id)
        attempt = self.attempt_store.append_attempt(
            item_id=payload.item_id,
            consumer_id=job.consumer_id,
            actor_type="agent",
            parent_attempt_id=self._parent_attempt_id(payload, job.consumer_id),
            started_at=started_at,
            completed_at=_stamp(),
            elapsed_ms=(time.perf_counter() - started) * 1000,
            **conclusion.to_attempt_payload(stage=payload.stage, attempt_number=attempt_number),
        )
        route = self._apply_route(payload, job.consumer_id, current_attempt=attempt)
        completed = self.job_store.complete(
            job.job_id,
            self.worker_id,
            {"attempt": attempt.to_dict(), "route": route.__dict__},
        )
        if route.next_stage in VISION_JOB_KINDS:
            self._enqueue_route(payload, route, attempt, job.consumer_id)
        return completed

    def _record_provider_failure(
        self,
        job: Job,
        payload: VisionReviewJobPayload | None,
        error: VisionProviderError,
    ) -> Job:
        failed = self.job_store.fail(
            job.job_id,
            self.worker_id,
            str(error),
            error_kind=error.kind.value,
            retryable=error.retryable,
            retry_after_seconds=error.retry_after_seconds,
            backoff_base_seconds=self.backoff_base_seconds,
            backoff_cap_seconds=self.backoff_cap_seconds,
        )
        if payload is None:
            return failed
        attempt_number = payload.attempt_number + job.attempts - 1
        attempt = self.attempt_store.append_attempt(
            item_id=payload.item_id,
            consumer_id=job.consumer_id,
            stage=payload.stage,
            attempt_number=attempt_number,
            actor_type="agent",
            provider=self.providers.get(payload.provider_slot).provider_name
            if self.providers.get(payload.provider_slot)
            else payload.provider_slot,
            model_id=self.providers.get(payload.provider_slot).model_id
            if self.providers.get(payload.provider_slot)
            else None,
            decision="error",
            confidence=None,
            reasons=(error.kind.value,),
            status="failed",
            parent_attempt_id=self._parent_attempt_id(payload, job.consumer_id),
            completed_at=_stamp(),
            error=str(error),
        )
        if failed.dead_lettered:
            self.review_store.apply_route(
                payload.item_id,
                stage="model_error",
                final_decision=None,
                reason_code=f"vision_{error.kind.value}_exhausted",
                consumer_id=job.consumer_id,
            )
        else:
            self._apply_route(payload, job.consumer_id, current_attempt=attempt)
        return failed

    def _apply_route(
        self,
        payload: VisionReviewJobPayload,
        consumer_id: str,
        *,
        current_attempt: ReviewAttempt | None = None,
    ) -> RouteResult:
        item = self.review_store.get(payload.item_id, consumer_id=consumer_id)
        attempts = self.attempt_store.list_attempts(payload.item_id, consumer_id=consumer_id)
        categories = sorted(
            {
                str(finding.get("category"))
                for attempt in attempts
                for finding in attempt.findings
                if finding.get("category")
            }
        )
        quality_proposal = _is_quality_proposal(payload, item.source_metadata)
        route = (
            self.router.route_proposal(
                corpus_ai_prelabel_attempts(
                    self.job_store,
                    item_id=item.item_id,
                    consumer_id=consumer_id,
                    attempts=attempts,
                    current_attempt=current_attempt,
                )
            )
            if quality_proposal
            else self.router.route(attempts, risk_score=item.top_score, categories=categories)
        )
        if quality_proposal and route.final_decision is not None:
            raise RuntimeError("quality AI proposal attempted to create a final decision")
        self.review_store.apply_route(
            payload.item_id,
            stage=route.state,
            final_decision=route.final_decision,
            reason_code=route.reason,
            consumer_id=item.consumer_id,
        )
        return route

    def _enqueue_route(
        self,
        previous: VisionReviewJobPayload,
        route: RouteResult,
        parent: ReviewAttempt,
        consumer_id: str,
    ) -> Job:
        assert route.next_stage in VISION_JOB_KINDS
        slot = self.stage_provider_slots.get(route.next_stage)
        if not slot:
            raise ValueError(f"no provider slot configured for {route.next_stage}")
        payload = VisionReviewJobPayload(
            item_id=previous.item_id,
            media_ref=previous.media_ref,
            media_type=previous.media_type,
            stage=route.next_stage,
            attempt_number=1,
            request_id=f"{previous.item_id}:{route.next_stage}:1",
            policy_version=previous.policy_version,
            content_sha256=previous.content_sha256,
            media_sha256=previous.media_sha256,
            categories=previous.categories,
            context=previous.context,
            parent_attempt_id=parent.attempt_id,
            provider_slot=slot,
        )
        return enqueue_vision_review(
            self.job_store,
            payload,
            consumer_id,
            max_attempts=self.router.config.max_attempts_per_stage,
        )

    def _assert_independent_second_review(
        self,
        payload: VisionReviewJobPayload,
        conclusion: VisionReviewConclusion,
        consumer_id: str,
    ) -> None:
        if payload.stage != "vision_review_2":
            return
        first_attempts = [
            attempt
            for attempt in self.attempt_store.list_attempts(
                payload.item_id, "vision_review_1", consumer_id=consumer_id
            )
            if attempt.status == "succeeded"
        ]
        if not first_attempts:
            raise VisionProviderError(
                VisionErrorKind.CONFIGURATION,
                "vision_review_2 requires a completed first review",
                retryable=False,
            )
        first = first_attempts[-1]
        first_identity = (first.provider, first.model_id, first.prompt_version)
        second_identity = (conclusion.provider, conclusion.model_id, conclusion.prompt_version)
        if first_identity == second_identity:
            raise VisionProviderError(
                VisionErrorKind.CONFIGURATION,
                "vision_review_2 must use an independent provider, model, or prompt",
                retryable=False,
            )

    def _parent_attempt_id(
        self, payload: VisionReviewJobPayload, consumer_id: str
    ) -> str | None:
        attempts = self.attempt_store.list_attempts(
            payload.item_id, payload.stage, consumer_id=consumer_id
        )
        return attempts[-1].attempt_id if attempts else payload.parent_attempt_id

    def _validate_job(self, job: Job, payload: VisionReviewJobPayload) -> None:
        if job.kind != payload.stage:
            raise ValueError("job kind does not match vision payload stage")
        item = self.review_store.get(payload.item_id, consumer_id=job.consumer_id)
        if item.media_ref != payload.media_ref:
            raise ValueError("queued media_ref does not match review item")
        if item.content_sha256 != payload.content_sha256:
            raise ValueError("queued content hash does not match review item")
        if item.policy_version != payload.policy_version:
            raise ValueError("queued policy version does not match review item")

    def _safe_media_path(self, media_ref: str) -> Path:
        relative = media_ref.removeprefix("media://")
        if not relative or relative.startswith("/"):
            raise VisionProviderError(
                VisionErrorKind.BAD_REQUEST, "invalid controlled media reference", retryable=False
            )
        path = (self.media_root / relative).resolve()
        if self.media_root != path and self.media_root not in path.parents:
            raise VisionProviderError(
                VisionErrorKind.BAD_REQUEST, "controlled media reference escapes media root", retryable=False
            )
        return path

    @staticmethod
    def _payload_or_none(job: Job) -> VisionReviewJobPayload | None:
        try:
            return VisionReviewJobPayload.from_mapping(job.payload)
        except ValueError:
            return None


def _is_quality_proposal(
    payload: VisionReviewJobPayload, source_metadata: Mapping[str, object]
) -> bool:
    return is_corpus_ai_prelabel_context(payload.context) and is_corpus_ai_prelabel(
        source_metadata
    )
