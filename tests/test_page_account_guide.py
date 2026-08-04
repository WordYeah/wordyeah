from __future__ import annotations

import unittest

from wy_api.page_account_guide import CSS, render_account_content, render_guide_content
from wy_api.review_pages import TableData


class AccountGuidePageTest(unittest.TestCase):
    def test_account_renders_only_supplied_identity_access_and_sessions(self) -> None:
        page = render_account_content(
            {
                "identity": {"Reviewer ID": "alice", "认证来源": "review-session"},
                "permissions": [{"name": "avatar:review", "scope": "consumer=cravatar"}],
                "sessions": [
                    {
                        "session_id": "session-7",
                        "created_at": "2026-08-05 09:00",
                        "last_seen_at": "2026-08-05 09:12",
                        "status": "当前",
                    }
                ],
            }
        )
        self.assertIn("alice", page)
        self.assertIn("avatar:review", page)
        self.assertIn("consumer=cravatar", page)
        self.assertIn("session-7", page)
        self.assertNotIn('action="/review/logout"', page)

    def test_logout_requires_a_server_supplied_csrf_token(self) -> None:
        page = render_account_content({}, csrf_token='token"><script>alert(1)</script>')
        self.assertIn('action="/review/logout"', page)
        self.assertIn('value="token&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"', page)
        self.assertNotIn("<script>alert(1)</script>", page)

    def test_account_accepts_existing_table_data_for_sessions(self) -> None:
        page = render_account_content(
            {
                "permissions": {"审核范围": "consumer=avatar"},
                "sessions": TableData(columns=("会话", "状态"), rows=(("s-1", "当前"),)),
            }
        )
        self.assertIn("审核范围", page)
        self.assertIn("consumer=avatar", page)
        self.assertIn('<th scope="col">会话</th>', page)
        self.assertIn("s-1", page)

    def test_all_account_dynamic_content_is_escaped(self) -> None:
        attack = '<img src=x onerror="alert(1)">'
        page = render_account_content(
            {
                "identity": {attack: attack},
                "permissions": [{"name": attack, "detail": attack}],
                "sessions": [{"id": attack, "status": attack}],
            }
        )
        self.assertNotIn("<img", page)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", page)

    def test_guide_contains_complete_review_reference(self) -> None:
        page = render_guide_content()
        for anchor in ("guide-principles", "guide-flow", "guide-risks", "guide-reasons", "guide-shortcuts"):
            self.assertIn(f'href="#{anchor}"', page)
            self.assertIn(f'id="{anchor}"', page)
        self.assertIn("决策流程", page)
        self.assertIn("风险定义", page)
        self.assertIn("原因词典", page)
        self.assertIn("safe_avatar", page)
        self.assertIn("media_unavailable", page)
        self.assertIn("输入框、文本域或选择控件", page)

    def test_guide_overrides_are_escaped_and_tables_are_accessible(self) -> None:
        attack = "<script>bad()</script>"
        page = render_guide_content(
            {
                "risks": ((attack, attack),),
                "reasons": ((attack, attack, attack),),
                "shortcuts": ((attack, attack),),
                "principles": (attack,),
            }
        )
        self.assertNotIn("<script>bad()</script>", page)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", page)
        self.assertIn('<nav class="account-guide__panel account-guide__toc" aria-labelledby="guide-toc-title">', page)
        self.assertGreaterEqual(page.count("<caption>"), 3)
        self.assertIn('<th scope="col">', page)

    def test_css_is_module_scoped_and_has_focus_and_mobile_rules(self) -> None:
        self.assertIn(".account-guide__panel", CSS)
        self.assertIn(":focus-visible", CSS)
        self.assertIn("@media (max-width: 640px)", CSS)
        self.assertNotIn("\nbody {", CSS)
        self.assertNotIn("\n:root {", CSS)


if __name__ == "__main__":
    unittest.main()
