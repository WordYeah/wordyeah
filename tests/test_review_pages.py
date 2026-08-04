from __future__ import annotations

import unittest

from wy_api.review_pages import (
    Metric,
    Notice,
    ReviewPageContext,
    TableData,
    render_account_page,
    render_agents_page,
    render_guide_page,
    render_health_page,
    render_history_page,
    render_overview_page,
    render_policies_page,
    render_quality_page,
    render_review_page,
)


class ReviewPagesTest(unittest.TestCase):
    def test_every_page_has_the_shared_accessible_shell(self) -> None:
        renderers = {
            "运营概览": render_overview_page,
            "AI 任务": render_agents_page,
            "策略与路由": render_policies_page,
            "质量与仲裁": render_quality_page,
            "审计历史": render_history_page,
            "系统健康": render_health_page,
            "Reviewer 账户": render_account_page,
            "审核指南": render_guide_page,
        }
        for heading, renderer in renderers.items():
            with self.subTest(heading=heading):
                page = renderer()
                self.assertIn("<!doctype html>", page)
                self.assertIn('<aside class="side-nav" aria-label="审核导航">', page)
                self.assertIn('<nav aria-label="工作台页面">', page)
                self.assertIn('<main class="shell" id="main-content">', page)
                self.assertIn(f"<h1>{heading}</h1>", page)
                self.assertIn('href="#main-content"', page)
                self.assertIn('role="status"', page)

    def test_overview_accepts_typed_and_plain_inputs(self) -> None:
        page = render_overview_page(
            {
                "attention": [Notice("二审积压", "最老任务 18 分钟", "warning")],
                "metrics": [Metric("人工介入率", "1.8%", "较昨日 +0.2%")],
                "pipeline": [{"title": "vision_review_2", "detail": "12 个等待", "meta": "p95 44s"}],
            },
            context=ReviewPageContext(consumer_id="avatar", reviewer_id="alice"),
        )
        self.assertIn("二审积压", page)
        self.assertIn("人工介入率", page)
        self.assertIn("vision_review_2", page)
        self.assertIn("当前 consumer：avatar", page)
        self.assertNotIn("<button", page)

    def test_tables_render_rows_and_empty_state(self) -> None:
        page = render_agents_page(
            {
                "agents": TableData(
                    columns=("阶段", "状态", "积压"),
                    rows=(("fast_scan", "ready", 0), ("vision_review_2", "delayed", 7)),
                )
            }
        )
        self.assertIn('<th scope="col">阶段</th>', page)
        self.assertIn("vision_review_2", page)
        self.assertIn("delayed", page)
        self.assertIn("没有需要人工关注的异常", page)

    def test_all_dynamic_content_is_escaped(self) -> None:
        attack = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        data = {
            "exceptions": [{"title": attack, "detail": attack, "tone": attack}],
            "current_policy": {attack: attack},
            "routes": {"columns": [attack], "rows": [[attack]], "empty_message": attack},
            "versions": [{"title": attack, "description": attack, "version": attack}],
        }
        page = render_policies_page(
            data,
            context={"consumer_id": attack, "reviewer_id": attack, "service_error": attack, "service_ready": False},
        )
        self.assertNotIn("<script>", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", page)
        self.assertIn('data-tone="quiet"', page)

    def test_account_only_shows_real_logout_when_csrf_is_available(self) -> None:
        without_session = render_account_page({"profile": {"角色": "reviewer"}})
        self.assertNotIn('action="/review/logout"', without_session)
        with_session = render_account_page(
            {"profile": {"角色": "reviewer"}},
            context={"csrf_token": 'token"><script>', "reviewer_id": "alice"},
        )
        self.assertIn('action="/review/logout"', with_session)
        self.assertIn('value="token&quot;&gt;&lt;script&gt;"', with_session)
        self.assertEqual(with_session.count("<button"), 1)

    def test_unknown_page_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown review page"):
            render_review_page("made-up")


if __name__ == "__main__":
    unittest.main()
