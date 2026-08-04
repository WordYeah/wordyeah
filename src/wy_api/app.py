import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import stat
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from wy_core.config import load_policy_config
from wy_core.contracts import ModerationResult
from wy_core.result_store import ResultStore
from wy_jobs.store import JobStore
from wy_jobs.vision import VISION_JOB_KINDS, VisionReviewJobPayload, enqueue_vision_review
from wy_media.falconsai import FalconsaiClassifier
from wy_media.g2a import G2AConfig, G2AVisionProvider
from wy_media.image_safety import ImageLimits, decode_image
from wy_media.service import MediaModerationService
from wy_media.vision_provider import AdvancedVisionProvider, VisionProviderError, VisionReviewRequest
from wy_review.store import ReviewConflictError, ReviewStore
from wy_review.attempt_store import AttemptConflictError, ReviewAttemptStore
from wy_review.router import ReviewRouter
from wy_review.quality import (
    CONTROLLED_QUALITY_LABELS,
    QualityConflictError,
    QualityStore,
)
from wy_review.workspace import Workspace, WorkspaceStore
from wy_api.login_ui import render_login_page
from wy_api.review_pages import ReviewPageContext, render_review_page
from wy_api.review_ui import WORKBENCH_JS, _filter_items, render_review_workbench

IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
APP_VERSION = "0.1.0"


class _UnavailableService:
    """Fail-closed placeholder so config errors surface through readiness."""

    cache_hits = 0
    ready = False

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def warmup(self) -> None:
        raise RuntimeError(self.reason)


@dataclass(frozen=True)
class ApiSettings:
    bind: str = "127.0.0.1"
    database_path: str = "./var/wordyeah.sqlite3"
    media_root: Path = Path("./var/media")
    max_body_bytes: int = 10 * 1024 * 1024
    api_key: str | None = None
    consumer_id: str = "default"
    policy_profile: str = "avatar-default"
    policy_path: str = "./config/policy.avatar.example.json"
    max_queue_depth: int = 1000
    max_image_width: int = 4096
    max_image_height: int = 4096
    max_image_pixels: int = 16_777_216
    max_image_frames: int = 1
    reviewer_token: str | None = None
    review_session_secret: str | None = None
    reviewer_id: str = "reviewer"
    reviewer_credentials: tuple[tuple[str, str], ...] = ()
    local_review_no_auth: bool = False
    model_path: str | None = None
    device: str = "auto"

    @classmethod
    def from_env(cls) -> "ApiSettings":
        raw_max = os.getenv("WORDYEAH_MAX_BODY_BYTES", str(10 * 1024 * 1024))
        try:
            max_body = int(raw_max)
        except ValueError as exc:
            raise ValueError("WORDYEAH_MAX_BODY_BYTES must be an integer") from exc
        if max_body < 1:
            raise ValueError("WORDYEAH_MAX_BODY_BYTES must be positive")
        raw_queue = os.getenv("WORDYEAH_MAX_QUEUE_DEPTH", "1000")
        try:
            max_queue = int(raw_queue)
        except ValueError as exc:
            raise ValueError("WORDYEAH_MAX_QUEUE_DEPTH must be an integer") from exc
        if max_queue < 1:
            raise ValueError("WORDYEAH_MAX_QUEUE_DEPTH must be positive")
        reviewer_credentials: tuple[tuple[str, str], ...] = ()
        raw_reviewers = os.getenv("WORDYEAH_REVIEWERS_JSON", "").strip()
        if raw_reviewers:
            try:
                parsed_reviewers = json.loads(raw_reviewers)
            except json.JSONDecodeError as exc:
                raise ValueError("WORDYEAH_REVIEWERS_JSON must be valid JSON") from exc
            if not isinstance(parsed_reviewers, dict) or not parsed_reviewers:
                raise ValueError("WORDYEAH_REVIEWERS_JSON must be a non-empty object")
            normalized: list[tuple[str, str]] = []
            for reviewer, token in parsed_reviewers.items():
                if (
                    not isinstance(reviewer, str)
                    or not reviewer.strip()
                    or len(reviewer) > 128
                    or not isinstance(token, str)
                    or len(token) < 16
                ):
                    raise ValueError(
                        "WORDYEAH_REVIEWERS_JSON keys must be reviewer IDs and tokens at least 16 characters"
                    )
                normalized.append((reviewer, token))
            reviewer_credentials = tuple(sorted(normalized))
        return cls(
            bind=os.getenv("WORDYEAH_BIND", "127.0.0.1"),
            database_path=os.getenv("WORDYEAH_DATABASE", "./var/wordyeah.sqlite3"),
            media_root=Path(os.getenv("WORDYEAH_MEDIA_ROOT", "./var/media")).expanduser(),
            max_body_bytes=max_body,
            api_key=os.getenv("WORDYEAH_API_KEY") or None,
            consumer_id=os.getenv("WORDYEAH_CONSUMER_ID", "default"),
            policy_profile=os.getenv("WORDYEAH_POLICY_PROFILE", "avatar-default"),
            policy_path=os.getenv("WORDYEAH_POLICY_PATH", "./config/policy.avatar.example.json"),
            max_queue_depth=max_queue,
            max_image_width=int(os.getenv("WORDYEAH_MAX_IMAGE_WIDTH", "4096")),
            max_image_height=int(os.getenv("WORDYEAH_MAX_IMAGE_HEIGHT", "4096")),
            max_image_pixels=int(os.getenv("WORDYEAH_MAX_IMAGE_PIXELS", "16777216")),
            max_image_frames=int(os.getenv("WORDYEAH_MAX_IMAGE_FRAMES", "1")),
            reviewer_token=os.getenv("WORDYEAH_REVIEWER_TOKEN") or None,
            review_session_secret=os.getenv("WORDYEAH_REVIEW_SESSION_SECRET") or None,
            reviewer_id=os.getenv("WORDYEAH_REVIEWER_ID", "reviewer"),
            reviewer_credentials=reviewer_credentials,
            local_review_no_auth=os.getenv("WORDYEAH_LOCAL_REVIEW_NO_AUTH", "").strip().lower()
            in {"1", "true", "yes", "on"},
            model_path=os.getenv("WORDYEAH_MEDIA_MODEL_PATH") or None,
            device=os.getenv("WORDYEAH_DEVICE", "auto"),
        )


def build_service(settings: ApiSettings) -> MediaModerationService:
    policy_config = load_policy_config(settings.policy_path)
    if policy_config.profile != settings.policy_profile:
        raise ValueError(
            f"policy profile mismatch: configured={settings.policy_profile}, "
            f"file={policy_config.profile}"
        )
    return MediaModerationService(
        FalconsaiClassifier(
            model_path=settings.model_path,
            device=settings.device,
            limits=ImageLimits(
                max_bytes=settings.max_body_bytes,
                max_width=settings.max_image_width,
                max_height=settings.max_image_height,
                max_pixels=settings.max_image_pixels,
                max_frames=settings.max_image_frames,
            ),
        ),
        policy=policy_config.media_policy,
        policy_version=policy_config.policy_version,
    )


def _error_result(source: ModerationResult, reason: str, error: str) -> ModerationResult:
    reasons = source.reasons if reason in source.reasons else (*source.reasons, reason)
    return ModerationResult(
        request_id=source.request_id,
        content_sha256=source.content_sha256,
        media_type=source.media_type,
        decision="error",
        reasons=reasons,
        findings=source.findings,
        top_score=source.top_score,
        model_versions=source.model_versions,
        elapsed_ms=source.elapsed_ms,
        error=error,
    )


