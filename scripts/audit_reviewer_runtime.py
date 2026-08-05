#!/usr/bin/env python3
"""Verify live reviewer-a, reviewer-b and arbitrator sessions without exposing tokens."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


REQUIRED_REVIEWERS = ("reviewer-a", "reviewer-b", "arbitrator")


def _loopback_base(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base URL must be loopback HTTP without credentials or query")
    return value.rstrip("/")


def _load_runtime(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("runtime config must be a regular non-symlink file")
        if metadata.st_mode & 0o077:
            raise ValueError("runtime config must not be accessible by group or others")
        if metadata.st_size > 64 * 1024:
            raise ValueError("runtime config exceeds 64 KiB")
        payload = handle.read(64 * 1024 + 1)
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict) or set(value) != {"reviewers", "session_secret"}:
        raise ValueError("runtime config has invalid top-level keys")
    reviewers = value.get("reviewers")
    session_secret = value.get("session_secret")
    if not isinstance(reviewers, dict) or set(reviewers) != set(REQUIRED_REVIEWERS):
        raise ValueError("runtime config must define the three required reviewer IDs")
    if any(not isinstance(token, str) or len(token) < 16 for token in reviewers.values()):
        raise ValueError("reviewer tokens must contain at least 16 characters")
    if not isinstance(session_secret, str) or len(session_secret) < 32:
        raise ValueError("session secret must contain at least 32 characters")
    return value


def _login_check(base: str, reviewer: str, token: str) -> dict[str, object]:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    request = urllib.request.Request(
        base + "/review/login",
        data=json.dumps({"reviewer_id": reviewer, "token": token}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=10) as response:
        login = json.load(response)
    with opener.open(base + "/review/account", timeout=10) as response:
        account = response.read().decode("utf-8")
    with opener.open(base + "/review/quality", timeout=10) as response:
        quality = response.read().decode("utf-8")
    passed = (
        login.get("reviewer") == reviewer
        and bool(login.get("csrf_token"))
        and reviewer in account
        and "corpus-avatar" in account
        and "corpus-primary-v1" in quality
        and "dual-review-10pct-v2" in quality
        and len(list(jar)) == 1
    )
    return {
        "name": reviewer,
        "status": "PASS" if passed else "FAIL",
        "csrf_present": bool(login.get("csrf_token")),
        "account_identity_present": reviewer in account,
        "quality_batches_present": "corpus-primary-v1" in quality
        and "dual-review-10pct-v2" in quality,
        "cookie_count": len(list(jar)),
    }


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8768")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        base = _loopback_base(args.base_url)
        runtime = _load_runtime(args.runtime)
        reviewers = runtime["reviewers"]
        checks = [
            _login_check(base, reviewer, str(reviewers[reviewer]))
            for reviewer in REQUIRED_REVIEWERS
        ]
        passed = all(check["status"] == "PASS" for check in checks)
        report = {
            "kind": "reviewer_runtime_acceptance",
            "status": "PASS" if passed else "FAIL",
            "base_url": base,
            "consumer_id": "corpus-avatar",
            "checks": checks,
            "secrets_emitted": False,
        }
        code = 0 if passed else 1
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        report = {
            "kind": "reviewer_runtime_acceptance",
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "secrets_emitted": False,
        }
        code = 2
    _atomic_write(args.output, report)
    print(json.dumps(report, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
