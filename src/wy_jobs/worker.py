from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .store import Job, JobStore

JobHandler = Callable[[Job], dict[str, Any]]


class JobExecutionError(RuntimeError):
    """A handler failure with queue-visible retry policy."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        retryable: bool,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass
class JobWorker:
    store: JobStore
    worker_id: str = ""
    lease_seconds: int = 120

    def __post_init__(self) -> None:
        self.worker_id = self.worker_id or f"worker-{uuid4().hex}"

    def run_once(self, handler: JobHandler) -> Job | None:
        job = self.store.claim(self.worker_id, self.lease_seconds)
        if job is None:
            return None
        try:
            result = handler(job)
        except JobExecutionError as exc:
            return self.store.fail(
                job.job_id,
                self.worker_id,
                str(exc),
                error_kind=exc.kind,
                retryable=exc.retryable,
                retry_after_seconds=exc.retry_after_seconds,
            )
        except Exception as exc:
            return self.store.fail(job.job_id, self.worker_id, f"{type(exc).__name__}: {exc}")
        return self.store.complete(job.job_id, self.worker_id, result)