def create_app(
    settings: ApiSettings | None = None,
    service: MediaModerationService | None = None,
    review_store: ReviewStore | None = None,
    attempt_store: ReviewAttemptStore | None = None,
    job_store: JobStore | None = None,
    result_store: ResultStore | None = None,
    advanced_vision_provider: AdvancedVisionProvider | None = None,
    workspace_store: WorkspaceStore | None = None,
    quality_store: QualityStore | None = None,
):
    """Create the avatar API without loading a model at import time."""

    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import (
        FileResponse,
        HTMLResponse,
        JSONResponse,
        PlainTextResponse,
        RedirectResponse,
        Response,
    )

    settings = settings or ApiSettings.from_env()
    if settings.bind not in {"127.0.0.1", "::1", "localhost"} and settings.api_key is None:
        raise ValueError("non-loopback bind requires WORDYEAH_API_KEY")
    if settings.local_review_no_auth and settings.bind not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("WORDYEAH_LOCAL_REVIEW_NO_AUTH is only allowed on a loopback bind")
    startup_error: str | None = None
    if service is None:
        try:
            service = build_service(settings)
        except Exception as exc:  # readiness exposes config/model failures without allowing traffic
            startup_error = f"{type(exc).__name__}: {exc}"
            service = _UnavailableService(startup_error)
    review_store = review_store or ReviewStore(settings.database_path)
    attempt_store = attempt_store or ReviewAttemptStore(settings.database_path)
    review_router = ReviewRouter()
    job_store = job_store or JobStore(settings.database_path)
    result_store = result_store or ResultStore(settings.database_path)
    workspace_store = workspace_store or WorkspaceStore(settings.database_path)
    quality_store = quality_store or QualityStore(settings.database_path)
    try:
        workspace_store.get(settings.consumer_id, settings.consumer_id)
    except KeyError:
        workspace_store.create(
            workspace_id=settings.consumer_id,
            consumer_id=settings.consumer_id,
            name="Cravatar" if settings.consumer_id == "cravatar" else settings.consumer_id,
            adapter="cravatar" if settings.consumer_id == "cravatar" else "generic",
            policy_profile=settings.policy_profile,
        )
    advanced_vision_provider = advanced_vision_provider or G2AVisionProvider(G2AConfig.from_env())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ready = False
        app.state.ready_error = startup_error
        if startup_error is None:
            try:
                service.warmup()
                app.state.ready = True
            except Exception as exc:  # readiness must expose model failures, not hide them
                app.state.ready_error = f"{type(exc).__name__}: {exc}"
        yield
        review_store.close()
        attempt_store.close()
        job_store.close()
        result_store.close()
        workspace_store.close()
        quality_store.close()

    app = FastAPI(title="WordYeah Avatar Moderation API", version=APP_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service
    app.state.review_store = review_store
    app.state.attempt_store = attempt_store
    app.state.review_router = review_router
    app.state.job_store = job_store
    app.state.result_store = result_store
    app.state.workspace_store = workspace_store
    app.state.quality_store = quality_store
    app.state.advanced_vision_provider = advanced_vision_provider
    app.state.ready = False
    app.state.ready_error = None

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; img-src 'self' https://cn.cravatar.com; style-src 'unsafe-inline'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        if request.url.path.startswith("/review"):
            response.headers["Cache-Control"] = "private, no-store"
        return response

    def require_api_access(request: Request) -> None:
        client_host = request.client.host if request.client else ""
        if settings.api_key is None and client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            raise HTTPException(status_code=403, detail="api key required for non-loopback access")
        if settings.api_key is not None:
            expected = f"Bearer {settings.api_key}"
            if request.headers.get("Authorization") != expected:
                raise HTTPException(status_code=401, detail="unauthorized")

    async def read_limited_body(request: Request) -> bytes:
        declared = request.headers.get("Content-Length")
        if declared is None or not declared.isdigit():
            raise HTTPException(status_code=411, detail="content-length required")
        if int(declared) > settings.max_body_bytes:
            raise HTTPException(status_code=413, detail="body exceeds configured limit")
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > settings.max_body_bytes:
                raise HTTPException(status_code=413, detail="body exceeds configured limit")
            chunks.append(chunk)
        return b"".join(chunks)

    reviewer_credentials = dict(settings.reviewer_credentials)
    if not reviewer_credentials and settings.reviewer_token is not None:
        reviewer_credentials[settings.reviewer_id] = settings.reviewer_token
    if reviewer_credentials:
        credential_material = "\0".join(
            f"{reviewer}\0{token}" for reviewer, token in sorted(reviewer_credentials.items())
        )
        review_secret = hmac.new(
            (settings.review_session_secret or "wordyeah-review-session").encode("utf-8"),
            credential_material.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    else:
        review_secret = None
    failed_logins: dict[str, list[float]] = {}
    session_ttl_seconds = 3600
    local_review_csrf = base64.urlsafe_b64encode(os.urandom(18)).decode("ascii").rstrip("=")

    def _store_review_preview(image_bytes: bytes, content_sha256: str) -> str:
        """Write a bounded, normalized reviewer preview outside SQLite."""

        image = decode_image(
            image_bytes,
            ImageLimits(
                max_bytes=settings.max_body_bytes,
                max_width=settings.max_image_width,
                max_height=settings.max_image_height,
                max_pixels=settings.max_image_pixels,
                max_frames=settings.max_image_frames,
            ),
        )
        image.thumbnail((1600, 1600))
        relative = Path("review") / f"{content_sha256}.jpg"
        target = settings.media_root.expanduser() / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_name(f".{target.name}.{os.getpid()}.{os.urandom(6).hex()}.tmp")
            try:
                image.save(temporary, format="JPEG", quality=88, optimize=True)
                temporary.chmod(0o600)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return f"media://{relative.as_posix()}"

    def _client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _ip_hash(request: Request) -> str:
        return hashlib.sha256(_client_ip(request).encode("utf-8")).hexdigest()[:24]

    def _issue_review_session(reviewer_id: str) -> tuple[str, str]:
        if review_secret is None:
            raise HTTPException(status_code=503, detail="reviewer authentication is not configured")
        csrf_token = base64.urlsafe_b64encode(os.urandom(18)).decode("ascii").rstrip("=")
        expires = int(time.time()) + session_ttl_seconds
        payload = f"{reviewer_id}\x00{expires}\x00{csrf_token}".encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        signature = hmac.new(review_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}", csrf_token

    def _read_review_session(request: Request) -> tuple[str, str]:
        if settings.local_review_no_auth:
            return settings.reviewer_id, local_review_csrf
        if not reviewer_credentials or review_secret is None:
            raise HTTPException(status_code=503, detail="reviewer authentication is not configured")
        value = request.cookies.get("wordyeah_review_session", "")
        try:
            encoded, signature = value.split(".", 1)
            padding = "=" * (-len(encoded) % 4)
            payload = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
            expected = hmac.new(review_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("invalid signature")
            reviewer, expires_text, csrf_token = payload.decode("utf-8").split("\x00", 2)
            if reviewer not in reviewer_credentials or int(expires_text) < int(time.time()) or not csrf_token:
                raise ValueError("expired session")
        except (ValueError, UnicodeError, base64.binascii.Error) as exc:
            raise HTTPException(status_code=401, detail="reviewer session required") from exc
        return reviewer, csrf_token

    def require_reviewer(request: Request) -> tuple[str, str]:
        return _read_review_session(request)

    def require_csrf(request: Request, csrf_token: str | None, session_csrf: str) -> None:
        supplied = request.headers.get("X-CSRF-Token") or csrf_token
        if not supplied or not hmac.compare_digest(supplied, session_csrf):
            raise HTTPException(status_code=403, detail="csrf token required")

    def _review_workspace(request: Request) -> Workspace:
        workspace_id = request.cookies.get("wordyeah_review_workspace") or settings.consumer_id
        try:
            workspace = workspace_store.get(workspace_id, settings.consumer_id)
        except KeyError:
            workspace = workspace_store.get(settings.consumer_id, settings.consumer_id)
        if not workspace.enabled:
            raise HTTPException(status_code=403, detail="review workspace is disabled")
        return workspace

    def _quality_vocabulary(consumer_id: str) -> None:
        """Create the immutable built-in vocabulary on first use per workspace."""

        quality_store.create_vocabulary(
            consumer_id=consumer_id,
            version="v1",
            actor_id="wordyeah-system",
        )

    async def read_review_payload(request: Request) -> dict[str, Any]:
        body = await request.body()
        if len(body) > 64 * 1024:
            raise HTTPException(status_code=413, detail="review payload too large")
        if not body:
            return {}
        content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type == "application/json":
            try:
                value = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="invalid review JSON") from exc
            if not isinstance(value, dict):
                raise HTTPException(status_code=400, detail="review payload must be an object")
            return value
        values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        return {key: entries[-1] for key, entries in values.items()}

    def _consumer_items(consumer_id: str, limit: int = 1000) -> list[Any]:
        return review_store.list_items(status=None, consumer_id=consumer_id, limit=limit)

    def _sanitize_review_return_to(raw_return_to: object, *, fallback: str = "/review") -> str:
        if not isinstance(raw_return_to, str) or not raw_return_to:
            return fallback
        parsed = urlsplit(raw_return_to)
        if parsed.scheme or parsed.netloc or parsed.path != "/review":
            return fallback
        query_values = parse_qs(parsed.query, keep_blank_values=True)
        cleaned: dict[str, str] = {}
        for key in ("status", "risk", "q", "view", "focus", "batch"):
            values = query_values.get(key)
            if not values:
                continue
            value = values[-1]
            if key == "batch":
                if value == "1":
                    cleaned[key] = value
                continue
            cleaned[key] = value
        fragment = parsed.fragment if parsed.fragment == "review-queue" else ""
        return urlunsplit(("", "", "/review", urlencode(cleaned), fragment))

    def _planned_review_return(
        item_id: str, raw_return_to: object, consumer_id: str
    ) -> str:
        target = _sanitize_review_return_to(raw_return_to)
        parsed = urlsplit(target)
        values = parse_qs(parsed.query, keep_blank_values=True)
        view_mode = (values.get("view") or ["list"])[-1]
        focus_item_id = (values.get("focus") or [None])[-1]
        if view_mode != "focus" or focus_item_id != item_id:
            return target
        filtered_items = _filter_items(
            _consumer_items(consumer_id),
            search_query=(values.get("q") or [""])[-1],
            status_filter=(values.get("status") or ["pending"])[-1],
            risk_filter=(values.get("risk") or ["all"])[-1],
        )
        focus_ids = [item.item_id for item in filtered_items]
        try:
            focus_index = focus_ids.index(item_id)
        except ValueError:
            return target
        next_item_id = focus_ids[focus_index + 1] if focus_index < len(focus_ids) - 1 else None
        if next_item_id is None:
            values.pop("focus", None)
            values["view"] = ["list"]
        else:
            values["focus"] = [next_item_id]
            values["view"] = ["focus"]
        rebuilt = urlencode(
            {
                key: values[key][-1]
                for key in ("status", "risk", "q", "view", "focus", "batch")
                if key in values and (key != "batch" or values[key][-1] == "1")
            }
        )
        return urlunsplit(("", "", "/review", rebuilt, parsed.fragment))

    def _attempt_signals(item: Any, attempts: list[Any]) -> set[str]:
        signals = {reason.lower() for reason in item.reasons}
        for finding in item.findings:
            for field in ("category", "label"):
                value = finding.get(field)
                if value:
                    signals.add(str(value).lower())
        for attempt in attempts:
            signals.update(str(reason).lower() for reason in attempt.reasons)
            for finding in attempt.findings:
                for field in ("category", "label"):
                    value = finding.get(field)
                    if value:
                        signals.add(str(value).lower())
        return signals

    def _batch_blocker(item: Any, attempts: list[Any]) -> str | None:
        if item.status != "pending" or item.stage != "human_required":
            return "only pending human_required items can use batch review"
        if item.quality_sample:
            return "quality sample requires individual review"
        if item.arbitration_required:
            return "arbitration-required item cannot use ordinary batch review"
        if item.appealed:
            return "appealed item cannot use ordinary batch review"
        signals = _attempt_signals(item, attempts)
        if any(
            token in signals
            for token in {
                "political",
                "political_person",
                "political_symbol",
                "political_text",
                "minor",
                "minor_identity",
                "underage",
                "child",
            }
        ):
            return "political or minor-sensitive item cannot use ordinary batch review"
        if not any(attempt.evidence for attempt in attempts):
            return "item is missing review evidence for ordinary batch review"
        return None

    def _review_html_page(items: list[Any], csrf_token: str) -> str:
        rows: list[str] = []
        for item in items:
            preview = ""
            if item.media_ref.startswith("media://"):
                preview = (
                    f'<img class="preview" src="/review/items/{html.escape(item.item_id)}/media" '
                    'alt="受控头像预览">'
                )
            findings = "<br>".join(
                html.escape(
                    f"{finding.get('category', '')}/{finding.get('label', '')}: "
                    f"{finding.get('score', '')} ({finding.get('source', '')})"
                )
                for finding in item.findings
            ) or "无 finding"
            row = f"""
            <article class="item">
              <div class="media">{preview or '<div class="no-preview">无可预览原图</div>'}</div>
              <div class="evidence">
                <h2>{html.escape(item.item_id)}</h2>
                <p>提示：<strong>{html.escape(item.decision_hint)}</strong> · 状态：{html.escape(item.status)} · 版本：{item.version}</p>
                <p>SHA-256：<code>{html.escape(item.content_sha256)}</code></p>
                <p>原因：{html.escape(', '.join(item.reasons) or '无')}</p>
                <p>模型证据：{findings}</p>
                <p>策略：{html.escape(item.policy_version)} · consumer：{html.escape(item.consumer_id)}</p>
                <form method="post" action="/review/items/{html.escape(item.item_id)}/approve">
                  <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
                  <input type="hidden" name="version" value="{item.version}">
                  <input name="note" maxlength="2000" placeholder="审核备注">
                  <button type="submit">通过</button>
                </form>
                <form method="post" action="/review/items/{html.escape(item.item_id)}/reject">
                  <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
                  <input type="hidden" name="version" value="{item.version}">
                  <input name="note" maxlength="2000" placeholder="审核备注">
                  <button type="submit">拒绝</button>
                </form>
                <form method="post" action="/review/items/{html.escape(item.item_id)}/hold">
                  <input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}">
                  <input type="hidden" name="version" value="{item.version}">
                  <input name="note" maxlength="2000" placeholder="暂缓原因">
                  <button type="submit">暂缓</button>
                </form>
              </div>
            </article>
            """
            rows.append(row)
        body = "\n".join(rows) or "<p>没有待审核项目。</p>"
        return f"""<!doctype html>
        <html lang="zh-CN"><head><meta charset="utf-8"><title>WordYeah 会语审核</title>
        <style>
        body{{font-family:system-ui,sans-serif;background:#101318;color:#e8edf2;margin:2rem}}
        .item{{display:grid;grid-template-columns:180px 1fr;gap:1.2rem;border:1px solid #38404c;border-radius:8px;padding:1rem;margin:1rem 0;background:#171c24}}
        .preview{{max-width:160px;max-height:160px;object-fit:contain;background:#090b0f}}
        .no-preview{{height:160px;display:grid;place-items:center;background:#252b35;color:#aeb8c4;font-size:.9rem}}
        code{{overflow-wrap:anywhere}} form{{display:inline-flex;gap:.4rem;margin:.25rem .4rem .25rem 0}} input{{max-width:260px;padding:.35rem}} button{{padding:.35rem .7rem}}
        </style></head><body><h1>WordYeah 会语头像审核</h1>
        <p>证据优先；人工 decision 与模型提示分开。当前 consumer：{html.escape(settings.consumer_id)}</p>
        {body}</body></html>"""

    def _route_item(item_id: str, *, risk_score: float | None = None) -> object:
        item = review_store.get(item_id, consumer_id=settings.consumer_id)
        attempts = attempt_store.list_attempts(item_id, consumer_id=settings.consumer_id)
        categories = sorted(
            {
                str(finding.get("category"))
                for attempt in attempts
                for finding in attempt.findings
                if finding.get("category")
            }
        )
        route = review_router.route(attempts, risk_score=risk_score, categories=categories)
        review_store.apply_route(
            item_id,
            stage=route.state,
            final_decision=route.final_decision,
            reason_code=route.reason,
            consumer_id=settings.consumer_id,
        )
        if route.next_stage in VISION_JOB_KINDS:
            if job_store.count_active(settings.consumer_id) >= settings.max_queue_depth:
                review_store.apply_route(
                    item_id,
                    stage="model_error",
                    final_decision=None,
                    reason_code="vision_queue_full",
                    consumer_id=settings.consumer_id,
                )
                return route
            stage = route.next_stage
            attempt_number = attempt_store.next_attempt_number(
                item_id, stage, consumer_id=settings.consumer_id
            )
            parent_attempt_id = attempts[-1].attempt_id if attempts else None
            payload = VisionReviewJobPayload(
                item_id=item.item_id,
                media_ref=item.media_ref,
                media_type=_media_type_for_ref(item.media_ref),
                stage=stage,
                attempt_number=attempt_number,
                request_id=f"{item.item_id}:{stage}:{attempt_number}",
                policy_version=item.policy_version,
                content_sha256=item.content_sha256,
                categories=tuple(categories),
                context=f"consumer={item.consumer_id}; policy={item.policy_version}",
                parent_attempt_id=parent_attempt_id,
                provider_slot="primary" if stage == "vision_review_1" else "secondary",
            )
            enqueue_vision_review(
                job_store,
                payload,
                settings.consumer_id,
                max_attempts=review_router.config.max_attempts_per_stage,
            )
        return route

    def _media_type_for_ref(media_ref: str) -> str:
        suffix = Path(media_ref.removeprefix("media://")).suffix.lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }.get(suffix, "image/jpeg")

    def _record_fast_scan(item_id: str, result: ModerationResult) -> None:
        if attempt_store.list_attempts(
            item_id, "fast_scan", consumer_id=settings.consumer_id
        ):
            return
        attempt_store.append_attempt(
            item_id=item_id,
            consumer_id=settings.consumer_id,
            stage="fast_scan",
            attempt_number=1,
            actor_type="agent",
            provider="local",
            model_id="media.nsfw",
            model_version=result.model_versions.get("media.nsfw"),
            prompt_version="none",
            decision=result.decision,
            confidence=result.top_score,
            reasons=result.reasons,
            findings=result.to_dict()["findings"],
            status="failed" if result.decision == "error" else "succeeded",
            elapsed_ms=result.elapsed_ms,
            error=result.error,
        )
        _route_item(item_id, risk_score=result.top_score)

    def _enqueue_manual_vision_retry(item: Any, consumer_id: str) -> None:
        attempts = attempt_store.list_attempts(
            item.item_id, consumer_id=consumer_id
        )
        vision_attempts = [
            attempt
            for attempt in attempts
            if attempt.stage in {"vision_review_1", "vision_review_2"}
        ]
        stage = vision_attempts[-1].stage if vision_attempts else "vision_review_1"
        attempt_number = attempt_store.next_attempt_number(
            item.item_id, stage, consumer_id=consumer_id
        )
        categories = tuple(
            sorted(
                {
                    str(finding.get("category"))
                    for attempt in attempts
                    for finding in attempt.findings
                    if finding.get("category")
                }
            )
        )
        payload = VisionReviewJobPayload(
            item_id=item.item_id,
            media_ref=item.media_ref,
            media_type=_media_type_for_ref(item.media_ref),
            stage=stage,
            attempt_number=attempt_number,
            request_id=f"{item.item_id}:{stage}:{attempt_number}:manual-retry",
            policy_version=item.policy_version,
            content_sha256=item.content_sha256,
            categories=categories,
            context=f"consumer={item.consumer_id}; policy={item.policy_version}; manual_retry=true",
            parent_attempt_id=vision_attempts[-1].attempt_id if vision_attempts else None,
            provider_slot="primary" if stage == "vision_review_1" else "secondary",
        )
        enqueue_vision_review(
            job_store,
            payload,
            consumer_id,
            max_attempts=review_router.config.max_attempts_per_stage,
        )

    @app.get("/health/live")
    async def health_live() -> dict[str, object]:
        return {
            "status": "ok",
            "external_model_calls": bool(advanced_vision_provider.enabled),
            "advanced_vision_provider": advanced_vision_provider.provider_name,
        }

    @app.get("/favicon.ico", include_in_schema=False, response_class=Response)
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/health/ready")
    async def health_ready() -> dict[str, object]:
        if not app.state.ready:
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "error": app.state.ready_error},
            )
        return {
            "status": "ready",
            "model_ready": service.ready,
            "database": "ok",
            "advanced_vision": {
                "provider": advanced_vision_provider.provider_name,
                "enabled": bool(advanced_vision_provider.enabled),
            },
        }

    @app.get("/version")
    async def version() -> dict[str, object]:
        return {"version": APP_VERSION, "schema_version": 5, "policy_profile": settings.policy_profile}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> str:
        ready = 1 if app.state.ready else 0
        cache_hits = int(getattr(service, "cache_hits", 0))
        review_metrics = review_store.metrics(settings.consumer_id)
        action_metrics = {
            key.removeprefix("action_"): value
            for key, value in review_metrics.items()
            if key.startswith("action_")
        }
        action_lines = "".join(
            f'wordyeah_review_actions_total{{action="{action}"}} {int(value)}\n'
            for action, value in sorted(action_metrics.items())
        )
        return (
            "# TYPE wordyeah_ready gauge\n"
            f"wordyeah_ready {ready}\n"
            "# TYPE wordyeah_media_cache_hits counter\n"
            f"wordyeah_media_cache_hits {cache_hits}\n"
            "# TYPE wordyeah_review_pending gauge\n"
            f"wordyeah_review_pending {int(review_metrics['pending'])}\n"
            "# TYPE wordyeah_review_pending_age_seconds gauge\n"
            f"wordyeah_review_pending_age_seconds {float(review_metrics['pending_age_seconds'])}\n"
            "# TYPE wordyeah_review_overturned_total counter\n"
            f"wordyeah_review_overturned_total {int(review_metrics['overturned'])}\n"
            "# TYPE wordyeah_review_actions_total counter\n"
            f"{action_lines}"
        )

    @app.post("/v1/moderate/image")
    async def moderate_image(request: Request) -> JSONResponse:
        require_api_access(request)
        if not app.state.ready:
            raise HTTPException(status_code=503, detail="model is not ready")
        content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type not in IMAGE_CONTENT_TYPES:
            raise HTTPException(status_code=415, detail="unsupported image content type")
        body = await read_limited_body(request)
        result = service.moderate_image(body)
        media_ref = f"sha256://{result.content_sha256}"
        if result.decision in {"review", "block", "error"}:
            try:
                media_ref = _store_review_preview(body, result.content_sha256)
            except Exception as exc:
                result = _error_result(
                    result,
                    "review_preview_failed",
                    f"{type(exc).__name__}: {exc}",
                )
        try:
            result_store.record(result, settings.consumer_id, media_ref, settings.policy_profile)
        except Exception as exc:
            result = _error_result(result, "result_persistence_failed", f"{type(exc).__name__}: {exc}")
        if result.decision in {"review", "block", "error"}:
            try:
                item = review_store.enqueue(result, media_ref, consumer_id=settings.consumer_id)
                _record_fast_scan(item.item_id, result)
            except Exception as exc:
                result = _error_result(result, "review_queue_failed", f"{type(exc).__name__}: {exc}")
        status_code = 422 if result.decision == "error" else 200
        return JSONResponse(result.to_dict(), status_code=status_code)

    @app.post("/v1/jobs", status_code=202)
    async def create_job(request: Request) -> dict[str, Any]:
        require_api_access(request)
        body = await read_limited_body(request)
        if len(body) > 64 * 1024:
            raise HTTPException(status_code=413, detail="job payload too large")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid job JSON: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("kind") != "moderate_image":
            raise HTTPException(status_code=400, detail="only moderate_image jobs are supported")
        media_ref = payload.get("media_ref")
        if not isinstance(media_ref, str) or not media_ref.startswith("media://") or len(media_ref) > 512:
            raise HTTPException(status_code=400, detail="media_ref must be a controlled media:// reference")
        if job_store.count_active(settings.consumer_id) >= settings.max_queue_depth:
            raise HTTPException(
                status_code=429,
                detail="consumer queue is full",
                headers={"Retry-After": "1"},
            )
        job = job_store.enqueue(
            "moderate_image",
            {"media_ref": media_ref},
            settings.consumer_id,
        )
        return job.to_dict()

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str, request: Request) -> dict[str, Any]:
        require_api_access(request)
        try:
            return job_store.get(job_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

    @app.post("/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
        require_api_access(request)
        try:
            return job_store.cancel(job_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

    @app.get("/review/login", response_class=HTMLResponse, response_model=None)
    async def review_login_page(request: Request) -> HTMLResponse | RedirectResponse:
        if settings.local_review_no_auth:
            return RedirectResponse("/review/overview", status_code=303)
        if not reviewer_credentials:
            raise HTTPException(status_code=503, detail="reviewer authentication is not configured")
        try:
            require_reviewer(request)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
        else:
            return RedirectResponse("/review", status_code=303)
        return HTMLResponse(
            render_login_page(
                expired=request.query_params.get("expired") == "1",
                show_reviewer_id=len(reviewer_credentials) > 1,
                default_reviewer_id=next(iter(reviewer_credentials))
                if len(reviewer_credentials) == 1
                else "",
            )
        )

    @app.post("/review/login", response_model=None)
    async def review_login(request: Request) -> JSONResponse | RedirectResponse:
        if settings.local_review_no_auth:
            if "text/html" in request.headers.get("Accept", ""):
                return RedirectResponse("/review/overview", status_code=303)
            return JSONResponse(
                {"status": "ok", "reviewer": settings.reviewer_id, "csrf_token": local_review_csrf}
            )
        if not reviewer_credentials or review_secret is None:
            raise HTTPException(status_code=503, detail="reviewer authentication is not configured")
        now = time.time()
        ip = _client_ip(request)
        recent = [stamp for stamp in failed_logins.get(ip, []) if now - stamp < 60]
        if len(recent) >= 5:
            raise HTTPException(status_code=429, detail="too many login attempts", headers={"Retry-After": "60"})
        body = await request.body()
        if len(body) > 64 * 1024:
            raise HTTPException(status_code=413, detail="login payload too large")
        content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        try:
            if content_type == "application/json":
                payload = json.loads(body.decode("utf-8"))
                token = payload.get("token") if isinstance(payload, dict) else None
                reviewer_id = payload.get("reviewer_id") if isinstance(payload, dict) else None
            else:
                values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                token = values.get("token", [None])[-1]
                reviewer_id = values.get("reviewer_id", [None])[-1]
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid login payload") from exc
        if reviewer_id in (None, "") and len(reviewer_credentials) == 1:
            reviewer_id = next(iter(reviewer_credentials))
        expected_token = reviewer_credentials.get(reviewer_id) if isinstance(reviewer_id, str) else None
        if (
            expected_token is None
            or not isinstance(token, str)
            or not hmac.compare_digest(token, expected_token)
        ):
            recent.append(now)
            failed_logins[ip] = recent
            raise HTTPException(status_code=401, detail="invalid reviewer token")
        failed_logins.pop(ip, None)
        cookie, csrf_token = _issue_review_session(reviewer_id)
        if "text/html" in request.headers.get("Accept", ""):
            response: JSONResponse | RedirectResponse = RedirectResponse("/review", status_code=303)
        else:
            response = JSONResponse({"status": "ok", "reviewer": reviewer_id, "csrf_token": csrf_token})
        response.set_cookie(
            "wordyeah_review_session",
            cookie,
            max_age=session_ttl_seconds,
            httponly=True,
            samesite="strict",
            path="/review",
        )
        return response

    @app.post("/review/logout", response_model=None)
    async def review_logout(request: Request) -> JSONResponse | RedirectResponse:
        _, session_csrf = require_reviewer(request)
        payload = await read_review_payload(request)
        require_csrf(request, payload.get("csrf_token"), session_csrf)
        if settings.local_review_no_auth:
            if "text/html" in request.headers.get("Accept", ""):
                return RedirectResponse("/review", status_code=303)
            return JSONResponse({"status": "ok"})
        if "text/html" in request.headers.get("Accept", ""):
            response: JSONResponse | RedirectResponse = RedirectResponse("/review/login", status_code=303)
        else:
            response = JSONResponse({"status": "ok"})
        response.delete_cookie("wordyeah_review_session", path="/review")
        return response

    @app.get("/review/workspaces")
    async def list_review_workspaces(request: Request) -> dict[str, object]:
        require_reviewer(request)
        active = _review_workspace(request)
        workspaces = [
            workspace
            for workspace in workspace_store.list_for_consumer(settings.consumer_id)
            if workspace.enabled
        ]
        return {
            "active_workspace_id": active.workspace_id,
            "workspaces": [
                {
                    "workspace_id": workspace.workspace_id,
                    "name": workspace.name,
                    "adapter": workspace.adapter,
                    "policy_profile": workspace.policy_profile,
                }
                for workspace in workspaces
            ],
        }

    @app.post("/review/workspaces/{workspace_id}/select", response_model=None)
    async def select_review_workspace(
        workspace_id: str, request: Request
    ) -> JSONResponse | RedirectResponse:
        _, session_csrf = require_reviewer(request)
        payload = await read_review_payload(request)
        require_csrf(request, payload.get("csrf_token"), session_csrf)
        try:
            workspace = workspace_store.get(workspace_id, settings.consumer_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review workspace not found") from exc
        if not workspace.enabled:
            raise HTTPException(status_code=403, detail="review workspace is disabled")
        response: JSONResponse | RedirectResponse
        if "text/html" in request.headers.get("Accept", ""):
            return_to = payload.get("return_to")
            allowed_returns = {
                "/review",
                "/review/overview",
                "/review/agents",
                "/review/policies",
                "/review/quality",
                "/review/history",
                "/review/health",
                "/review/account",
                "/review/guide",
            }
            response = RedirectResponse(
                return_to if isinstance(return_to, str) and return_to in allowed_returns else "/review",
                status_code=303,
            )
        else:
            response = JSONResponse({"active_workspace_id": workspace.workspace_id})
        response.set_cookie(
            "wordyeah_review_workspace",
            workspace.workspace_id,
            max_age=session_ttl_seconds,
            httponly=True,
            samesite="strict",
            path="/review",
        )
        return response

    @app.get("/review", response_class=HTMLResponse, response_model=None)
    async def review_page(request: Request) -> HTMLResponse | RedirectResponse:
        try:
            reviewer, csrf_token = require_reviewer(request)
        except HTTPException as exc:
            if exc.status_code == 401 and "text/html" in request.headers.get("Accept", ""):
                return RedirectResponse("/review/login?expired=1", status_code=303)
            raise
        focus_item_id = request.query_params.get("focus") or None
        search_query = request.query_params.get("q", "").strip()
        status_filter = request.query_params.get("status", "pending")
        risk_filter = request.query_params.get("risk", "all")
        view_mode = request.query_params.get("view", "list")
        batch_mode = request.query_params.get("batch") == "1"
        batch_result = request.query_params.get("batch_result", "")
        workspace = _review_workspace(request)
        items = review_store.list_items(
            status=None, consumer_id=workspace.workspace_id, limit=1000
        )
        events = review_store.list_all_events(workspace.workspace_id, limit=1000)
        return HTMLResponse(
            render_review_workbench(
                items=items,
                events=events,
                csrf_token=csrf_token,
                consumer_id=workspace.workspace_id,
                reviewer_id=reviewer,
                policy_profile=workspace.policy_profile,
                service_ready=bool(app.state.ready),
                service_error=app.state.ready_error,
                focus_item_id=focus_item_id,
                metrics=review_store.metrics(workspace.workspace_id),
                search_query=search_query,
                status_filter=status_filter,
                risk_filter=risk_filter,
                view_mode=view_mode,
                batch_mode=batch_mode,
                batch_result=batch_result,
                workspaces=(
                    {
                        "workspace_id": candidate.workspace_id,
                        "name": candidate.name,
                        "adapter": candidate.adapter,
                    }
                    for candidate in workspace_store.list_for_consumer(settings.consumer_id)
                    if candidate.enabled
                ),
            )
        )

    @app.get("/review/assets/workbench.js", response_class=Response, response_model=None)
    async def review_workbench_script() -> Response:
        return Response(WORKBENCH_JS, media_type="application/javascript")

    @app.get("/review/assets/cravatar-ban.png", response_class=FileResponse, response_model=None)
    async def review_cravatar_ban_asset() -> FileResponse:
        return FileResponse(
            Path(__file__).with_name("assets") / "cravatar-ban.png",
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )

    def _support_page_data(
        page: str,
        consumer_id: str,
        reviewer_id: str | None = None,
        csrf_token: str | None = None,
        quality_offset: int = 0,
        quality_batch_id: str | None = None,
    ) -> dict[str, object]:
        items = _consumer_items(consumer_id)
        consumer_item_ids = {item.item_id for item in items}
        attempts = [
            attempt
            for attempt in attempt_store.list_recent(5000, consumer_id=consumer_id)
            if attempt.item_id in consumer_item_ids
        ][:1000]
        events = review_store.list_all_events(consumer_id, limit=1000)
        pending = [item for item in items if item.status == "pending"]
        held = [item for item in items if item.status == "held"]
        human = [item for item in pending if item.stage == "human_required"]
        active_items = [item for item in items if item.status in {"pending", "held"}]
        stage_counts: dict[str, int] = {}
        for item in active_items:
            stage_counts[item.stage] = stage_counts.get(item.stage, 0) + 1
        failed_attempts = [attempt for attempt in attempts if attempt.status == "failed"]
        common_exceptions: list[dict[str, str]] = []
        if not app.state.ready:
            common_exceptions.append(
                {"title": "模型服务未就绪", "detail": app.state.ready_error or "readiness 检查失败", "tone": "danger"}
            )
        if held:
            common_exceptions.append(
                {"title": "存在留置项目", "detail": f"{len(held)} 条需要检查错误或证据", "tone": "warning"}
            )
        metrics = [
            {"label": "待处理", "value": len(pending), "detail": "全部 AI 与人工阶段"},
            {"label": "需人工", "value": len(human), "detail": "AI 二审后仍不确定"},
            {"label": "模型失败", "value": len(failed_attempts), "detail": "追加式 attempt 记录"},
        ]
        if page == "overview":
            today = datetime.now(timezone.utc).date()
            days = [today - timedelta(days=offset) for offset in range(13, -1, -1)]
            incoming_by_day = {day.isoformat(): 0 for day in days}
            decided_by_day = {day.isoformat(): 0 for day in days}
            for item in items:
                day_key = item.created_at[:10]
                if day_key in incoming_by_day:
                    incoming_by_day[day_key] += 1
            for event in events:
                day_key = event.created_at[:10]
                if day_key in decided_by_day and event.action in {"approve", "reject", "blacklist"}:
                    decided_by_day[day_key] += 1
            status_labels = (
                ("待处理", "pending"),
                ("已通过", "approved"),
                ("已拒绝", "rejected"),
                ("留置", "held"),
            )
            status_counts = {
                label: sum(item.status == status for item in items)
                for label, status in status_labels
            }
            finalized_count = status_counts["已通过"] + status_counts["已拒绝"]
            incoming_14d = sum(incoming_by_day.values())
            return {
                "exceptions": common_exceptions,
                "metrics": metrics,
                "overview_metrics": (
                    {"label": "审核总量", "value": len(items), "detail": "当前工作区"},
                    {"label": "14 天入队", "value": incoming_14d, "detail": "按创建时间统计"},
                    {
                        "label": "通过率",
                        "value": f"{status_counts['已通过'] * 100 / finalized_count:.1f}%" if finalized_count else "—",
                        "detail": f"{finalized_count} 条已有最终结论",
                    },
                    {"label": "人工待审", "value": len(human), "detail": "AI 二审后仍不确定"},
                ),
                "volume_series": [
                    {
                        "label": f"{day.month}/{day.day}",
                        "incoming": incoming_by_day[day.isoformat()],
                        "decided": decided_by_day[day.isoformat()],
                    }
                    for day in days
                ],
                "decision_distribution": [
                    {"label": label, "value": status_counts[label]}
                    for label, _ in status_labels
                ],
                "pipeline": [
                    {
                        "stage": stage,
                        "count": count,
                        "title": stage,
                        "detail": f"{count} 个待处理",
                        "meta": "live",
                    }
                    for stage, count in sorted(stage_counts.items())
                ],
            }
        if page == "agents":
            rows = []
            for stage in ("fast_scan", "vision_review_1", "vision_review_2", "human_required"):
                stage_attempts = [attempt for attempt in attempts if attempt.stage == stage or (stage == "human_required" and attempt.stage == "human_review")]
                rows.append((stage, stage_counts.get(stage, 0), len(stage_attempts), sum(a.status == "failed" for a in stage_attempts)))
            return {
                "exceptions": common_exceptions,
                "metrics": metrics,
                "agents": {"columns": ("阶段", "当前项目", "attempt", "失败"), "rows": rows},
            }
        if page == "policies":
            config = review_router.config
            policy_version = getattr(service, "policy_version", "policy-default")
            policy_rows = review_store.connection.execute(
                "SELECT policy_version, profile, created_at FROM policy_versions ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            current_policy_row = next(
                (row for row in policy_rows if row["policy_version"] == policy_version),
                None,
            )
            return {
                "exceptions": common_exceptions,
                "policy_version": policy_version,
                "effective_at": current_policy_row["created_at"] if current_policy_row else "未写入版本账本",
                "thresholds": (
                    {"label": "fast scan 放行风险阈值", "value": config.allow_threshold, "detail": "低于该值自动放行"},
                    {"label": "fast scan 拒绝风险阈值", "value": config.reject_threshold, "detail": "高于该值进入拒绝路径"},
                    {"label": "AI 一审最低置信度", "value": config.vision_review_1_min_confidence, "detail": "不足时升级二审"},
                    {"label": "AI 二审最低置信度", "value": config.vision_review_2_min_confidence, "detail": "不足时交人工复核"},
                    {"label": "单阶段最大 attempt", "value": config.max_attempts_per_stage, "detail": "超过后停止自动重试"},
                ),
                "routes": (
                    {"stage": "fast_scan", "condition": "边界或低置信度", "target": "vision_review_1"},
                    {"stage": "vision_review_1", "condition": "低置信度或模型分歧", "target": "vision_review_2"},
                    {"stage": "vision_review_2", "condition": "低置信度或模型分歧", "target": "human_required"},
                ),
                "versions": [
                    {
                        "date": row["created_at"],
                        "version": row["policy_version"],
                        "detail": f"profile={row['profile']}",
                    }
                    for row in policy_rows
                ],
            }
        if page == "quality":
            _quality_vocabulary(consumer_id)
            report = quality_store.report(consumer_id=consumer_id)
            batches = quality_store.list_review_batches(consumer_id=consumer_id)
            selected_batch = next(
                (batch for batch in batches if batch.batch_id == quality_batch_id),
                batches[0] if batches and not quality_batch_id else None,
            )
            if quality_batch_id and selected_batch is None:
                raise HTTPException(status_code=404, detail="quality review batch not found")
            batch_report = (
                quality_store.review_batch_report(
                    consumer_id=consumer_id, batch_id=selected_batch.batch_id
                )
                if selected_batch else None
            )
            page_size = 24
            source_samples = int(report.get("sample_count", 0))
            total_samples = (
                selected_batch.selected_count if selected_batch else source_samples
            )
            safe_offset = min(max(quality_offset, 0), max(total_samples - 1, 0))
            safe_offset = safe_offset // page_size * page_size
            samples = (
                quality_store.list_batch_samples(
                    consumer_id=consumer_id,
                    batch_id=selected_batch.batch_id,
                    limit=page_size,
                    offset=safe_offset,
                )
                if selected_batch else quality_store.list_samples(
                    consumer_id=consumer_id, limit=page_size, offset=safe_offset
                )
            )
            sample_rows = []
            for sample in samples:
                decisions = quality_store.list_decisions(
                    sample_id=sample.sample_id,
                    consumer_id=consumer_id,
                )
                reviewer_ids = {decision.reviewer_id for decision in decisions}
                action_url = None
                if sample.status == "awaiting_reviews" and reviewer_id not in reviewer_ids:
                    action_url = f"/review/quality/samples/{sample.sample_id}/decision"
                elif sample.arbitration_required and reviewer_id not in reviewer_ids:
                    action_url = f"/review/quality/samples/{sample.sample_id}/arbitrate"
                sample_rows.append(
                    {
                        "id": sample.sample_id[:12],
                        "item_id": sample.item_id,
                        "model": sample.reason,
                        "review": " / ".join(
                            f"{decision.reviewer_id}:{decision.decision}"
                            for decision in decisions
                        ) or "待双人复核",
                        "disagreement": "是" if sample.arbitration_required else "否",
                        "verdict": sample.final_decision or sample.status,
                        "tone": "warning" if sample.arbitration_required else "quiet",
                        "media_url": f"/review/quality/samples/{sample.sample_id}/media",
                        "thumbnail_url": (
                            f"/review/quality/samples/{sample.sample_id}/thumbnail"
                            if sample.media_ref.startswith(
                                f"media://corpus/{consumer_id}/"
                            )
                            else None
                        ),
                        "offset": safe_offset,
                        "batch_id": selected_batch.batch_id if selected_batch else None,
                        "action_url": action_url,
                        "csrf_token": csrf_token,
                    }
                )
            return {
                "exceptions": common_exceptions,
                "metrics": [
                    {"label": "冻结批次", "value": total_samples, "detail": f"源样本 {source_samples}"},
                    {"label": "待双审", "value": batch_report.get("untouched", 0) if batch_report else report.get("samples_by_status", {}).get("awaiting_reviews", 0), "detail": "需要两个独立 reviewer"},
                    {"label": "待仲裁", "value": batch_report.get("arbitration_required", 0) if batch_report else report.get("samples_by_status", {}).get("arbitration_required", 0), "detail": "双审结论不一致"},
                ],
                "sampling": {
                    "coverage": f"{total_samples} / {source_samples} 样本" if selected_batch else f"{total_samples} 样本",
                    "false_positive": "待标注" if total_samples else "SKIP",
                    "disagreement": batch_report.get("arbitration_required", 0) if batch_report else report.get("samples_by_status", {}).get("arbitration_required", 0),
                },
                "review_batch": asdict(selected_batch) if selected_batch else None,
                "review_batch_report": batch_report,
                "samples": sample_rows,
                "labels": CONTROLLED_QUALITY_LABELS,
                "retention": {
                    "duration": "由接入方策略定义",
                    "deidentified": True,
                    "dataset": consumer_id,
                },
                "pagination": {
                    "offset": safe_offset,
                    "page_size": page_size,
                    "total": total_samples,
                    "previous_url": (
                        "/review/quality?" + urlencode({
                            "batch": selected_batch.batch_id if selected_batch else "",
                            "offset": max(0, safe_offset - page_size),
                        })
                        if safe_offset > 0 else None
                    ),
                    "next_url": (
                        "/review/quality?" + urlencode({
                            "batch": selected_batch.batch_id if selected_batch else "",
                            "offset": safe_offset + page_size,
                        })
                        if safe_offset + page_size < total_samples else None
                    ),
                },
            }
        if page == "history":
            return {
                "exceptions": common_exceptions,
                "events": {"columns": ("时间", "对象", "actor", "动作", "阶段", "原因"), "rows": [
                    (event.created_at, event.item_id, event.actor_id or event.reviewer, event.action, event.after_stage or "—", event.reason_code or event.note or "—") for event in events
                ]},
            }
        if page == "health":
            return {
                "exceptions": common_exceptions,
                "metrics": metrics,
                "services": {"columns": ("组件", "状态", "说明"), "rows": (
                    ("media model", "ready" if app.state.ready else "blocked", app.state.ready_error or "warmup complete"),
                    ("review database", "ready", "schema v5 + workspace/quality tables"),
                    ("review router", "ready", "vendor-neutral deterministic routing"),
                )},
            }
        if page == "account":
            return {
                "exceptions": common_exceptions,
                "profile": {"Reviewer": reviewer_id or settings.reviewer_id, "Consumer": consumer_id, "角色": "reviewer"},
                "sessions": {"columns": ("会话", "有效期", "权限范围"), "rows": (("当前浏览器", "1 小时", consumer_id),)},
            }
        return {
            "exceptions": common_exceptions,
            "principles": [
                {"title": "证据优先", "detail": "模型结论不能替代受控图片证据", "meta": "required"},
                {"title": "最少人工", "detail": "只处理模型分歧、低置信度、抽检与申诉", "meta": "AI-first"},
                {"title": "追加审计", "detail": "重试生成新 attempt，不覆盖历史", "meta": "append-only"},
            ],
            "categories": {"columns": ("类别", "处置"), "rows": (("sexual_content", "按策略分级"), ("政治人物", "默认交 AI/人工复核"))},
            "shortcuts": {"columns": ("按键", "动作"), "rows": (("J / K", "下一条 / 上一条"), ("A / R / H", "通过 / 拒绝 / 留置"))},
            "reasons": [],
        }

    def _render_support_page(page: str, request: Request) -> HTMLResponse | RedirectResponse:
        try:
            reviewer, csrf_token = require_reviewer(request)
        except HTTPException as exc:
            if exc.status_code == 401 and "text/html" in request.headers.get("Accept", ""):
                return RedirectResponse("/review/login?expired=1", status_code=303)
            raise
        workspace = _review_workspace(request)
        try:
            quality_offset = int(request.query_params.get("offset", "0"))
        except ValueError:
            quality_offset = 0
        quality_batch_id = request.query_params.get("batch") or None
        return HTMLResponse(
            render_review_page(
                page,
                _support_page_data(
                    page,
                    workspace.workspace_id,
                    reviewer,
                    csrf_token,
                    quality_offset=quality_offset,
                    quality_batch_id=quality_batch_id,
                ),
                context=ReviewPageContext(
                    consumer_id=workspace.workspace_id,
                    reviewer_id=reviewer,
                    csrf_token=csrf_token,
                    service_ready=bool(app.state.ready),
                    service_error=app.state.ready_error,
                    workspaces=tuple(
                        (candidate.workspace_id, candidate.name)
                        for candidate in workspace_store.list_for_consumer(settings.consumer_id)
                        if candidate.enabled
                    ),
                ),
            )
        )

    @app.get("/review/overview", response_class=HTMLResponse, response_model=None)
    async def review_overview_page(request: Request):
        return _render_support_page("overview", request)

    @app.get("/review/agents", response_class=HTMLResponse, response_model=None)
    async def review_agents_page(request: Request):
        return _render_support_page("agents", request)

    @app.get("/review/policies", response_class=HTMLResponse, response_model=None)
    async def review_policies_page(request: Request):
        return _render_support_page("policies", request)

    @app.get("/review/quality", response_class=HTMLResponse, response_model=None)
    async def review_quality_page(request: Request):
        return _render_support_page("quality", request)

    @app.get("/review/quality/samples")
    async def list_quality_samples(
        request: Request,
        status: str | None = None,
        batch: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        require_reviewer(request)
        workspace = _review_workspace(request)
        _quality_vocabulary(workspace.workspace_id)
        try:
            if batch:
                if status is not None:
                    raise ValueError("status cannot be combined with a frozen batch")
                samples = quality_store.list_batch_samples(
                    consumer_id=workspace.workspace_id, batch_id=batch,
                    limit=limit, offset=offset,
                )
                batch_report = quality_store.review_batch_report(
                    consumer_id=workspace.workspace_id, batch_id=batch
                )
            else:
                samples = quality_store.list_samples(
                    consumer_id=workspace.workspace_id,
                    status=status,  # type: ignore[arg-type]
                    limit=limit,
                    offset=offset,
                )
                batch_report = None
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "report": quality_store.report(consumer_id=workspace.workspace_id),
            "batch_report": batch_report,
            "samples": [asdict(sample) for sample in samples],
            "pagination": {"limit": limit, "offset": offset, "returned": len(samples)},
        }

    @app.post("/review/items/{item_id}/quality-label")
    async def label_review_item(item_id: str, request: Request) -> JSONResponse:
        reviewer, session_csrf = require_reviewer(request)
        workspace = _review_workspace(request)
        payload = await read_review_payload(request)
        require_csrf(request, payload.get("csrf_token"), session_csrf)
        try:
            review_store.get(item_id, consumer_id=workspace.workspace_id)
            _quality_vocabulary(workspace.workspace_id)
            event = quality_store.append_item_label(
                consumer_id=workspace.workspace_id,
                item_id=item_id,
                label=str(payload.get("label") or ""),
                actor_id=reviewer,
                vocabulary_version="v1",
                request_id=request.headers.get("X-Request-ID"),
                note=str(payload.get("note") or "") or None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (QualityConflictError, ValueError) as exc:
            raise HTTPException(
                status_code=409 if isinstance(exc, QualityConflictError) else 400,
                detail=str(exc),
            ) from exc
        return JSONResponse(asdict(event), status_code=201)

    @app.post("/review/items/{item_id}/quality-sample")
    async def sample_review_item(item_id: str, request: Request) -> JSONResponse:
        reviewer, session_csrf = require_reviewer(request)
        workspace = _review_workspace(request)
        payload = await read_review_payload(request)
        require_csrf(request, payload.get("csrf_token"), session_csrf)
        try:
            review_store.get(item_id, consumer_id=workspace.workspace_id)
            _quality_vocabulary(workspace.workspace_id)
            sample = quality_store.create_sample(
                consumer_id=workspace.workspace_id,
                item_id=item_id,
                reason=str(payload.get("reason") or "quality_sample"),
                vocabulary_version="v1",
                stratum=str(payload.get("stratum") or "") or None,
                actor_id=reviewer,
                request_id=request.headers.get("X-Request-ID"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (QualityConflictError, ValueError) as exc:
            raise HTTPException(
                status_code=409 if isinstance(exc, QualityConflictError) else 400,
                detail=str(exc),
            ) from exc
        return JSONResponse(asdict(sample), status_code=201)

    @app.post("/review/quality/samples/{sample_id}/decision", response_model=None)
    async def decide_quality_sample(
        sample_id: str, request: Request
    ) -> JSONResponse | RedirectResponse:
        reviewer, session_csrf = require_reviewer(request)
        workspace = _review_workspace(request)
        payload = await read_review_payload(request)
        require_csrf(request, payload.get("csrf_token"), session_csrf)
        try:
            sample = quality_store.submit_decision(
                sample_id=sample_id,
                consumer_id=workspace.workspace_id,
                reviewer_id=reviewer,
                decision=str(payload.get("decision") or ""),  # type: ignore[arg-type]
                request_id=request.headers.get("X-Request-ID"),
                note=str(payload.get("note") or "") or None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (QualityConflictError, ValueError) as exc:
            raise HTTPException(
                status_code=409 if isinstance(exc, QualityConflictError) else 400,
                detail=str(exc),
            ) from exc
        if "text/html" in request.headers.get("Accept", ""):
            raw_offset = payload.get("offset")
            try:
                offset = int(raw_offset) if raw_offset not in (None, "") else 0
            except (TypeError, ValueError):
                offset = 0
            parameters = {"offset": offset}
            if payload.get("batch"):
                parameters["batch"] = str(payload["batch"])
            return RedirectResponse(
                "/review/quality?" + urlencode(parameters)
                if 0 <= offset <= 10_000_000 else "/review/quality",
                status_code=303,
            )
        return JSONResponse(asdict(sample))

    @app.post("/review/quality/samples/{sample_id}/arbitrate", response_model=None)
    async def arbitrate_quality_sample(
        sample_id: str, request: Request
    ) -> JSONResponse | RedirectResponse:
        reviewer, session_csrf = require_reviewer(request)
        workspace = _review_workspace(request)
        payload = await read_review_payload(request)
        require_csrf(request, payload.get("csrf_token"), session_csrf)
        try:
            sample = quality_store.arbitrate(
                sample_id=sample_id,
                consumer_id=workspace.workspace_id,
                arbitrator_id=reviewer,
                decision=str(payload.get("decision") or ""),  # type: ignore[arg-type]
                request_id=request.headers.get("X-Request-ID"),
                note=str(payload.get("note") or "") or None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (QualityConflictError, ValueError) as exc:
            raise HTTPException(
                status_code=409 if isinstance(exc, QualityConflictError) else 400,
                detail=str(exc),
            ) from exc
        if "text/html" in request.headers.get("Accept", ""):
            raw_offset = payload.get("offset")
            try:
                offset = int(raw_offset) if raw_offset not in (None, "") else 0
            except (TypeError, ValueError):
                offset = 0
            parameters = {"offset": offset}
            if payload.get("batch"):
                parameters["batch"] = str(payload["batch"])
            return RedirectResponse(
                "/review/quality?" + urlencode(parameters)
                if 0 <= offset <= 10_000_000 else "/review/quality",
                status_code=303,
            )
        return JSONResponse(asdict(sample))

    @app.get("/review/history", response_class=HTMLResponse, response_model=None)
    async def review_history_page(request: Request):
        return _render_support_page("history", request)

    @app.get("/review/health", response_class=HTMLResponse, response_model=None)
    async def review_health_page(request: Request):
        return _render_support_page("health", request)

    @app.get("/review/account", response_class=HTMLResponse, response_model=None)
    async def review_account_page(request: Request):
        return _render_support_page("account", request)

    @app.get("/review/guide", response_class=HTMLResponse, response_model=None)
    async def review_guide_page(request: Request):
        return _render_support_page("guide", request)

    @app.get("/review/items")
    async def list_review_items(
        request: Request,
        status: str = "pending",
        limit: int = 100,
        decision_hint: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, object]:
        require_reviewer(request)
        workspace = _review_workspace(request)
        if status == "all":
            status_filter = None
        elif status in {"pending", "approved", "rejected", "held"}:
            status_filter = status
        else:
            raise HTTPException(status_code=400, detail="invalid review status")
        try:
            items, next_cursor = review_store.list_items_page(
                status=status_filter,
                consumer_id=workspace.workspace_id,
                limit=limit,
                decision_hint=decision_hint,
                cursor=cursor,
                human_only=status_filter == "pending",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "items": [item.to_dict() for item in items],
            "count": len(items),
            "next_cursor": next_cursor,
        }

    @app.get("/review/items/{item_id}")
    async def get_review_item(item_id: str, request: Request) -> dict[str, object]:
        require_reviewer(request)
        workspace = _review_workspace(request)
        try:
            item = review_store.get(item_id, consumer_id=workspace.workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review item not found") from exc
        return {
            "item": item.to_dict(),
            "events": [
                event.to_dict()
                for event in review_store.list_events(item_id, workspace.workspace_id)
            ],
            "attempts": [
                attempt.to_dict()
                for attempt in attempt_store.list_attempts(
                    item_id, consumer_id=workspace.workspace_id
                )
            ],
        }

    @app.get("/review/items/{item_id}/attempts")
    async def get_review_attempts(item_id: str, request: Request) -> dict[str, object]:
        require_reviewer(request)
        workspace = _review_workspace(request)
        try:
            review_store.get(item_id, consumer_id=workspace.workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review item not found") from exc
        attempts = attempt_store.list_attempts(
            item_id, consumer_id=workspace.workspace_id
        )
        return {"attempts": [attempt.to_dict() for attempt in attempts], "count": len(attempts)}

    @app.post("/v1/review/items/{item_id}/attempts")
    async def record_review_attempt(item_id: str, request: Request) -> JSONResponse:
        require_api_access(request)
        try:
            item = review_store.get(item_id, consumer_id=settings.consumer_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review item not found") from exc
        body = await read_limited_body(request)
        if len(body) > 128 * 1024:
            raise HTTPException(status_code=413, detail="attempt payload too large")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid attempt JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="attempt payload must be an object")
        try:
            attempt = attempt_store.append_attempt(
                item_id=item.item_id,
                consumer_id=settings.consumer_id,
                stage=payload.get("stage"),
                attempt_number=payload.get("attempt_number"),
                actor_type="agent",
                provider=payload.get("provider"),
                model_id=payload.get("model_id"),
                model_version=payload.get("model_version"),
                prompt_version=payload.get("prompt_version"),
                decision=payload.get("decision"),
                confidence=payload.get("confidence"),
                reasons=payload.get("reasons") or (),
                findings=payload.get("findings") or (),
                evidence=payload.get("evidence") or (),
                status=payload.get("status", "succeeded"),
                parent_attempt_id=payload.get("parent_attempt_id"),
                started_at=payload.get("started_at"),
                completed_at=payload.get("completed_at"),
                elapsed_ms=payload.get("elapsed_ms"),
                error=payload.get("error"),
            )
            route = _route_item(item.item_id)
        except (AttemptConflictError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=409 if isinstance(exc, AttemptConflictError) else 400, detail=str(exc)) from exc
        return JSONResponse(
            {"attempt": attempt.to_dict(), "route": route.__dict__, "item": review_store.get(item_id).to_dict()},
            status_code=201,
        )

    def _read_safe_media(media_ref: str) -> bytes:
        if not media_ref.startswith("media://"):
            raise HTTPException(status_code=404, detail="media preview is unavailable")
        relative = media_ref.removeprefix("media://")
        if not relative or relative.startswith("/"):
            raise HTTPException(status_code=404, detail="media preview is unavailable")
        root = settings.media_root.expanduser().resolve()
        parts = Path(relative).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise HTTPException(status_code=404, detail="media preview is unavailable")
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptors: list[int] = []
        try:
            current = os.open(root, directory_flags)
            descriptors.append(current)
            for part in parts[:-1]:
                current = os.open(part, directory_flags, dir_fd=current)
                descriptors.append(current)
            descriptor = os.open(parts[-1], file_flags, dir_fd=current)
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise HTTPException(status_code=404, detail="media preview is unavailable")
            if metadata.st_size > settings.max_body_bytes:
                raise HTTPException(status_code=413, detail="media preview exceeds configured limit")
            with os.fdopen(os.dup(descriptor), "rb") as handle:
                payload = handle.read(settings.max_body_bytes + 1)
            if len(payload) > settings.max_body_bytes:
                raise HTTPException(status_code=413, detail="media preview exceeds configured limit")
            return payload
        except OSError as exc:
            raise HTTPException(status_code=404, detail="media preview is unavailable") from exc
        finally:
            for descriptor in reversed(descriptors):
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _safe_media_response(media_ref: str) -> Response:
        image_bytes = _read_safe_media(media_ref)
        try:
            decode_image(
                image_bytes,
                ImageLimits(
                    max_bytes=settings.max_body_bytes,
                    max_width=settings.max_image_width,
                    max_height=settings.max_image_height,
                    max_pixels=settings.max_image_pixels,
                    max_frames=settings.max_image_frames,
                ),
            )
            from PIL import Image
            from io import BytesIO

            with Image.open(BytesIO(image_bytes)) as image:
                format_name = image.format
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=415, detail="media preview is not a supported safe image"
            ) from exc
        mime = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
            "GIF": "image/gif",
            "BMP": "image/bmp",
        }.get(format_name)
        if mime is None:
            raise HTTPException(status_code=415, detail="media preview format is not allowed")
        return Response(
            content=image_bytes,
            media_type=mime,
            headers={"Cache-Control": "private, no-store", "Content-Disposition": "inline"},
        )

    @app.post("/v1/review/items/{item_id}/advanced-vision")
    async def run_advanced_vision(item_id: str, request: Request) -> JSONResponse:
        """Run the configured advanced provider for the router-selected vision stage."""
        require_api_access(request)
        try:
            item = review_store.get(item_id, consumer_id=settings.consumer_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review item not found") from exc

        attempts = attempt_store.list_attempts(item_id, consumer_id=settings.consumer_id)
        categories = tuple(
            sorted(
                {
                    str(finding.get("category"))
                    for attempt in attempts
                    for finding in attempt.findings
                    if finding.get("category")
                }
            )
        )
        route = review_router.route(attempts, risk_score=item.top_score, categories=categories)
        stage = route.next_stage
        if stage not in {"vision_review_1", "vision_review_2"}:
            raise HTTPException(status_code=409, detail=f"advanced vision is not required for stage {route.state}")
        if not advanced_vision_provider.enabled:
            raise HTTPException(status_code=503, detail="advanced vision provider is disabled")

        try:
            image_bytes = _read_safe_media(item.media_ref)
            decode_image(
                image_bytes,
                ImageLimits(
                    max_bytes=settings.max_body_bytes,
                    max_width=settings.max_image_width,
                    max_height=settings.max_image_height,
                    max_pixels=settings.max_image_pixels,
                    max_frames=settings.max_image_frames,
                ),
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=415, detail="media is not a supported safe image") from exc

        attempt_number = attempt_store.next_attempt_number(
            item_id, stage, consumer_id=settings.consumer_id
        )
        request_id = request.headers.get("X-Request-ID") or item.request_id or f"{item_id}:{stage}:{attempt_number}"
        started = time.perf_counter()
        try:
            conclusion = await asyncio.to_thread(
                advanced_vision_provider.review,
                VisionReviewRequest(
                    image_bytes=image_bytes,
                    media_type="image/jpeg",
                    request_id=request_id,
                    categories=categories,
                    context=f"consumer={item.consumer_id}; policy={item.policy_version}",
                ),
            )
        except VisionProviderError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            attempt = attempt_store.append_attempt(
                item_id=item_id,
                consumer_id=settings.consumer_id,
                stage=stage,
                attempt_number=attempt_number,
                actor_type="agent",
                provider=advanced_vision_provider.provider_name,
                model_id=advanced_vision_provider.model_id or None,
                model_version=None,
                prompt_version=None,
                decision="error",
                confidence=None,
                reasons=(exc.kind.value,),
                status="failed",
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )
            next_route = _route_item(item_id, risk_score=item.top_score)
            status_code = 503 if exc.kind.value in {"disabled", "configuration", "authentication"} else 502
            return JSONResponse(
                {"attempt": attempt.to_dict(), "route": next_route.__dict__, "error": exc.to_dict()},
                status_code=status_code,
            )

        elapsed_ms = (time.perf_counter() - started) * 1000
        payload = conclusion.to_attempt_payload(stage=stage, attempt_number=attempt_number)
        attempt = attempt_store.append_attempt(
            item_id=item_id,
            consumer_id=settings.consumer_id,
            actor_type="agent",
            elapsed_ms=elapsed_ms,
            **payload,
        )
        next_route = _route_item(item_id, risk_score=item.top_score)
        return JSONResponse(
            {"attempt": attempt.to_dict(), "route": next_route.__dict__, "item": review_store.get(item_id).to_dict()},
            status_code=201,
        )

    @app.get("/review/items/{item_id}/media")
    async def review_media(item_id: str, request: Request) -> Response:
        require_reviewer(request)
        workspace = _review_workspace(request)
        try:
            item = review_store.get(item_id, consumer_id=workspace.workspace_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review item not found") from exc
        return _safe_media_response(item.media_ref)

    @app.get("/review/quality/samples/{sample_id}/media")
    async def quality_sample_media(sample_id: str, request: Request) -> Response:
        require_reviewer(request)
        workspace = _review_workspace(request)
        try:
            sample = quality_store.get_sample(
                sample_id=sample_id,
                consumer_id=workspace.workspace_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="quality sample not found") from exc
        return _safe_media_response(sample.media_ref)

    @app.get("/review/quality/samples/{sample_id}/thumbnail")
    async def quality_sample_thumbnail(sample_id: str, request: Request) -> Response:
        require_reviewer(request)
        workspace = _review_workspace(request)
        try:
            sample = quality_store.get_sample(
                sample_id=sample_id,
                consumer_id=workspace.workspace_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="quality sample not found") from exc
        prefix = f"media://corpus/{workspace.workspace_id}/"
        if not sample.media_ref.startswith(prefix):
            raise HTTPException(status_code=404, detail="quality thumbnail is unavailable")
        name = Path(sample.media_ref.removeprefix(prefix)).name
        digest = name.split(".", 1)[0]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise HTTPException(status_code=404, detail="quality thumbnail is unavailable")
        return _safe_media_response(f"{prefix}thumbs/{digest}.jpg")

    async def _review_action(request: Request, item_id: str, action: str) -> JSONResponse | RedirectResponse:
        reviewer, session_csrf = require_reviewer(request)
        workspace = _review_workspace(request)
        payload = await read_review_payload(request)
        require_csrf(request, payload.get("csrf_token"), session_csrf)
        raw_version = payload.get("version")
        try:
            expected_version = int(raw_version) if raw_version not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="version must be an integer") from exc
        note = payload.get("note", "")
        if not isinstance(note, str):
            raise HTTPException(status_code=400, detail="note must be a string")
        return_to = None
        if "text/html" in request.headers.get("Accept", ""):
            return_to = _planned_review_return(
                item_id, payload.get("return_to"), workspace.workspace_id
            )
        try:
            item = review_store.decide(
                item_id,
                action,  # type: ignore[arg-type]
                reviewer,
                note,
                consumer_id=workspace.workspace_id,
                expected_version=expected_version,
                request_id=request.headers.get("X-Request-ID"),
                ip_hash=_ip_hash(request),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review item not found") from exc
        except ReviewConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if action == "retry":
            try:
                if job_store.count_active(workspace.workspace_id) >= settings.max_queue_depth:
                    raise RuntimeError("vision review queue is full")
                _enqueue_manual_vision_retry(item, workspace.workspace_id)
            except Exception as exc:
                item = review_store.apply_route(
                    item_id,
                    stage="model_error",
                    final_decision=None,
                    reason_code="manual_retry_enqueue_failed",
                    consumer_id=workspace.workspace_id,
                )
                if "text/html" not in request.headers.get("Accept", ""):
                    return JSONResponse(
                        {"item": item.to_dict(), "error": f"{type(exc).__name__}: {exc}"},
                        status_code=503,
                    )
        if "text/html" in request.headers.get("Accept", ""):
            return RedirectResponse(return_to or "/review", status_code=303)
        return JSONResponse(item.to_dict())

    @app.post("/review/items/{item_id}/approve", response_model=None)
    async def approve_review_item(item_id: str, request: Request) -> JSONResponse | RedirectResponse:
        return await _review_action(request, item_id, "approve")

    @app.post("/review/items/{item_id}/reject", response_model=None)
    async def reject_review_item(item_id: str, request: Request) -> JSONResponse | RedirectResponse:
        return await _review_action(request, item_id, "reject")

    @app.post("/review/items/{item_id}/blacklist", response_model=None)
    async def blacklist_review_item(item_id: str, request: Request) -> JSONResponse | RedirectResponse:
        return await _review_action(request, item_id, "blacklist")

    @app.post("/review/items/{item_id}/hold", response_model=None)
    async def hold_review_item(item_id: str, request: Request) -> JSONResponse | RedirectResponse:
        return await _review_action(request, item_id, "hold")

    @app.post("/review/items/{item_id}/retry", response_model=None)
    async def retry_review_item(item_id: str, request: Request) -> JSONResponse | RedirectResponse:
        return await _review_action(request, item_id, "retry")

    @app.post("/review/batch", response_model=None)
    async def batch_review_items(request: Request) -> JSONResponse | RedirectResponse:
        reviewer, session_csrf = require_reviewer(request)
        workspace = _review_workspace(request)
        body = await request.body()
        if len(body) > 64 * 1024:
            raise HTTPException(status_code=413, detail="review payload too large")
        try:
            values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid review form") from exc
        require_csrf(request, (values.get("csrf_token") or [None])[-1], session_csrf)
        action = (values.get("action") or [""])[-1]
        if action not in {"approve", "reject", "blacklist", "hold"}:
            raise HTTPException(status_code=400, detail="unknown batch review action")
        selected = values.get("selected", [])
        if not selected:
            raise HTTPException(status_code=400, detail="select at least one review item")
        if len(selected) > 50:
            raise HTTPException(status_code=400, detail="batch review is limited to 50 items")

        processed: list[str] = []
        failures: list[dict[str, str]] = []
        for entry in selected:
            try:
                item_id, raw_version = entry.rsplit(":", 1)
                expected_version = int(raw_version)
                item = review_store.get(item_id, consumer_id=workspace.workspace_id)
                attempts = attempt_store.list_attempts(
                    item_id, consumer_id=workspace.workspace_id
                )
                blocker = _batch_blocker(item, attempts)
                if blocker is not None:
                    raise ValueError(blocker)
                review_store.decide(
                    item_id,
                    action,  # type: ignore[arg-type]
                    reviewer,
                    "batch review",
                    consumer_id=workspace.workspace_id,
                    expected_version=expected_version,
                    request_id=request.headers.get("X-Request-ID"),
                    ip_hash=_ip_hash(request),
                )
                processed.append(item_id)
            except (KeyError, ReviewConflictError, ValueError) as exc:
                failures.append({"item": entry.split(":", 1)[0], "error": str(exc)})

        if "text/html" in request.headers.get("Accept", ""):
            return_to = _sanitize_review_return_to(
                (values.get("return_to") or ["/review?batch=1"])[-1],
                fallback="/review?batch=1",
            )
            separator = "&" if "?" in return_to else "?"
            summary = f"批量处理完成：成功 {len(processed)} 项，失败 {len(failures)} 项"
            return RedirectResponse(
                f"{return_to}{separator}{urlencode({'batch_result': summary})}",
                status_code=303,
            )
        return JSONResponse({"action": action, "processed": processed, "failures": failures})

    return app
