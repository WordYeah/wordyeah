#!/usr/bin/env python3
"""Submit a controlled local Cravatar manifest to a loopback WordYeah API."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wy_cravatar.backlog import (  # noqa: E402
    CravatarBacklogRecord,
    import_cravatar_backlog,
    submit_cravatar_backlog,
)


def _endpoint(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1", "::1", "localhost"
    }:
        raise ValueError("endpoint must be a loopback HTTP(S) URL")
    return value.rstrip("/") + "/v1/moderate/image"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, required=True, help="controlled local image root")
    parser.add_argument("--endpoint", default="http://127.0.0.1:18765")
    parser.add_argument("--output", type=Path, help="metadata-only result report")
    args = parser.parse_args()
    try:
        endpoint = _endpoint(args.endpoint)
        backlog = import_cravatar_backlog(args.manifest, controlled_root=args.root)
        token = os.environ.get("WORDYEAH_API_KEY")

        def submit(record: CravatarBacklogRecord, payload: bytes) -> dict[str, object]:
            with Image.open(io.BytesIO(payload)) as image:
                content_type = {
                    "JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp",
                    "GIF": "image/gif", "BMP": "image/bmp",
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
            return {
                "avatar_ref": record.avatar_ref,
                "request_id": result.get("request_id"),
                "content_sha256": result.get("content_sha256"),
                "decision": result.get("decision"),
                "mutates_avatar": False,
            }

        results = submit_cravatar_backlog(backlog, controlled_root=args.root, callback=submit)
        report = {
            "kind": "cravatar_backlog_shadow_submission",
            "source_count": backlog.source_count,
            "submitted_count": len(results),
            "duplicate_count": backlog.duplicate_count,
            "mutates_avatar": False,
            "results": results,
        }
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
            args.output.chmod(0o600)
        else:
            sys.stdout.write(rendered)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"kind": "cravatar_backlog_shadow_submission", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
