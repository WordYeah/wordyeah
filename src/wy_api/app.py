import base64
import hashlib
import hmac
import html
import json
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from wy_core.config import load_policy_config
from wy_core.contracts import ModerationResult
from wy_core.result_store import ResultStore
from wy_jobs.store import JobStore
from wy_media.falconsai import FalconsaiClassifier
from wy_media.image_safety import ImageLimits, decode_image
from wy_media.service import MediaModerationService
from wy_review.store import ReviewConflictError, ReviewStore
from wy_review.attempt_store import AttemptConflictError, ReviewAttemptStore
from wy_review.router import ReviewRouter
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

    app = FastAPI(title="WordYeah Avatar Moderation API", version=APP_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service
    app.state.review_store = review_store
    app.state.attempt_store = attempt_store
    app.state.review_router = review_router
    app.state.job_store = job_store
    app.state.result_store = result_store
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

    if settings.reviewer_token is not None:
        review_secret = hmac.new(
            (settings.review_session_secret or "wordyeah-review-session").encode("utf-8"),
            settings.reviewer_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    else:
        review_secret = None
    failed_logins: dict[str, list[float]] = {}
    session_ttl_seconds = 3600

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

    def _issue_review_session() -> tuple[str, str]:
        if review_secret is None:
            raise HTTPException(status_code=503, detail="reviewer authentication is not configured")
        csrf_token = base64.urlsafe_b64encode(os.urandom(18)).decode("ascii").rstrip("=")
        expires = int(time.time()) + session_ttl_seconds
        payload = f"{settings.reviewer_id}\x00{expires}\x00{csrf_token}".encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        signature = hmac.new(review_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}", csrf_token

    def _read_review_session(request: Request) -> tuple[str, str]:
        if settings.reviewer_token is None or review_secret is None:
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
            if reviewer != settings.reviewer_id or int(expires_text) < int(time.time()) or not csrf_token:
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

    def _consumer_items(limit: int = 1000) -> list[Any]:
        return review_store.list_items(status=None, consumer_id=settings.consumer_id, limit=limit)

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

    def _planned_review_return(item_id: str, raw_return_to: object) -> str:
        target = _sanitize_review_return_to(raw_return_to)
        parsed = urlsplit(target)
        values = parse_qs(parsed.query, keep_blank_values=True)
        view_mode = (values.get("view") or ["list"])[-1]
        focus_item_id = (values.get("focus") or [None])[-1]
        if view_mode != "focus" or focus_item_id != item_id:
            return target
        filtered_items = _filter_items(
            _consumer_items(),
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
        attempts = attempt_store.list_attempts(item_id)
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
        return route

    def _record_fast_scan(item_id: str, result: ModerationResult) -> None:
        if attempt_store.list_attempts(item_id, "fast_scan"):
            return
        attempt_store.append_attempt(
            item_id=item_id,
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

    @app.get("/health/live")
    async def health_live() -> dict[str, object]:
        return {"status": "ok", "external_model_calls": False}

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
        return {"status": "ready", "model_ready": service.ready, "database": "ok"}

    @app.get("/version")
    async def version() -> dict[str, object]:
        return {"version": APP_VERSION, "schema_version": 3, "policy_profile": settings.policy_profile}

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
        if settings.reviewer_token is None:
            raise HTTPException(status_code=503, detail="reviewer authentication is not configured")
        try:
            require_reviewer(request)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
        else:
            return RedirectResponse("/review", status_code=303)
        return HTMLResponse(render_login_page(expired=request.query_params.get("expired") == "1"))

    @app.post("/review/login", response_model=None)
    async def review_login(request: Request) -> JSONResponse | RedirectResponse:
        if settings.reviewer_token is None or review_secret is None:
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
            else:
                values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
                token = values.get("token", [None])[-1]
        except (UnicodeDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid login payload") from exc
        if not isinstance(token, str) or not hmac.compare_digest(token, settings.reviewer_token):
            recent.append(now)
            failed_logins[ip] = recent
            raise HTTPException(status_code=401, detail="invalid reviewer token")
        failed_logins.pop(ip, None)
        cookie, csrf_token = _issue_review_session()
        if "text/html" in request.headers.get("Accept", ""):
            response: JSONResponse | RedirectResponse = RedirectResponse("/review", status_code=303)
        else:
            response = JSONResponse({"status": "ok", "reviewer": settings.reviewer_id, "csrf_token": csrf_token})
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
        if "text/html" in request.headers.get("Accept", ""):
            response: JSONResponse | RedirectResponse = RedirectResponse("/review/login", status_code=303)
        else:
            response = JSONResponse({"status": "ok"})
        response.delete_cookie("wordyeah_review_session", path="/review")
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
        items = _consumer_items()
        events = review_store.list_all_events(settings.consumer_id, limit=1000)
        return HTMLResponse(
            render_review_workbench(
                items=items,
                events=events,
                csrf_token=csrf_token,
                consumer_id=settings.consumer_id,
                reviewer_id=reviewer,
                policy_profile=settings.policy_profile,
                service_ready=bool(app.state.ready),
                service_error=app.state.ready_error,
                focus_item_id=focus_item_id,
                metrics=review_store.metrics(settings.consumer_id),
                search_query=search_query,
                status_filter=status_filter,
                risk_filter=risk_filter,
                view_mode=view_mode,
                batch_mode=batch_mode,
                batch_result=batch_result,
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

    def _support_page_data(page: str) -> dict[str, object]:
        items = _consumer_items()
        consumer_item_ids = {item.item_id for item in items}
        attempts = [
            attempt
            for attempt in attempt_store.list_recent(5000)
            if attempt.item_id in consumer_item_ids
        ][:1000]
        events = review_store.list_all_events(settings.consumer_id, limit=1000)
        pending = [item for item in items if item.status == "pending"]
        held = [item for item in items if item.status == "held"]
        human = [item for item in pending if item.stage == "human_required"]
        stage_counts: dict[str, int] = {}
        for item in items:
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
            return {
                "exceptions": common_exceptions,
                "metrics": metrics,
                "pipeline": [
                    {"title": stage, "detail": f"{count} 条", "meta": "live"}
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
            return {
                "exceptions": common_exceptions,
                "current_policy": {
                    "profile": settings.policy_profile,
                    "fast scan 放行风险阈值": config.allow_threshold,
                    "fast scan 拒绝风险阈值": config.reject_threshold,
                    "AI 一审最低置信度": config.vision_review_1_min_confidence,
                    "AI 二审最低置信度": config.vision_review_2_min_confidence,
                    "单阶段最大 attempt": config.max_attempts_per_stage,
                },
                "routes": {
                    "columns": ("来源", "条件", "去向"),
                    "rows": (
                        ("fast_scan", "边界或低置信度", "vision_review_1"),
                        ("vision_review_1", "低置信度或分歧", "vision_review_2"),
                        ("vision_review_2", "低置信度或分歧", "human_required"),
                    ),
                },
                "versions": [],
            }
        if page == "quality":
            samples = [item for item in items if item.quality_sample]
            return {
                "exceptions": common_exceptions,
                "metrics": [
                    {"label": "抽检样本", "value": len(samples), "detail": "0 样本显示 SKIP"},
                    {"label": "误报率", "value": "SKIP" if not samples else "待标注", "detail": "不得以 0 样本判通过"},
                    {"label": "漏报率", "value": "SKIP" if not samples else "待标注", "detail": "不得以 0 样本判通过"},
                ],
                "cases": {"columns": ("项目", "阶段", "最终决定", "仲裁"), "rows": [
                    (item.item_id, item.stage, item.final_decision or "—", "是" if item.arbitration_required else "否") for item in samples
                ]},
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
                    ("review database", "ready", "schema v3"),
                    ("review router", "ready", "vendor-neutral deterministic routing"),
                )},
            }
        if page == "account":
            return {
                "exceptions": common_exceptions,
                "profile": {"Reviewer": settings.reviewer_id, "Consumer": settings.consumer_id, "角色": "reviewer"},
                "sessions": {"columns": ("会话", "有效期", "权限范围"), "rows": (("当前浏览器", "1 小时", settings.consumer_id),)},
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
        return HTMLResponse(
            render_review_page(
                page,
                _support_page_data(page),
                context=ReviewPageContext(
                    consumer_id=settings.consumer_id,
                    reviewer_id=reviewer,
                    csrf_token=csrf_token,
                    service_ready=bool(app.state.ready),
                    service_error=app.state.ready_error,
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
    ) -> dict[str, object]:
        require_reviewer(request)
        if status == "all":
            status_filter = None
        elif status in {"pending", "approved", "rejected", "held"}:
            status_filter = status
        else:
            raise HTTPException(status_code=400, detail="invalid review status")
        try:
            items = review_store.list_items(
                status=status_filter,
                consumer_id=settings.consumer_id,
                limit=limit,
                decision_hint=decision_hint,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"items": [item.to_dict() for item in items], "count": len(items)}

    @app.get("/review/items/{item_id}")
    async def get_review_item(item_id: str, request: Request) -> dict[str, object]:
        require_reviewer(request)
        try:
            item = review_store.get(item_id, consumer_id=settings.consumer_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review item not found") from exc
        return {
            "item": item.to_dict(),
            "events": [event.to_dict() for event in review_store.list_events(item_id, settings.consumer_id)],
            "attempts": [attempt.to_dict() for attempt in attempt_store.list_attempts(item_id)],
        }

    @app.get("/review/items/{item_id}/attempts")
    async def get_review_attempts(item_id: str, request: Request) -> dict[str, object]:
        require_reviewer(request)
        try:
            review_store.get(item_id, consumer_id=settings.consumer_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review item not found") from exc
        attempts = attempt_store.list_attempts(item_id)
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

    def _safe_media_path(media_ref: str) -> Path:
        if not media_ref.startswith("media://"):
            raise HTTPException(status_code=404, detail="media preview is unavailable")
        relative = media_ref.removeprefix("media://")
        if not relative or relative.startswith("/"):
            raise HTTPException(status_code=404, detail="media preview is unavailable")
        root = settings.media_root.expanduser().resolve()
        path = (root / relative).resolve()
        if root != path and root not in path.parents:
            raise HTTPException(status_code=404, detail="media preview is unavailable")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="media preview is unavailable")
        try:
            if path.stat().st_size > settings.max_body_bytes:
                raise HTTPException(status_code=413, detail="media preview exceeds configured limit")
        except OSError as exc:
            raise HTTPException(status_code=404, detail="media preview is unavailable") from exc
        return path

    @app.get("/review/items/{item_id}/media")
    async def review_media(item_id: str, request: Request) -> FileResponse:
        require_reviewer(request)
        try:
            item = review_store.get(item_id, consumer_id=settings.consumer_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review item not found") from exc
        path = _safe_media_path(item.media_ref)
        try:
            image_bytes = path.read_bytes()
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

            with Image.open(path) as image:
                format_name = image.format
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=415, detail="media preview is not a supported safe image") from exc
        mime = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
            "GIF": "image/gif",
            "BMP": "image/bmp",
        }.get(format_name)
        if mime is None:
            raise HTTPException(status_code=415, detail="media preview format is not allowed")
        return FileResponse(
            path,
            media_type=mime,
            headers={"Cache-Control": "private, no-store", "Content-Disposition": "inline"},
        )

    async def _review_action(request: Request, item_id: str, action: str) -> JSONResponse | RedirectResponse:
        reviewer, session_csrf = require_reviewer(request)
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
            return_to = _planned_review_return(item_id, payload.get("return_to"))
        try:
            item = review_store.decide(
                item_id,
                action,  # type: ignore[arg-type]
                reviewer,
                note,
                consumer_id=settings.consumer_id,
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
                item = review_store.get(item_id, consumer_id=settings.consumer_id)
                attempts = attempt_store.list_attempts(item_id)
                blocker = _batch_blocker(item, attempts)
                if blocker is not None:
                    raise ValueError(blocker)
                review_store.decide(
                    item_id,
                    action,  # type: ignore[arg-type]
                    reviewer,
                    "batch review",
                    consumer_id=settings.consumer_id,
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
