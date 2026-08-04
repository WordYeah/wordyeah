from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .falconsai import FalconsaiClassifier
from .service import MediaModerationService

MAX_BODY_BYTES = int(os.getenv("WORDYEAH_MAX_BODY_BYTES", str(10 * 1024 * 1024)))
API_KEY = os.getenv("WORDYEAH_API_KEY")


def build_service() -> MediaModerationService:
    return MediaModerationService(
        FalconsaiClassifier(
            model_path=os.getenv("WORDYEAH_MEDIA_MODEL_PATH") or None,
            device=os.getenv("WORDYEAH_DEVICE", "auto"),
        )
    )


class Handler(BaseHTTPRequestHandler):
    service = build_service()

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
                },
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/moderate/image":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        declared = self.headers.get("Content-Length")
        if not declared or not declared.isdigit() or int(declared) > MAX_BODY_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "invalid_or_oversized_body"})
            return
        image_bytes = self.rfile.read(int(declared))
        result = self.service.moderate_image(image_bytes)
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
