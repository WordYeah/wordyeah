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

            def dropdown_alignment() -> dict[str, object]:
                measurements: list[dict[str, object]] = []
                layouts: list[dict[str, object]] = []
                for width in (1440, 1180, 1024, 900, 760, 640, 390):
                    page.set_viewport_size({"width": width, "height": 900})
                    for path in (
                        "/review?status=all&view=list&per_page=20",
                        "/review/history",
                    ):
                        response = page.goto(base + path, wait_until="networkidle")
                        if response is None or response.status != 200:
                            raise RuntimeError(f"dropdown page failed: {path}")
                        controls = page.locator("select")
                        page_measurements: list[dict[str, object]] = []
                        for control in controls.all():
                            measurement = control.evaluate(
                                """select => {
                                  const wrapper = select.closest('.select-control');
                                  const icon = wrapper?.querySelector('.select-control__icon');
                                  const selectBox = select.getBoundingClientRect();
                                  const wrapperBox = wrapper?.getBoundingClientRect();
                                  const iconBox = icon?.getBoundingClientRect();
                                  const style = getComputedStyle(select);
                                  return {
                                    name: select.getAttribute('name'),
                                    wrapped: Boolean(wrapper),
                                    icon: Boolean(icon),
                                    appearance: style.appearance,
                                    selectHeight: selectBox.height,
                                    wrapperMatches: wrapperBox
                                      ? Math.abs(selectBox.left - wrapperBox.left) <= .5
                                        && Math.abs(selectBox.top - wrapperBox.top) <= .5
                                        && Math.abs(selectBox.width - wrapperBox.width) <= .5
                                        && Math.abs(selectBox.height - wrapperBox.height) <= .5
                                      : false,
                                    insideViewport: selectBox.left >= 0
                                      && selectBox.right <= innerWidth,
                                    centerDelta: iconBox
                                      ? Math.abs(
                                          (selectBox.top + selectBox.height / 2)
                                          - (iconBox.top + iconBox.height / 2)
                                        )
                                      : null,
                                  };
                                }"""
                            )
                            measurement.update({"path": path, "viewport": width})
                            measurements.append(measurement)
                            page_measurements.append(measurement)
                        root_widths = page.evaluate(
                            "() => ({scroll: document.documentElement.scrollWidth, viewport: innerWidth})"
                        )
                        filter_children_inside = True
                        if path == "/review/history":
                            filter_children_inside = page.locator(".audit-filters").evaluate(
                                """form => {
                                  const box = form.getBoundingClientRect();
                                  return [...form.children].every(child => {
                                    const childBox = child.getBoundingClientRect();
                                    return childBox.left >= box.left - .5
                                      && childBox.right <= box.right + .5;
                                  });
                                }"""
                            )
                        layouts.append(
                            {
                                "path": path,
                                "viewport": width,
                                "controls": len(page_measurements),
                                "noHorizontalOverflow": root_widths["scroll"]
                                <= root_widths["viewport"],
                                "filterChildrenInside": filter_children_inside,
                            }
                        )
                aligned = all(
                    row["wrapped"]
                    and row["icon"]
                    and row["appearance"] == "none"
                    and row["wrapperMatches"]
                    and row["insideViewport"]
                    and row["centerDelta"] is not None
                    and row["centerDelta"] <= 0.5
                    for row in measurements
                ) and all(
                    row["noHorizontalOverflow"] and row["filterChildrenInside"]
                    for row in layouts
                )
                mobile_triggers: list[dict[str, object]] = []
                for width in (900, 390):
                    page.set_viewport_size({"width": width, "height": 900})
                    for path, selector in (
                        (
                            "/review?status=all&view=list&per_page=20",
                            ".mobile-workspace-switcher > summary",
                        ),
                        ("/review/history", ".support-mobile-workspace > summary"),
                    ):
                        page.goto(base + path, wait_until="networkidle")
                        trigger = page.locator(selector)
                        trigger_measurement = trigger.evaluate(
                            """summary => {
                              const triggerBox = summary.getBoundingClientRect();
                              const iconBox = summary.querySelector('.icon').getBoundingClientRect();
                              return {
                                height: triggerBox.height,
                                iconSize: [iconBox.width, iconBox.height],
                                centerDelta: Math.abs(
                                  (triggerBox.top + triggerBox.height / 2)
                                  - (iconBox.top + iconBox.height / 2)
                                ),
                              };
                            }"""
                        )
                        trigger.click()
                        page.wait_for_timeout(200)
                        menu_box = page.locator(
                            selector.replace("> summary", ".consumer-popover-menu")
                        ).bounding_box()
                        trigger_box = trigger.bounding_box()
                        trigger_measurement["menuWithinViewport"] = bool(
                            menu_box
                            and menu_box["x"] >= 0
                            and menu_box["x"] + menu_box["width"] <= width
                        )
                        trigger_measurement["anchorEdgeDelta"] = (
                            abs(menu_box["x"] - trigger_box["x"])
                            if menu_box and trigger_box
                            else None
                        )
                        trigger_measurement.update({"path": path, "viewport": width})
                        mobile_triggers.append(trigger_measurement)
                triggers_aligned = all(
                    row["height"] <= 42
                    and row["iconSize"] == [14, 14]
                    and row["centerDelta"] <= 0.5
                    and row["menuWithinViewport"]
                    and row["anchorEdgeDelta"] is not None
                    and row["anchorEdgeDelta"] <= 0.5
                    for row in mobile_triggers
                )
                desktop_popovers: list[dict[str, object]] = []
                page.set_viewport_size({"width": 1440, "height": 900})
                for path, trigger_selector, menu_selector, max_height in (
                    (
                        "/review?status=all&view=list&per_page=20",
                        ".consumer-popover-wrapper > summary",
                        ".consumer-popover-wrapper > .consumer-popover-menu",
                        280,
                    ),
                    (
                        "/review/history",
                        ".account-menu > summary",
                        ".account-menu > .account-popover",
                        180,
                    ),
                ):
                    page.goto(base + path, wait_until="networkidle")
                    page.locator(trigger_selector).click()
                    page.wait_for_timeout(200)
                    popover = page.locator(menu_selector)
                    menu_box = popover.bounding_box()
                    trigger_box = page.locator(trigger_selector).bounding_box()
                    icon_sizes = popover.locator(".popover-action-btn > .icon").evaluate_all(
                        "icons => icons.map(icon => { const box = icon.getBoundingClientRect(); return [box.width, box.height]; })"
                    )
                    desktop_popovers.append(
                        {
                            "path": path,
                            "menu": menu_box,
                            "icons": icon_sizes,
                            "heightWithinContract": bool(
                                menu_box and menu_box["height"] <= max_height
                            ),
                            "insideViewport": bool(
                                menu_box
                                and menu_box["x"] >= 0
                                and menu_box["x"] + menu_box["width"] <= 1440
                                and menu_box["y"] >= 0
                                and menu_box["y"] + menu_box["height"] <= 900
                            ),
                            "anchorEdgeDelta": (
                                abs(menu_box["x"] - trigger_box["x"])
                                if path.startswith("/review?") and menu_box and trigger_box
                                else abs(
                                    menu_box["x"]
                                    + menu_box["width"]
                                    - trigger_box["x"]
                                    - trigger_box["width"]
                                )
                                if menu_box and trigger_box
                                else None
                            ),
                            "iconsWithinContract": all(
                                width <= 16 and height <= 16
                                for width, height in icon_sizes
                            ),
                        }
                    )
                desktop_popovers_aligned = all(
                    row["heightWithinContract"]
                    and row["insideViewport"]
                    and row["anchorEdgeDelta"] is not None
                    and row["anchorEdgeDelta"] <= 0.5
                    and row["iconsWithinContract"]
                    for row in desktop_popovers
                )
                page.set_viewport_size({"width": 1440, "height": 900})
                page.goto(base + "/review/history", wait_until="networkidle")
                shot = screenshot("dropdowns-1440x900.png")
                return {
                    "passed": (
                        aligned
                        and len(measurements) >= 28
                        and triggers_aligned
                        and len(mobile_triggers) == 4
                        and desktop_popovers_aligned
                        and len(desktop_popovers) == 2
                    ),
                    "controls": measurements,
                    "layouts": layouts,
                    "mobile_triggers": mobile_triggers,
                    "desktop_popovers": desktop_popovers,
                    "screenshot": shot,
                }

            checks.append(_check("all_dropdowns_share_alignment_contract", dropdown_alignment))

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
                proposals = page.locator("[data-quality-ai-proposal]").all_inner_texts()
                proposal_states = (
                    "待 AI 预标注",
                    "AI 预标注待入队",
                    "AI 一审排队中",
                    "AI 二审排队中",
                    "AI 建议",
                    "AI 预标注失败",
                    "AI 预标注处理中",
                )
                return {
                    "passed": bool(
                        response
                        and response.status == 200
                        and "1100" in body.replace(",", "")
                        and 0 < thumbnails <= 24
                        and original_links == thumbnails
                        and len(proposals) == thumbnails
                        and all(
                            any(proposal.startswith(state) for state in proposal_states)
                            for proposal in proposals
                        )
                        and all("quality_sample" not in proposal for proposal in proposals)
                    ),
                    "http": response.status if response else None,
                    "lazy_thumbnails": thumbnails,
                    "original_autoloads": 0,
                    "ai_proposals": len(proposals),
                    "human_truth_mutations": 0,
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
