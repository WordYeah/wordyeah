from __future__ import annotations

import unittest

from wy_api.page_history_health import (
    CSS,
    PAGE_HISTORY_HEALTH_CSS,
    render_health_body,
    render_health_content,
    render_history_body,
    render_history_content,
)
from wy_api.review_ui import CSS as REVIEW_CSS


class PageHistoryHealthTest(unittest.TestCase):
    def test_history_is_a_filtered_event_stream_not_a_table(self) -> None:
        page = render_history_content(
            {
                "filters": {
                    "q": "avatar",
                    "actor": "agent-a",
                    "actors": ["agent-a", "reviewer"],
                },
                "actions": ["attempt.created", "decision.changed"],
                "stages": ["vision_review_1", "human_required"],
                "events": [
                    {
                        "created_at": "2026-08-05T02:00:00Z",
                        "item_id": "avatar-17",
                        "actor": "agent-a",
                        "action": "attempt.created",
                        "stage": "vision_review_1",
                        "detail": "低置信度，进入模型一审",
                        "status": "running",
                    }
                ],
                "total": 51,
                "start": 1,
                "end": 50,
                "pagination": {
                    "page": 1,
                    "total_pages": 2,
                    "next_url": "/review/history?offset=50",
                },
            }
        )
        self.assertIn('role="search"', page)
        self.assertIn('aria-label="审计事件流"', page)
        self.assertIn('<ol class="audit-timeline"', page)
        self.assertIn('<time class="audit-time"', page)
        self.assertIn('value="avatar"', page)
        self.assertIn('<option value="agent-a" selected>', page)
        self.assertEqual(
            page.count('class="audit-filter audit-filter-select select-control"'), 3
        )
        self.assertEqual(page.count('class="select-control__icon"'), 3)
        self.assertEqual(page.count('<path d="M6 9l6 6l6 -6"/>'), 3)
        self.assertIn(
            "@media (min-width: 761px) and (max-width: 1180px)",
            PAGE_HISTORY_HEALTH_CSS,
        )
        self.assertIn(
            "grid-template-columns: repeat(3, minmax(132px, 1fr)) auto auto",
            PAGE_HISTORY_HEALTH_CSS,
        )
        self.assertIn('class="audit-list-head"', page)
        self.assertIn("1 / 2", page)
        self.assertIn("显示 1–50", page)
        self.assertIn("2026-08-05 02:00:00", page)
        self.assertNotIn("<table", page)

    def test_history_accepts_legacy_mapping_rows_and_escapes_every_value(self) -> None:
        attack = '<img src=x onerror="alert(1)">'
        page = render_history_content(
            {
                "events": {
                    "columns": ("时间", "对象", "actor", "动作", "阶段", "原因"),
                    "rows": ((attack, attack, attack, attack, attack, attack),),
                }
            }
        )
        self.assertNotIn("<img", page)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", page)
        self.assertIn("共 1 条事件", page)

    def test_health_uses_pipeline_and_component_impact_structures(self) -> None:
        page = render_health_content(
            {
                "pipeline": {
                    "status": "degraded",
                    "summary": "二审延迟，不影响快速扫描",
                    "stages": (
                        {"name": "fast_scan", "status": "ready", "detail": "p95 18 ms"},
                        {
                            "name": "vision_review_2",
                            "status": "delayed",
                            "detail": "积压 7",
                        },
                    ),
                },
                "components": (
                    {
                        "name": "vision provider",
                        "status": "degraded",
                        "detail": "响应变慢",
                        "impact": "边界内容等待时间增加",
                        "dependencies": "vision_review_2",
                    },
                ),
            }
        )
        self.assertIn('role="status"', page)
        self.assertIn('<ol class="health-pipeline"', page)
        self.assertIn('<ul class="component-impact-list"', page)
        self.assertIn("用户影响", page)
        self.assertIn("依赖范围", page)
        self.assertNotIn("<table", page)
        self.assertNotIn("audit-timeline", page)

    def test_health_accepts_service_rows_and_escapes_content(self) -> None:
        attack = "<script>alert(1)</script>"
        page = render_health_content(
            {
                "status": "blocked",
                "summary": attack,
                "services": {
                    "columns": ("组件", "状态", "说明", "影响"),
                    "rows": ((attack, "blocked", attack, attack),),
                },
            }
        )
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn('data-tone="danger"', page)

    def test_input_contract_and_module_css(self) -> None:
        with self.assertRaisesRegex(TypeError, "Mapping"):
            render_history_content([])  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "Mapping"):
            render_health_content(None)  # type: ignore[arg-type]
        self.assertIn(".audit-timeline", CSS)
        self.assertIn(".health-pipeline", CSS)
        self.assertIn(":focus-visible", CSS)
        self.assertIn("appearance: none", CSS)
        self.assertIn(".select-control > .select-control__icon", REVIEW_CSS)
        self.assertIn("grid-template-rows: var(--select-height)", REVIEW_CSS)
        self.assertIn("grid-column: 1", REVIEW_CSS)
        self.assertIn("justify-self: end", REVIEW_CSS)
        self.assertIn("align-self: center", REVIEW_CSS)
        self.assertNotIn("transform: translateY(-50%)", REVIEW_CSS)
        self.assertIs(PAGE_HISTORY_HEALTH_CSS, CSS)
        self.assertIs(render_history_body, render_history_content)
        self.assertIs(render_health_body, render_health_content)


if __name__ == "__main__":
    unittest.main()
