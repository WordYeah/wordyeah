from __future__ import annotations

import unittest

from wy_api.page_overview_agents import CSS, render_agents_body, render_overview_body, render_page_body


class OverviewAgentsPageTest(unittest.TestCase):
    def test_overview_is_exception_first_and_uses_compact_source_data(self) -> None:
        body = render_overview_body(
            {
                "attention": [{"title": "二审积压", "detail": "最老任务 18 分钟", "tone": "warning"}],
                "metrics": [{"label": "人工介入率", "value": "1.8%", "detail": "较昨日 +0.2%"}],
                "pipeline": [{"title": "vision_review_2", "detail": "12 个等待", "meta": "p95 44s"}],
            }
        )
        self.assertLess(body.index("二审积压"), body.index("人工介入率"))
        self.assertLess(body.index("人工介入率"), body.index("vision_review_2"))
        self.assertIn('<dl class="oa-summary"', body)
        self.assertNotIn("dashboard-grid", body)
        self.assertNotIn("Daily Processing Volume", body)

    def test_agents_explains_ai_first_escalation_and_final_human_gate(self) -> None:
        body = render_agents_body()
        self.assertIn('aria-label="自动审核升级链"', body)
        self.assertLess(body.index("自动审核"), body.index("高级视觉模型"))
        self.assertLess(body.index("高级视觉模型"), body.index("人工最终复核"))
        self.assertIn("仅高级视觉模型仍无法确定的项目进入人工队列", body)
        self.assertIn("未提供 AI 任务分阶段明细。", body)

    def test_existing_mapping_shape_renders_accessible_table(self) -> None:
        body = render_agents_body(
            {
                "agents": {
                    "columns": ("阶段", "状态", "积压"),
                    "rows": (("fast_scan", "ready", 0), ("vision_review_2", "delayed", 7)),
                    "empty_message": "没有需要人工关注的异常",
                }
            }
        )
        self.assertIn("<caption>AI 任务阶段明细</caption>", body)
        self.assertIn('<th scope="col">阶段</th>', body)
        self.assertIn("vision_review_2", body)

    def test_agents_table_has_mobile_card_labels_and_breakpoint_css(self) -> None:
        body = render_agents_body(
            {
                "agents": {
                    "columns": ("阶段", "状态", "积压"),
                    "rows": (("fast_scan", "ready", 0),),
                }
            }
        )
        self.assertIn('data-label="阶段"', body)
        self.assertIn('data-label="状态"', body)
        self.assertIn('data-label="积压"', body)
        self.assertIn("@media (max-width: 720px)", CSS)
        self.assertIn(".oa-table td[data-label]::before", CSS)

    def test_all_dynamic_content_is_escaped_and_tone_is_allowlisted(self) -> None:
        attack = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        body = render_overview_body(
            {
                "exceptions": [{"title": attack, "detail": attack, "tone": attack, "meta": attack}],
                "metrics": [{"label": attack, "value": attack, "detail": attack}],
                "pipeline": [{"title": attack, "description": attack, "version": attack}],
            }
        )
        self.assertNotIn("<script>", body)
        self.assertNotIn("<img", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn('data-tone="quiet"', body)

    def test_empty_state_is_explicit_and_dispatch_rejects_other_pages(self) -> None:
        body = render_overview_body({})
        self.assertIn('role="status"', body)
        self.assertIn("没有需要人工接手的异常。", body)
        self.assertIn("未提供概览指标。", body)
        self.assertEqual(render_page_body("overview", {}), body)
        with self.assertRaisesRegex(ValueError, "unsupported overview/agents page"):
            render_page_body("quality", {})

    def test_css_is_scoped_to_exported_root_class(self) -> None:
        selector_groups = [
            line.rsplit("{", 1)[0].strip()
            for line in CSS.splitlines()
            if line.strip().endswith("{") and not line.lstrip().startswith("@")
        ]
        for selector_group in selector_groups:
            for selector in selector_group.split(","):
                self.assertTrue(selector.strip().startswith(".oa-page"), selector)
        self.assertNotIn(":root", CSS)
        self.assertNotRegex(CSS, r"(?:^|\})\s*(?:body|table|a|section)\s*\{")


if __name__ == "__main__":
    unittest.main()
