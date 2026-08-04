from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .falconsai import FalconsaiClassifier
from .service import MediaModerationService
from wy_word.service import TextModerationService, load_text_rules

MAX_BODY_BYTES = int(os.getenv("WORDYEAH_MAX_BODY_BYTES", str(10 * 1024 * 1024)))
API_KEY = os.getenv("WORDYEAH_API_KEY")
IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}


def build_service() -> MediaModerationService:
    return MediaModerationService(
        FalconsaiClassifier(
            model_path=os.getenv("WORDYEAH_MEDIA_MODEL_PATH") or None,
            device=os.getenv("WORDYEAH_DEVICE", "auto"),
        )
    )


def build_text_service() -> TextModerationService:
    rules_path = os.getenv("WORDYEAH_TEXT_RULES")
    if not rules_path:
        return TextModerationService()
    return TextModerationService(load_text_rules(rules_path))


class Handler(BaseHTTPRequestHandler):
    service = build_service()
    text_service = build_text_service()

    def _authorized(self) -> bool:
        if not API_KEY:
            return True
        return self.headers.get("Authorization") == f"Bearer {API_KEY}"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "ready": Handler.service.classifier._model is not None,
                    "external_model_calls": False,
                    "cache_hits": Handler.service.cache_hits,
                },
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/v1/moderate/image", "/v1/moderate/text"}:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        declared = self.headers.get("Content-Length")
        if not declared or not declared.isdigit() or int(declared) > MAX_BODY_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "invalid_or_oversized_body"})
            return
        body = self.rfile.read(int(declared))
        if self.path == "/v1/moderate/text":
            try:
                payload = json.loads(body.decode("utf-8"))
                text = payload["text"]
                if not isinstance(text, str):
                    raise ValueError("text must be a string")
            except (UnicodeDecodeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": f"invalid_text_request: {exc}"})
                return
            result = self.text_service.moderate(text)
        else:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in IMAGE_CONTENT_TYPES:
                self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "unsupported_image_content_type"})
                return
            result = self.service.moderate_image(body)
        status = HTTPStatus.OK if result.decision != "error" else HTTPStatus.UNPROCESSABLE_ENTITY
        self._json(status, result.to_dict())

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host or os.getenv("WORDYEAH_BIND", "127.0.0.1")
    port = port or int(os.getenv("WORDYEAH_PORT", "18765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"WordYeah media PoC listening on http://{host}:{port}", flush=True)
    server.serve_forever()
