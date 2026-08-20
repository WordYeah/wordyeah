from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.parse import urlparse

from wy_review.store import ReviewItem


_BAN_PATH = "/wp-json/cravatar/console/bans"
_PUBLIC_HOSTS = {"cravatar.com", "www.cravatar.com"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


class BanTransport(Protocol):
    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> tuple[int, bytes]:
        ...


@dataclass(frozen=True)
class BanWritebackConfig:
    url: str
    token: str
    timeout_seconds: float = 8.0


@dataclass(frozen=True)
class BanWritebackResult:
    status: str
    detail: str = ""
    http_status: int | None = None


def config_from_env(environ: Mapping[str, str] | None = None) -> BanWritebackConfig | None:
    env = os.environ if environ is None else environ
    url = str(env.get("CRAVATAR_BAN_URL", "")).strip()
    token = str(env.get("CRAVATAR_BAN_TOKEN", "")).strip()
    if url == "" or token == "":
        return None
    config = BanWritebackConfig(url=url.rstrip("/"), token=token)
    if not _valid_config(config):
        return None
    return config


def _valid_config(config: BanWritebackConfig) -> bool:
    parsed = urlparse(config.url)
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != _BAN_PATH
        or not config.token
        or config.timeout_seconds <= 0
        or config.timeout_seconds > 30
    ):
        return False
    host = parsed.hostname.lower()
    if host in _PUBLIC_HOSTS:
        return parsed.scheme == "https" and parsed.port in {None, 443}
    if host in _LOOPBACK_HOSTS:
        return parsed.scheme in {"http", "https"}
    return False


def payload_from_item(item: ReviewItem) -> dict[str, str] | None:
    if (
        item.consumer_id != "cravatar"
        or item.status != "rejected"
        or item.final_decision != "block"
        or item.avatar_action != "blacklist"
    ):
        return None
    meta = item.source_metadata or {}
    image_md5 = str(meta.get("image_md5") or meta.get("collected_content_md5") or "").lower()
    if len(image_md5) != 32 or any(ch not in "0123456789abcdef" for ch in image_md5):
        return None
    email_hash = ""
    source_ref = item.source_ref or ""
    if source_ref.startswith("cravatar://"):
        email_hash = source_ref.removeprefix("cravatar://").lower()
    payload = {
        "image_md5": image_md5,
        "source": "wordyeah",
        "item_id": item.item_id[:64],
        "reason": (item.review_note or "wordyeah-blacklist")[:200],
    }
    if email_hash and (
        (len(email_hash) == 32 or len(email_hash) == 64)
        and all(ch in "0123456789abcdef" for ch in email_hash)
    ):
        payload["email_hash"] = email_hash
    return payload


def post_blacklist(
    item: ReviewItem,
    *,
    config: BanWritebackConfig | None = None,
    transport: BanTransport | None = None,
) -> BanWritebackResult:
    if item.avatar_action != "blacklist":
        return BanWritebackResult("skipped", "not_blacklist")
    resolved = config if config is not None else config_from_env()
    if resolved is None:
        return BanWritebackResult("skipped", "writeback_disabled")
    if not _valid_config(resolved):
        return BanWritebackResult("skipped", "invalid_writeback_config")
    payload = payload_from_item(item)
    if payload is None:
        return BanWritebackResult("skipped", "missing_image_md5")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Cravatar-Ban-Token": resolved.token,
        "Idempotency-Key": f"wordyeah-blacklist:{item.item_id[:64]}",
        "X-WordYeah-Content-SHA256": item.content_sha256,
    }
    try:
        if transport is not None:
            status, raw = transport.post(resolved.url, body, headers)
        else:
            status, raw = _default_post(resolved, body, headers)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return BanWritebackResult("error", f"{type(exc).__name__}: {exc}")
    if status >= 200 and status < 300:
        return BanWritebackResult("ok", http_status=status)
    return BanWritebackResult("error", f"upstream_http_{status}", status)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _default_post(
    config: BanWritebackConfig,
    body: bytes,
    headers: Mapping[str, str],
) -> tuple[int, bytes]:
    request = urllib.request.Request(config.url, data=body, headers=dict(headers), method="POST")
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=config.timeout_seconds) as response:
        return int(response.status), response.read()
