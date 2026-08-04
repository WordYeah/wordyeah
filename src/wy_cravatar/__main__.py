from __future__ import annotations

import argparse
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Sequence

from PIL import Image

from .backlog import CravatarBacklogRecord, import_cravatar_backlog
from .incremental import CravatarCursorStore, CravatarIncrementalImporter


def _endpoint(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise ValueError("endpoint must be a loopback HTTP(S) URL")
    return value.rstrip("/") + "/v1/moderate/image"


def _submitter(endpoint: str):
    token = os.environ.get("WORDYEAH_API_KEY")

    def submit(record: CravatarBacklogRecord, payload: bytes) -> dict[str, object]:
        with Image.open(io.BytesIO(payload)) as image:
            content_type = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
                "GIF": "image/gif",
                "BMP": "image/bmp",
            }.get(image.format)
        if content_type is None:
            raise ValueError("unsupported image format")
        headers = {"Content-Type": content_type, "Content-Length": str(len(payload))}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"WordYeah returned HTTP {exc.code}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("WordYeah returned a non-object response")
        return {
            "source_id": record.source_id,
            "request_id": result.get("request_id"),
            "decision": result.get("decision"),
            "mutates_avatar": False,
        }

    return submit


def _render(command: str, importer: CravatarIncrementalImporter, run=None) -> str:
    watermark = run.watermark if run is not None else importer.watermark()
    payload: dict[str, object] = {
        "kind": "cravatar_incremental_shadow",
        "command": command,
        "mutates_avatar": False,
        "watermark": watermark.to_dict(),
    }
    if run is not None:
        payload["outcomes"] = [
            {"source_id": item.source_id, "status": item.status, "error": item.error}
            for item in run.outcomes
        ]
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_status(rendered: str, output: Path | None) -> None:
    if output is None:
        print(rendered, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(output)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run incremental Cravatar shadow ingestion")
    parser.add_argument(
        "command", choices=("run", "replay", "watch", "pause", "resume", "watermark")
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--source", default="cravatar")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-cycles", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        importer = CravatarIncrementalImporter(
            CravatarCursorStore(args.state), workspace=args.workspace, source=args.source
        )
        run = None
        if args.command == "pause":
            importer.pause()
        elif args.command == "resume":
            importer.resume()
        elif args.command in {"run", "replay", "watch"}:
            if args.manifest is None or args.root is None:
                raise ValueError("run, replay and watch require --manifest and --root")
            if args.poll_seconds <= 0:
                raise ValueError("poll-seconds must be positive")
            if args.max_cycles is not None and args.max_cycles < 1:
                raise ValueError("max-cycles must be positive")
            callback = _submitter(_endpoint(args.endpoint))
            if args.command == "watch":
                cycles = 0
                try:
                    while True:
                        backlog = import_cravatar_backlog(
                            args.manifest, controlled_root=args.root
                        )
                        if importer.watermark().failed_count:
                            importer.replay_failed(
                                backlog,
                                controlled_root=args.root,
                                callback=callback,
                                limit=args.limit,
                            )
                        run = importer.run(
                            backlog,
                            controlled_root=args.root,
                            callback=callback,
                            limit=args.limit,
                        )
                        _write_status(_render("watch", importer, run), args.output)
                        cycles += 1
                        if args.max_cycles is not None and cycles >= args.max_cycles:
                            return 0 if not run.watermark.failed_count else 2
                        time.sleep(args.poll_seconds)
                except KeyboardInterrupt:
                    _write_status(_render("watch", importer), args.output)
                    return 0
            backlog = import_cravatar_backlog(args.manifest, controlled_root=args.root)
            operation = importer.run if args.command == "run" else importer.replay_failed
            run = operation(
                backlog,
                controlled_root=args.root,
                callback=callback,
                limit=args.limit,
            )
        rendered = _render(args.command, importer, run)
        _write_status(rendered, args.output)
        return 0 if run is None or not run.watermark.failed_count else 2
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"kind": "cravatar_incremental_shadow", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
