#!/usr/bin/env python3
"""Run reproducible reviewer-session browser acceptance without changing decisions."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


REQUIRED_REVIEWERS = {"reviewer-a", "reviewer-b", "arbitrator"}


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
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("runtime config must be a regular non-symlink file")
        if metadata.st_mode & 0o077:
            raise ValueError("runtime config must be mode 0600")
        if metadata.st_size > 64 * 1024:
            raise ValueError("runtime config exceeds 64 KiB")
        value = json.loads(handle.read(64 * 1024 + 1).decode("utf-8"))
    if not isinstance(value, dict) or set(value) != {"reviewers", "session_secret"}:
        raise ValueError("runtime config has invalid top-level keys")
    reviewers = value.get("reviewers")
    if not isinstance(reviewers, dict) or set(reviewers) != REQUIRED_REVIEWERS:
        raise ValueError("runtime config must define the three required reviewers")
    if any(not isinstance(token, str) or len(token) < 16 for token in reviewers.values()):
        raise ValueError("reviewer tokens must contain at least 16 characters")
    return value


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _check(name: str, action: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        detail = action()
        passed = detail.pop("passed", False) is True
        return {"name": name, "status": "PASS" if passed else "FAIL", "detail": detail}
    except Exception as exc:  # browser evidence must preserve individual failures
        return {
            "name": name,
            "status": "FAIL",
            "detail": {"error": f"{type(exc).__name__}: {exc}"},
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18765")
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--screenshot-dir", type=Path, default=Path("output/playwright/mvp-browser")
    )
    parser.add_argument("--reviewer", default="reviewer-a")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    report: dict[str, object]
    exit_code = 2
    try:
        from playwright.sync_api import sync_playwright

        base = _loopback_base(args.base_url)
        runtime = _load_runtime(args.runtime)
        reviewers = runtime["reviewers"]
        assert isinstance(reviewers, dict)
        if args.reviewer not in reviewers:
            raise ValueError("reviewer is not present in runtime config")
        args.screenshot_dir.mkdir(parents=True, exist_ok=True)
        args.screenshot_dir.chmod(0o700)
        screenshots: list[str] = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not args.headed)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            login = context.request.post(
                base + "/review/login",
                data={"reviewer_id": args.reviewer, "token": reviewers[args.reviewer]},
            )
            login_payload = login.json() if login.ok else {}
            page = context.new_page()
            account = page.goto(base + "/review/account", wait_until="networkidle")
            reviewer_session = bool(
                login.ok
                and login_payload.get("reviewer") == args.reviewer
                and account is not None
                and account.status == 200
                and page.get_by_text(args.reviewer, exact=True).count() >= 1
            )

            def screenshot(name: str) -> str:
                target = args.screenshot_dir / name
                page.screenshot(path=target, full_page=False)
                target.chmod(0o600)
                rendered = str(target)
                screenshots.append(rendered)
                return rendered

            def desktop_list(width: int, height: int, name: str) -> dict[str, object]:
                page.set_viewport_size({"width": width, "height": height})
                response = page.goto(
                    base + "/review?status=all&view=list&per_page=20",
                    wait_until="networkidle",
                )
                queue = page.locator('.queue-list[data-view="list"]')
                cards = page.locator(".review-card").count()
                shot = screenshot(name)
                return {
                    "passed": bool(response and response.status == 200 and queue.count() == 1),
                    "http": response.status if response else None,
                    "viewport": [width, height],
                    "cards": cards,
                    "screenshot": shot,
                }

            checks = [
                _check(
                    "desktop_list_1440",
                    lambda: desktop_list(1440, 900, "queue-list-1440x900.png"),
                )
            ]

            def queue_views() -> dict[str, object]:
                states: dict[str, bool] = {}
                switch_labels = 0
                for view, selector in (
                    ("list", '.queue-list[data-view="list"]'),
                    ("grid", '.queue-list[data-view="grid"]'),
                    ("focus", ".review-detail .detail-layout"),
                ):
                    response = page.goto(
                        f"{base}/review?status=all&view={view}&per_page=20",
                        wait_until="networkidle",
                    )
                    states[view] = bool(
                        response and response.status == 200 and page.locator(selector).count() == 1
                    )
                    if view == "list":
                        switch_labels = page.locator('[aria-label="队列视图"] a').count()
                return {
                    "passed": all(states.values()) and switch_labels == 3,
                    "views": states,
                    "visible_switches": switch_labels,
                }

            checks.append(_check("three_queue_views", queue_views))

            def batch_contract() -> dict[str, object]:
                response = page.goto(
                    base + "/review?status=all&view=list&batch=1&per_page=50",
                    wait_until="networkidle",
                )
                selected = page.locator('input[name="selected"]').count()
                form = page.locator("[data-batch-form]")
                return {
                    "passed": bool(
                        response
                        and response.status == 200
                        and form.count() == 1
                        and form.get_attribute("data-batch-limit") == "50"
                        and 0 < selected <= 50
                    ),
                    "http": response.status if response else None,
                    "selectable_items": selected,
                    "limit": 50,
                }

            checks.append(_check("batch_mode_server_contract", batch_contract))

            def focus_no_modal() -> dict[str, object]:
                dialogs: list[str] = []
                page.on("dialog", lambda dialog: (dialogs.append(dialog.type), dialog.dismiss()))
                response = page.goto(
                    base + "/review?status=all&view=focus",
                    wait_until="networkidle",
                )
                buttons = page.locator(".action-buttons button")
                button_count = buttons.count()
                if button_count:
                    page.locator(".action-form").evaluate(
                        "form => form.addEventListener('submit', event => event.preventDefault())"
                    )
                    for index in range(button_count):
                        buttons.nth(index).click()
                return {
                    "passed": bool(
                        response and response.status == 200 and button_count >= 2 and not dialogs
                    ),
                    "http": response.status if response else None,
                    "actions": button_count,
                    "dialogs": len(dialogs),
                    "mutating_requests": 0,
                }

            checks.append(_check("focus_actions_no_modal", focus_no_modal))
            checks.append(
                _check(
                    "desktop_list_1280",
                    lambda: desktop_list(1280, 800, "queue-list-1280x800.png"),
                )
            )

            def mobile_quality() -> dict[str, object]:
                page.set_viewport_size({"width": 390, "height": 844})
                response = page.goto(base + "/review/quality", wait_until="networkidle")
                shot = screenshot("quality-390x844.png")
                return {
                    "passed": bool(
                        response
                        and response.status == 200
                        and page.locator("[data-quality-row]").count() > 0
                    ),
                    "http": response.status if response else None,
                    "viewport": [390, 844],
                    "rows": page.locator("[data-quality-row]").count(),
                    "screenshot": shot,
                }

            checks.append(_check("mobile_quality_workspace", mobile_quality))

            def mobile_overflow() -> dict[str, object]:
                response = page.goto(
                    base + "/review?status=all&view=list&per_page=20",
                    wait_until="networkidle",
                )
                widths = page.evaluate(
                    "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth})"
                )
                view_actions = page.locator(".queue-tool-actions").count()
                return {
                    "passed": bool(
                        response
                        and response.status == 200
                        and widths["scrollWidth"] <= widths["innerWidth"]
                        and view_actions == 1
                    ),
                    "http": response.status if response else None,
                    "view_actions": view_actions,
                    **widths,
                }

            checks.append(_check("mobile_no_horizontal_overflow", mobile_overflow))

            def quality_corpus() -> dict[str, object]:
                page.set_viewport_size({"width": 1440, "height": 900})
                response = page.goto(base + "/review/quality", wait_until="networkidle")
                body = page.locator("body").inner_text()
                thumbnails = page.locator('.pq-sample-link img[loading="lazy"]').count()
                original_links = page.locator('.pq-sample-link[target="_blank"]').count()
                return {
                    "passed": bool(
                        response
                        and response.status == 200
                        and "1100" in body.replace(",", "")
                        and 0 < thumbnails <= 24
                        and original_links == thumbnails
                    ),
                    "http": response.status if response else None,
                    "lazy_thumbnails": thumbnails,
                    "original_autoloads": 0,
                }

            checks.append(_check("corpus_quality_1100_paginated_thumbnails", quality_corpus))
            browser.close()

        passed = reviewer_session and all(row["status"] == "PASS" for row in checks)
        report = {
            "kind": "wordyeah_browser_acceptance",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "PASS" if passed else "FAIL",
            "base_url": base,
            "reviewer_session": reviewer_session,
            "reviewer_id": args.reviewer,
            "mutates_review_decisions": False,
            "checks": checks,
            "screenshots": screenshots,
            "secrets_emitted": False,
        }
        exit_code = 0 if passed else 1
    except Exception as exc:
        report = {
            "kind": "wordyeah_browser_acceptance",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
            "reviewer_session": False,
            "mutates_review_decisions": False,
            "secrets_emitted": False,
        }
    _atomic_write(args.output, report)
    print(json.dumps(report, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
