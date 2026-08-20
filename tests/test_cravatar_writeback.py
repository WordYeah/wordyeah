import unittest

from wy_core.contracts import ModerationResult
from wy_cravatar.writeback import (
    BanWritebackConfig,
    config_from_env,
    payload_from_item,
    post_blacklist,
)
from wy_review.store import ReviewStore


def _result() -> ModerationResult:
    return ModerationResult(
        request_id="req",
        content_sha256="a" * 64,
        media_type="image",
        decision="review",
        reasons=("test",),
    )


class CravatarWritebackTest(unittest.TestCase):
    def test_env_off_by_default(self) -> None:
        self.assertIsNone(config_from_env({}))
        self.assertIsNone(
            config_from_env(
                {
                    "CRAVATAR_BAN_URL": "https://evil.example/bans",
                    "CRAVATAR_BAN_TOKEN": "x" * 16,
                }
            )
        )
        cfg = config_from_env(
            {
                "CRAVATAR_BAN_URL": "https://cravatar.com/wp-json/cravatar/console/bans",
                "CRAVATAR_BAN_TOKEN": "x" * 16,
            }
        )
        self.assertIsNotNone(cfg)
        assert cfg is not None
        self.assertEqual(cfg.url, "https://cravatar.com/wp-json/cravatar/console/bans")
        for bad_url in (
            "http://cravatar.com/wp-json/cravatar/console/bans",
            "https://cravatar.com:444/wp-json/cravatar/console/bans",
            "https://cravatar.com/wp-json/cravatar/console/bans?next=1",
            "https://cravatar.com/wp-json/other",
            "https://user@cravatar.com/wp-json/cravatar/console/bans",
        ):
            self.assertIsNone(
                config_from_env(
                    {"CRAVATAR_BAN_URL": bad_url, "CRAVATAR_BAN_TOKEN": "x" * 16}
                )
            )

    def test_payload_requires_image_md5(self) -> None:
        store = ReviewStore()
        item = store.enqueue(_result(), "media://x.png")
        decided = store.decide(item.item_id, "blacklist", "senior")
        self.assertIsNone(payload_from_item(decided))

        store2 = ReviewStore()
        item2 = store2.enqueue(
            _result(),
            "media://malicious.png",
            consumer_id="cravatar",
            source_ref="cravatar://5f93f983524def3dca464469d2cf9f3e",
            source_metadata={"image_md5": "5f93f983524def3dca464469d2cf9f3e"},
        )
        banned = store2.decide(item2.item_id, "blacklist", "senior")
        payload = payload_from_item(banned)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["image_md5"], "5f93f983524def3dca464469d2cf9f3e")
        self.assertEqual(payload["source"], "wordyeah")
        self.assertEqual(payload["email_hash"], "5f93f983524def3dca464469d2cf9f3e")

        foreign = ReviewStore()
        foreign_item = foreign.enqueue(
            _result(),
            "media://bad.png",
            consumer_id="another-workspace",
            source_metadata={"image_md5": "5f93f983524def3dca464469d2cf9f3e"},
        )
        foreign_ban = foreign.decide(foreign_item.item_id, "blacklist", "senior")
        self.assertIsNone(payload_from_item(foreign_ban))

    def test_reject_does_not_write_and_missing_env_skips(self) -> None:
        store = ReviewStore()
        item = store.enqueue(
            _result(),
            "media://ordinary.png",
            source_metadata={"image_md5": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
        )
        rejected = store.decide(item.item_id, "reject", "tester")
        calls: list[str] = []

        class Transport:
            def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
                calls.append(url)
                return 200, b'{"status":0}'

        cfg = BanWritebackConfig(
            url="https://cravatar.com/wp-json/cravatar/console/bans",
            token="t" * 16,
        )
        skipped = post_blacklist(rejected, config=cfg, transport=Transport())
        self.assertEqual(skipped.status, "skipped")
        self.assertEqual(calls, [])

        store2 = ReviewStore()
        item2 = store2.enqueue(
            _result(),
            "media://bad.png",
            consumer_id="cravatar",
            source_metadata={"image_md5": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
        )
        banned = store2.decide(item2.item_id, "blacklist", "senior")
        disabled = post_blacklist(banned, config=None, transport=Transport())
        self.assertEqual(disabled.status, "skipped")
        self.assertEqual(disabled.detail, "writeback_disabled")

        sent = post_blacklist(banned, config=cfg, transport=Transport())
        self.assertEqual(sent.status, "ok")
        self.assertEqual(len(calls), 1)

        invalid = post_blacklist(
            banned,
            config=BanWritebackConfig(
                url="https://evil.example/wp-json/cravatar/console/bans",
                token="t" * 16,
            ),
            transport=Transport(),
        )
        self.assertEqual(invalid.status, "skipped")
        self.assertEqual(invalid.detail, "invalid_writeback_config")
        self.assertEqual(len(calls), 1)

    def test_request_has_idempotency_and_does_not_expose_error_body(self) -> None:
        store = ReviewStore()
        item = store.enqueue(
            _result(),
            "media://bad.png",
            consumer_id="cravatar",
            source_metadata={"image_md5": "b" * 32},
        )
        banned = store.decide(item.item_id, "blacklist", "senior")
        captured: dict[str, str] = {}

        class Transport:
            def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
                captured.update(headers)
                return 503, b"upstream response containing private diagnostics"

        result = post_blacklist(
            banned,
            config=BanWritebackConfig(
                url="https://cravatar.com/wp-json/cravatar/console/bans",
                token="t" * 16,
            ),
            transport=Transport(),
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.detail, "upstream_http_503")
        self.assertEqual(result.http_status, 503)
        self.assertEqual(captured["Idempotency-Key"], f"wordyeah-blacklist:{banned.item_id}")
        self.assertEqual(captured["X-WordYeah-Content-SHA256"], banned.content_sha256)
