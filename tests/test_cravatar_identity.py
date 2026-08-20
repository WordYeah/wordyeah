from __future__ import annotations

import unittest

from wy_api.cravatar_identity import (
    cravatar_avatar_url,
    normalize_reviewer_email,
    resolve_reviewer_email,
    reviewer_avatar_url,
)
from wy_api.review_ui import render_review_toolbar_actions


class CravatarIdentityTest(unittest.TestCase):
    def test_normalize_reviewer_email_lowercases_and_validates(self) -> None:
        self.assertEqual(normalize_reviewer_email("Alice@Example.com"), "alice@example.com")
        self.assertIsNone(normalize_reviewer_email("not-an-email"))
        self.assertIsNone(normalize_reviewer_email(""))

    def test_resolve_reviewer_email_prefers_explicit_email(self) -> None:
        self.assertEqual(
            resolve_reviewer_email(
                email="alice@example.com",
                username="bob@example.com",
                reviewer_id="carol@example.com",
            ),
            "alice@example.com",
        )
        self.assertEqual(
            resolve_reviewer_email(username="bob@example.com", reviewer_id="carol@example.com"),
            "bob@example.com",
        )

    def test_cravatar_avatar_url_uses_md5_hash(self) -> None:
        self.assertEqual(
            cravatar_avatar_url("alice@example.com"),
            "https://cn.cravatar.com/avatar/c160f8cc69a4f0bf2b0362752353d060?s=96&d=mp&r=g",
        )

    def test_reviewer_avatar_url_uses_cravatar_default_without_email(self) -> None:
        self.assertEqual(
            reviewer_avatar_url(reviewer_id="alice"),
            "https://cn.cravatar.com/avatar/00000000000000000000000000000000?s=96&f=y",
        )

    def test_reviewer_avatar_url_falls_back_to_reviewer_id_email(self) -> None:
        self.assertEqual(
            reviewer_avatar_url(reviewer_id="alice@example.com"),
            "https://cn.cravatar.com/avatar/c160f8cc69a4f0bf2b0362752353d060?s=96&d=mp&r=g",
        )

    def test_toolbar_renders_cravatar_default_without_email(self) -> None:
        toolbar = render_review_toolbar_actions(
            consumer_id="cravatar",
            reviewer_id="reviewer",
            reviewer_display_name="reviewer",
            workspace_menu="",
        )
        self.assertIn("cn.cravatar.com/avatar/00000000000000000000000000000000", toolbar)
        self.assertIn('class="reviewer-avatar"', toolbar)
        self.assertNotIn(">R<", toolbar)

    def test_toolbar_renders_cravatar_from_email_without_explicit_url(self) -> None:
        toolbar = render_review_toolbar_actions(
            consumer_id="default",
            reviewer_id="alice",
            reviewer_display_name="Alice Chen",
            reviewer_username="alice@example.com",
            reviewer_email="alice@example.com",
            workspace_menu="",
        )
        self.assertIn("cn.cravatar.com/avatar/c160f8cc69a4f0bf2b0362752353d060", toolbar)
        self.assertIn('class="reviewer-avatar"', toolbar)
        self.assertIn('referrerpolicy="no-referrer"', toolbar)


if __name__ == "__main__":
    unittest.main()
