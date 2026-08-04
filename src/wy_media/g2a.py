from __future__ import annotations

import base64
import json
import os
import socket
import ipaddress
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .vision_provider import (
    VisionErrorKind,
    VisionEvidence,
    VisionFinding,
    VisionProviderError,
    VisionReviewConclusion,
    VisionReviewRequest,
    string_sequence,
)


DEFAULT_PROMPT_VERSION = "wordyeah-avatar-review-v1"


@dataclass(frozen=True)
class G2AConfig:
    enabled: bool = False
    endpoint: str = ""
    api_key: str = ""
    model_id: str = ""
    model_version: str | None = None
    timeout_seconds: float = 20.0
    prompt_version: str = DEFAULT_PROMPT_VERSION
    max_image_bytes: int = 10 * 1024 * 1024
    allow_private_http: bool = False

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise ValueError("G2A timeout_seconds must be between 0 and 300")
        if self.max_image_bytes < 1:
            raise ValueError("G2A max_image_bytes must be positive")
        if self.enabled:
            if not self.endpoint or not self.api_key or not self.model_id:
                raise ValueError("enabled G2A requires endpoint, api_key and model_id")
            parsed = urlparse(self.endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("G2A endpoint must be an absolute HTTP(S) URL")
            if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
                try:
                    private_address = ipaddress.ip_address(parsed.hostname or "").is_private
                except ValueError:
                    private_address = False
                if not (self.allow_private_http and private_address):
                    raise ValueError(
                        "enabled G2A requires HTTPS except for loopback or explicitly allowed private IP"
                    )
        if not self.prompt_version:
            raise ValueError("G2A prompt_version is required")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> G2AConfig:
        values = os.environ if env is None else env
        enabled = _parse_bool(values.get("WORDYEAH_G2A_ENABLED", "false"))
        try:
            timeout = float(values.get("WORDYEAH_G2A_TIMEOUT_SECONDS", "20"))
            max_bytes = int(values.get("WORDYEAH_G2A_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
        except ValueError as exc:
            raise ValueError("G2A timeout and image limit must be numeric") from exc
        return cls(
            enabled=enabled,
            endpoint=values.get("WORDYEAH_G2A_ENDPOINT", "").strip(),
            api_key=values.get("WORDYEAH_G2A_API_KEY", "").strip(),
            model_id=values.get("WORDYEAH_G2A_MODEL", "").strip(),
            model_version=values.get("WORDYEAH_G2A_MODEL_VERSION") or None,
            timeout_seconds=timeout,
            prompt_version=values.get("WORDYEAH_G2A_PROMPT_VERSION", DEFAULT_PROMPT_VERSION).strip(),
            max_image_bytes=max_bytes,
            allow_private_http=_parse_bool(
                values.get("WORDYEAH_G2A_ALLOW_PRIVATE_HTTP", "false")
            ),
        )


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] | None = None


Transport = Callable[[Request, float], HttpResponse]


class G2AVisionProvider:
    """Configurable G2A adapter using an OpenAI-compatible chat payload.

    Network access is impossible unless ``G2AConfig.enabled`` is explicitly
    true. A transport can be injected for deterministic tests.
    """

    provider_name = "g2a"

    def __init__(self, config: G2AConfig, transport: Transport | None = None) -> None:
        self.config = config
        self.model_id = config.model_id
        self.enabled = config.enabled
        self._transport = transport or _urlopen_transport

    def review(self, request: VisionReviewRequest) -> VisionReviewConclusion:
        if not self.enabled:
            raise VisionProviderError(
                VisionErrorKind.DISABLED,
                "G2A real calls are disabled",
                retryable=False,
            )
        if len(request.image_bytes) > self.config.max_image_bytes:
            raise VisionProviderError(
                VisionErrorKind.BAD_REQUEST,
                "image exceeds configured G2A byte limit",
                retryable=False,
            )

        payload = self._build_payload(request)
        http_request = Request(
            self.config.endpoint,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Request-ID": request.request_id,
            },
            method="POST",
        )
        try:
            response = self._transport(http_request, self.config.timeout_seconds)
        except (TimeoutError, socket.timeout) as exc:
            raise VisionProviderError(
                VisionErrorKind.TIMEOUT, "G2A request timed out", retryable=True
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise VisionProviderError(
                    VisionErrorKind.TIMEOUT, "G2A request timed out", retryable=True
                ) from exc
            raise VisionProviderError(
                VisionErrorKind.NETWORK, "G2A network request failed", retryable=True
            ) from exc
        except OSError as exc:
            raise VisionProviderError(
                VisionErrorKind.NETWORK, "G2A network request failed", retryable=True
            ) from exc
        except Exception as exc:
            raise VisionProviderError(
                VisionErrorKind.UPSTREAM, "G2A transport failed", retryable=True
            ) from exc

        if not 200 <= response.status < 300:
            raise _status_error(response.status, response.headers)
        return self._parse_response(response.body, request.request_id)

    def _build_payload(self, request: VisionReviewRequest) -> dict[str, object]:
        categories = ", ".join(request.categories) if request.categories else "policy configured categories"
        context = f" Additional context: {request.context}" if request.context else ""
        instruction = (
            "Review this avatar image for content moderation. Return JSON only with keys "
            "decision (allow, review, or block), confidence (0..1), reasons (string array), "
            "findings (array of category, label, optional score, explanation, region), and "
            "evidence (array of kind, description, optional region). "
            f"Evaluate: {categories}.{context} When uncertain, use review."
        )
        encoded = base64.b64encode(request.image_bytes).decode("ascii")
        return {
            "model": self.config.model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a content moderation vision reviewer. Do not infer identity.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{request.media_type};base64,{encoded}",
                            },
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }

    def _parse_response(self, body: bytes, request_id: str) -> VisionReviewConclusion:
        try:
            envelope = json.loads(body.decode("utf-8"))
            structured = _extract_structured(envelope)
            if not isinstance(structured, dict):
                raise ValueError("structured response must be an object")
            decision = structured["decision"]
            confidence = structured["confidence"]
            if decision not in {"allow", "review", "block"}:
                raise ValueError("decision must be allow, review or block")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise ValueError("confidence must be numeric")
            reasons = string_sequence(structured.get("reasons", ()), field="reasons")
            findings = _parse_findings(structured.get("findings", ()))
            evidence = _parse_evidence(structured.get("evidence", ()))
            return VisionReviewConclusion(
                decision=decision,
                confidence=float(confidence),
                reasons=reasons,
                findings=findings,
                evidence=evidence,
                provider=self.provider_name,
                model_id=self.config.model_id,
                model_version=self.config.model_version,
                prompt_version=self.config.prompt_version,
                request_id=request_id,
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisionProviderError(
                VisionErrorKind.INVALID_RESPONSE,
                f"G2A returned an invalid structured response: {exc}",
                retryable=False,
            ) from exc


def _extract_structured(envelope: object) -> object:
    if not isinstance(envelope, dict):
        raise ValueError("response envelope must be an object")
    if "decision" in envelope:
        return envelope
    choices = envelope.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return json.loads(content)
            if isinstance(content, list):
                texts = [item.get("text") for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)]
                if texts:
                    return json.loads("".join(texts))
    output_text = envelope.get("output_text")
    if isinstance(output_text, str):
        return json.loads(output_text)
    raise ValueError("response does not contain structured model output")


def _parse_findings(value: object) -> tuple[VisionFinding, ...]:
    if not isinstance(value, list):
        raise ValueError("findings must be an array")
    result: list[VisionFinding] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each finding must be an object")
        region = item.get("region")
        if region is not None and not isinstance(region, dict):
            raise ValueError("finding region must be an object")
        result.append(
            VisionFinding(
                category=_required_string(item, "category"),
                label=_required_string(item, "label"),
                score=_optional_score(item.get("score")),
                explanation=_optional_string(item.get("explanation"), "explanation"),
                region=region,
            )
        )
    return tuple(result)


def _parse_evidence(value: object) -> tuple[VisionEvidence, ...]:
    if not isinstance(value, list):
        raise ValueError("evidence must be an array")
    result: list[VisionEvidence] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each evidence item must be an object")
        region = item.get("region")
        if region is not None and not isinstance(region, dict):
            raise ValueError("evidence region must be an object")
        result.append(
            VisionEvidence(
                kind=_required_string(item, "kind"),
                description=_required_string(item, "description"),
                region=region,
            )
        )
    return tuple(result)


def _required_string(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return item


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string when provided")
    return value


def _optional_score(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("finding score must be numeric")
    return float(value)


def _status_error(status: int, headers: Mapping[str, str] | None = None) -> VisionProviderError:
    retry_after = _retry_after_seconds(headers)
    if status in {401, 403}:
        return VisionProviderError(
            VisionErrorKind.AUTHENTICATION, "G2A authentication failed", retryable=False, status_code=status
        )
    if status == 429:
        return VisionProviderError(
            VisionErrorKind.RATE_LIMIT,
            "G2A rate limit reached",
            retryable=True,
            status_code=status,
            retry_after_seconds=retry_after,
        )
    if 400 <= status < 500:
        return VisionProviderError(
            VisionErrorKind.BAD_REQUEST, "G2A rejected the request", retryable=False, status_code=status
        )
    return VisionProviderError(
        VisionErrorKind.UPSTREAM,
        "G2A upstream service failed",
        retryable=True,
        status_code=status,
        retry_after_seconds=retry_after,
    )


def _retry_after_seconds(headers: Mapping[str, str] | None) -> float | None:
    if not headers:
        return None
    value = next((item for key, item in headers.items() if key.lower() == "retry-after"), None)
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if 0 <= seconds <= 86400 else None


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError("WORDYEAH_G2A_ENABLED must be a boolean")


def _urlopen_transport(request: Request, timeout: float) -> HttpResponse:
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - endpoint is operator configuration.
            return HttpResponse(
                status=int(response.status),
                body=response.read(),
                headers=dict(response.headers.items()),
            )
    except HTTPError as exc:
        return HttpResponse(status=exc.code, body=exc.read(), headers=dict(exc.headers.items()))
