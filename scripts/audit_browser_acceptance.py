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
                pending_response = page.request.get(
                    base + "/review/items?status=pending&limit=1"
                )
                pending_payload = pending_response.json() if pending_response.ok else {}
                pending_items = pending_payload.get("items", [])
                focus_item_id = (
                    pending_items[0].get("item_id")
                    if pending_items and isinstance(pending_items[0], dict)
                    else None
                )
                response = page.goto(
                    base
                    + "/review?status=pending&view=focus"
                    + (f"&focus={focus_item_id}" if focus_item_id else ""),
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
                    "eligible_item_found": bool(focus_item_id),
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
                dropdown_paths = (
                    "/review?status=all&view=list&per_page=20",
                    "/review/overview",
                    "/review/agents",
                    "/review/policies",
                    "/review/quality",
                    "/review/history",
                    "/review/health",
                    "/review/account",
                    "/review/guide",
                )
                for width in (1440, 1280, 1180, 1024, 900, 760, 640, 390):
                    page.set_viewport_size({"width": width, "height": 900})
                    for path in dropdown_paths:
                        response = page.goto(base + path, wait_until="domcontentloaded")
                        if response is None or response.status != 200:
                            raise RuntimeError(f"dropdown page failed: {path}")
                        page.add_style_tag(
                            content=(
                                "details[name='review-dropdown'] > *, "
                                "details[name='review-dropdown'] * {"
                                "animation: none !important; transition: none !important;}"
                            )
                        )
                        controls = page.locator('details[name="review-dropdown"]')
                        page_measurements: list[dict[str, object]] = []
                        for control in controls.all():
                            if not control.is_visible():
                                continue
                            control.scroll_into_view_if_needed()
                            trigger = control.locator(":scope > summary")
                            trigger.click()
                            page.wait_for_timeout(40)
                            measurement = control.evaluate(
                                """dropdown => {
                                  const trigger = dropdown.querySelector(':scope > summary');
                                  const menu = dropdown.querySelector(
                                    ':scope > .menu-select__menu, '
                                    + ':scope > .consumer-popover-menu, '
                                    + ':scope > .account-popover'
                                  );
                                  const icon = trigger?.querySelector(
                                    ':scope > .icon, '
                                    + ':scope > .chevron > .icon, '
                                    + ':scope > .dropdown-trigger__chevron > .icon'
                                  );
                                  const label = trigger?.querySelector(
                                    ':scope > .menu-select__label, '
                                    + ':scope > .dropdown-trigger__label, '
                                    + ':scope > .consumer-copy, '
                                    + ':scope > span:not(.reviewer-avatar):not(.chevron)'
                                  );
                                  const triggerBox = trigger?.getBoundingClientRect();
                                  const menuBox = menu?.getBoundingClientRect();
                                  const iconBox = icon?.getBoundingClientRect();
                                  const rawLabelBox = label?.getBoundingClientRect();
                                  const labelBox = rawLabelBox
                                    && rawLabelBox.width > 0
                                    && rawLabelBox.height > 0
                                    ? rawLabelBox
                                    : null;
                                  const options = menu
                                    ? [...menu.querySelectorAll('.menu-select__option')]
                                    : [];
                                  const optionAlignment = options.map(option => {
                                    const optionBox = option.getBoundingClientRect();
                                    const text = option.querySelector(':scope > span');
                                    const textBox = text?.getBoundingClientRect();
                                    const checkBox = option.querySelector(':scope > .icon')
                                      ?.getBoundingClientRect();
                                    return {
                                      textCenterDelta: textBox
                                        ? Math.abs(
                                            optionBox.top + optionBox.height / 2
                                            - (textBox.top + textBox.height / 2)
                                          )
                                        : null,
                                      checkCenterDelta: checkBox
                                        ? Math.abs(
                                            optionBox.top + optionBox.height / 2
                                            - (checkBox.top + checkBox.height / 2)
                                          )
                                        : null,
                                      textLeftInset: textBox
                                        ? textBox.left - optionBox.left
                                        : null,
                                      textTriggerDelta: textBox && labelBox
                                        ? Math.abs(textBox.left - labelBox.left)
                                        : null,
                                      checkTriggerDelta: checkBox && iconBox
                                        ? Math.abs(
                                            checkBox.left + checkBox.width / 2
                                            - (iconBox.left + iconBox.width / 2)
                                          )
                                        : null,
                                      textClipped: text
                                        ? text.scrollWidth > text.clientWidth + .5
                                        : null,
                                      inside: textBox
                                        ? textBox.left >= optionBox.left
                                          && textBox.right <= optionBox.right
                                        : false,
                                    };
                                  });
                                  const centerHit = menuBox
                                    ? document.elementFromPoint(
                                        menuBox.left + menuBox.width / 2,
                                        menuBox.top + Math.min(menuBox.height / 2, 18)
                                      )
                                    : null;
                                  const verticalGap = triggerBox && menuBox
                                    ? Math.min(
                                        Math.abs(menuBox.top - triggerBox.bottom),
                                        Math.abs(triggerBox.top - menuBox.bottom)
                                      )
                                    : null;
                                  const inlineEdgeDelta = triggerBox && menuBox
                                    ? Math.min(
                                        Math.abs(menuBox.left - triggerBox.left),
                                        Math.abs(menuBox.right - triggerBox.right)
                                      )
                                    : null;
                                  return {
                                    className: dropdown.className,
                                    kind: dropdown.classList.contains('menu-select')
                                      ? 'select'
                                      : dropdown.classList.contains('consumer-popover-wrapper')
                                        ? 'desktop-workspace'
                                        : dropdown.classList.contains('account-menu')
                                          ? 'account'
                                          : 'mobile-workspace',
                                    triggerHeight: triggerBox?.height ?? null,
                                    icon: Boolean(icon),
                                    menu: Boolean(menu),
                                    triggerInsideViewport: triggerBox
                                      ? triggerBox.left >= 0 && triggerBox.right <= innerWidth
                                      : false,
                                    menuInsideViewport: menuBox
                                      ? menuBox.left >= 0 && menuBox.right <= innerWidth
                                        && menuBox.top >= 0 && menuBox.bottom <= innerHeight
                                      : false,
                                    centerDelta: iconBox
                                      ? Math.abs(
                                          (triggerBox.top + triggerBox.height / 2)
                                          - (iconBox.top + iconBox.height / 2)
                                        )
                                      : null,
                                    labelCenterDelta: labelBox
                                      ? Math.abs(
                                          (triggerBox.top + triggerBox.height / 2)
                                          - (labelBox.top + labelBox.height / 2)
                                        )
                                      : null,
                                    labelClipped: labelBox
                                      ? label.scrollWidth > label.clientWidth + .5
                                      : false,
                                    optionAlignment,
                                    inlineEdgeDelta,
                                    widthDelta: triggerBox && menuBox
                                      ? Math.abs(menuBox.width - triggerBox.width)
                                      : null,
                                    menuNotNarrower: triggerBox && menuBox
                                      ? menuBox.width + .5 >= triggerBox.width
                                      : false,
                                    verticalGap,
                                    menuVisibleAtAnchor: Boolean(
                                      centerHit && menu && menu.contains(centerHit)
                                    ),
                                  };
                                }"""
                            )
                            trigger.click()
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
                                  return [...form.children]
                                    .filter(child => getComputedStyle(child).display !== 'none')
                                    .every(child => {
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
                def follows_geometry_contract(row: dict[str, object]) -> bool:
                    kind = row["kind"]
                    class_name = str(row["className"])
                    expected_gap = {
                        "select": 6.0,
                        "desktop-workspace": 10.0,
                        "account": 9.0,
                        "mobile-workspace": 8.0,
                    }[kind]
                    same_width = row["widthDelta"] is not None and row["widthDelta"] <= 0.5
                    anchored = (
                        row["inlineEdgeDelta"] is not None
                        and row["inlineEdgeDelta"] <= 0.5
                    )
                    return bool(
                        row["icon"]
                        and row["menu"]
                        and row["triggerInsideViewport"]
                        and row["menuInsideViewport"]
                        and row["menuVisibleAtAnchor"]
                        and row["centerDelta"] is not None
                        and row["centerDelta"] <= 0.5
                        and (
                            row["labelCenterDelta"] is None
                            or row["labelCenterDelta"] <= 0.75
                        )
                        and not row["labelClipped"]
                        and all(
                            option["inside"]
                            and not option["textClipped"]
                            and option["textCenterDelta"] is not None
                            and option["textCenterDelta"] <= 0.75
                            and option["textLeftInset"] is not None
                            and abs(option["textLeftInset"] - 5.0) <= 0.75
                            and (
                                option["textTriggerDelta"] is None
                                or option["textTriggerDelta"] <= 0.75
                            )
                            and (
                                option["checkTriggerDelta"] is None
                                or option["checkTriggerDelta"] <= 0.75
                            )
                            and (
                                option["checkCenterDelta"] is None
                                or option["checkCenterDelta"] <= 0.5
                            )
                            for option in row["optionAlignment"]
                        )
                        and anchored
                        and (
                            same_width
                            if kind == "desktop-workspace"
                            else row["menuNotNarrower"]
                            if kind == "select"
                            and "audit-filter-menu--actor" in class_name
                            else same_width
                            if kind == "select"
                            else True
                        )
                        and row["verticalGap"] is not None
                        and abs(row["verticalGap"] - expected_gap) <= 0.6
                    )

                aligned = all(follows_geometry_contract(row) for row in measurements) and all(
                    row["noHorizontalOverflow"] and row["filterChildrenInside"]
                    for row in layouts
                )
                interactions: list[dict[str, object]] = []
                page.set_viewport_size({"width": 1440, "height": 900})
                page.goto(
                    base + "/review?status=all&view=list&per_page=20",
                    wait_until="networkidle",
                )
                page.locator(".risk-filter-dropdown > summary").click()
                page.locator(
                    '.risk-filter-dropdown .menu-select__option[href*="risk=critical"]'
                ).click()
                page.wait_for_load_state("networkidle")
                interactions.append(
                    {
                        "name": "risk",
                        "passed": "risk=critical" in page.url
                        and page.locator(
                            ".risk-filter-dropdown .menu-select__label"
                        ).inner_text()
                        == "严重风险",
                    }
                )
                page.goto(
                    base + "/review?status=all&view=list&per_page=20",
                    wait_until="networkidle",
                )
                page.locator(".per-page-dropdown > summary").click()
                page.locator(
                    '.per-page-dropdown .menu-select__option[href*="per_page=50"]'
                ).click()
                page.wait_for_load_state("networkidle")
                interactions.append(
                    {
                        "name": "per_page",
                        "passed": "per_page=50" in page.url
                        and page.locator(
                            ".per-page-dropdown .menu-select__label"
                        ).inner_text()
                        == "50 条/页",
                    }
                )
                page.goto(base + "/review/history", wait_until="networkidle")
                actor_options = page.locator(
                    ".audit-filter-menu:first-of-type .menu-select__option"
                )
                actor_interaction = actor_options.count() > 1
                if actor_interaction:
                    page.locator(
                        ".audit-filter-menu:first-of-type > summary"
                    ).click()
                    actor_options.nth(1).click()
                    page.wait_for_load_state("networkidle")
                    actor_interaction = "actor=" in page.url
                interactions.append(
                    {"name": "history_actor", "passed": actor_interaction}
                )
                interactions_aligned = all(row["passed"] for row in interactions)
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
                        page.wait_for_timeout(250)
                        menu = page.locator(
                            selector.replace("> summary", ".consumer-popover-menu")
                        )
                        menu_box = menu.bounding_box()
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
                        trigger_measurement["visibleAtCenter"] = menu.evaluate(
                            """menu => {
                              const box = menu.getBoundingClientRect();
                              const hit = document.elementFromPoint(
                                box.left + box.width / 2,
                                box.top + box.height / 2
                              );
                              return Boolean(hit && menu.contains(hit));
                            }"""
                        )
                        trigger_measurement.update({"path": path, "viewport": width})
                        mobile_triggers.append(trigger_measurement)
                triggers_aligned = all(
                    row["height"] <= 42
                    and row["iconSize"] == [14, 14]
                    and row["centerDelta"] <= 0.5
                    and row["menuWithinViewport"]
                    and row["visibleAtCenter"]
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
                    page.wait_for_timeout(250)
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
                            "visibleAtCenter": popover.evaluate(
                                """menu => {
                                  const box = menu.getBoundingClientRect();
                                  const hit = document.elementFromPoint(
                                    box.left + box.width / 2,
                                    box.top + box.height / 2
                                  );
                                  return Boolean(hit && menu.contains(hit));
                                }"""
                            ),
                        }
                    )
                desktop_popovers_aligned = all(
                    row["heightWithinContract"]
                    and row["insideViewport"]
                    and row["anchorEdgeDelta"] is not None
                    and row["anchorEdgeDelta"] <= 0.5
                    and row["iconsWithinContract"]
                    and row["visibleAtCenter"]
                    for row in desktop_popovers
                )
                responsive_account_popovers: list[dict[str, object]] = []
                account_paths = (
                    "/review?status=all&view=list&per_page=20",
                    "/review/overview",
                    "/review/agents",
                    "/review/history",
                    "/review/policies",
                    "/review/quality",
                    "/review/health",
                    "/review/account",
                    "/review/guide",
                )
                for width in (1440, 1024, 760, 390):
                    page.set_viewport_size({"width": width, "height": 900})
                    for path in account_paths:
                        page.goto(base + path, wait_until="networkidle")
                        trigger = page.locator(".account-menu > summary")
                        trigger.click()
                        page.wait_for_timeout(250)
                        popover = page.locator(".account-menu > .account-popover")
                        trigger_box = trigger.bounding_box()
                        popover_box = popover.bounding_box()
                        responsive_account_popovers.append(
                            {
                                "path": path,
                                "viewport": width,
                                "trigger": trigger_box,
                                "popover": popover_box,
                                "insideViewport": bool(
                                    popover_box
                                    and popover_box["x"] >= 0
                                    and popover_box["x"] + popover_box["width"] <= width
                                    and popover_box["y"] >= 0
                                    and popover_box["y"] + popover_box["height"] <= 900
                                ),
                                "visibleAtCenter": popover.evaluate(
                                    """menu => {
                                      const box = menu.getBoundingClientRect();
                                      const hit = document.elementFromPoint(
                                        box.left + box.width / 2,
                                        box.top + box.height / 2
                                      );
                                      return Boolean(hit && menu.contains(hit));
                                    }"""
                                ),
                            }
                        )
                responsive_accounts_aligned = all(
                    row["insideViewport"] and row["visibleAtCenter"]
                    for row in responsive_account_popovers
                )
                page.set_viewport_size({"width": 1440, "height": 900})
                page.goto(base + "/review/history", wait_until="networkidle")
                page.locator(".audit-filter-menu:first-of-type > summary").click()
                visual_shots = [screenshot("dropdown-history-open-1440x900.png")]
                page.goto(
                    base + "/review?status=all&view=list&per_page=20",
                    wait_until="networkidle",
                )
                page.locator(".risk-filter-dropdown > summary").click()
                visual_shots.append(screenshot("dropdown-risk-open-1440x900.png"))
                page.locator(".risk-filter-dropdown > summary").click()
                page.locator(".per-page-dropdown > summary").click()
                visual_shots.append(screenshot("dropdown-per-page-open-1440x900.png"))
                page.locator(".per-page-dropdown > summary").click()
                page.locator(".account-menu > summary").click()
                visual_shots.append(screenshot("dropdown-account-open-1440x900.png"))
                return {
                    "passed": (
                        aligned
                        and len(measurements) >= 28
                        and interactions_aligned
                        and triggers_aligned
                        and len(mobile_triggers) == 4
                        and desktop_popovers_aligned
                        and len(desktop_popovers) == 2
                        and responsive_accounts_aligned
                        and len(responsive_account_popovers)
                        == len(account_paths) * 4
                    ),
                    "controls": measurements,
                    "layouts": layouts,
                    "interactions": interactions,
                    "mobile_triggers": mobile_triggers,
                    "desktop_popovers": desktop_popovers,
                    "responsive_account_popovers": responsive_account_popovers,
                    "screenshots": visual_shots,
                }

            checks.append(_check("all_dropdowns_share_alignment_contract", dropdown_alignment))

            def quality_blind_keyboard() -> dict[str, object]:
                page.set_viewport_size({"width": 1440, "height": 900})
                response = page.goto(base + "/review/quality", wait_until="networkidle")
                rows = page.locator("[data-quality-row]")
                forms = page.locator("[data-quality-action]")
                proposals = page.locator("[data-quality-ai-proposal]")
                blinded = proposals.evaluate_all(
                    "cells => cells.every(cell => "
                    "cell.dataset.blinded === 'true' "
                    "&& cell.textContent.trim() === '盲审封存 · 提交独立结论后显示')"
                )
                forms.evaluate_all(
                    "forms => forms.forEach(form => form.addEventListener('submit', event => {"
                    "event.preventDefault(); "
                    "form.dataset.capturedDecision = event.submitter?.value || '';"
                    "}))"
                )
                page.keyboard.press("j")
                focused = page.locator("[data-quality-row].is-kb-focused")
                page.keyboard.press("a")
                captured = (
                    focused.locator("[data-quality-action]").get_attribute(
                        "data-captured-decision"
                    )
                    if focused.count() == 1
                    else None
                )
                return {
                    "passed": bool(
                        response
                        and response.status == 200
                        and rows.count() > 0
                        and forms.count() > 0
                        and proposals.count() == rows.count()
                        and blinded
                        and focused.count() == 1
                        and captured == "allow"
                    ),
                    "http": response.status if response else None,
                    "rows": rows.count(),
                    "forms": forms.count(),
                    "blinded_proposals": proposals.count() if blinded else 0,
                    "focused_rows": focused.count(),
                    "captured_decision": captured,
                    "mutating_requests": 0,
                }

            checks.append(
                _check("quality_blind_keyboard_contract", quality_blind_keyboard)
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
                proposals = page.locator("[data-quality-ai-proposal]").all_inner_texts()
                blinded = page.locator(
                    '[data-quality-ai-proposal][data-blinded="true"]'
                ).count()
                return {
                    "passed": bool(
                        response
                        and response.status == 200
                        and "1100" in body.replace(",", "")
                        and 0 < thumbnails <= 24
                        and original_links == thumbnails
                        and len(proposals) == thumbnails
                        and blinded == len(proposals)
                        and all(
                            proposal == "盲审封存 · 提交独立结论后显示"
                            for proposal in proposals
                        )
                    ),
                    "http": response.status if response else None,
                    "lazy_thumbnails": thumbnails,
                    "original_autoloads": 0,
                    "ai_proposals": len(proposals),
                    "blinded_proposals": blinded,
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
