import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from wy_core.contracts import Finding, ModerationResult, sha256_bytes
from wy_core.config import load_policy_config
from wy_core.metrics import evaluate_decisions
from wy_core.policy import MediaPolicy
from wy_media.falconsai import ImageScores
from wy_media.service import MediaModerationService
from wy_word.service import TextModerationService, TextRule, load_text_rules


class ContractsTest(unittest.TestCase):
    def test_hash_is_stable_and_result_is_json_ready(self) -> None:
        digest = sha256_bytes(b"wordyeah")
        result = ModerationResult(
            request_id="req-1",
            content_sha256=digest,
            media_type="image",
            decision="review",
            reasons=("needs_review",),
            findings=(Finding("sexual_content", "nsfw", 0.4, "test"),),
            top_score=0.4,
        )
        self.assertEqual(result.to_dict()["content_sha256"], digest)
        self.assertEqual(result.to_dict()["findings"][0]["label"], "nsfw")

    def test_policy_has_three_way_decision(self) -> None:
        policy = MediaPolicy(review_threshold=0.3, block_threshold=0.85)
        self.assertEqual(policy.decide_nsfw(0.1)[0], "allow")
        self.assertEqual(policy.decide_nsfw(0.5)[0], "review")
        self.assertEqual(policy.decide_nsfw(0.9)[0], "block")

    def test_error_result_requires_error_text(self) -> None:
        with self.assertRaises(ValueError):
            ModerationResult("req", "a" * 64, "image", "error")

    def test_text_rules_share_the_same_result_contract(self) -> None:
        service = TextModerationService(
            (TextRule("example_block", ("blocked-token",), "block"),)
        )
        allowed = service.moderate("ordinary text")
        blocked = service.moderate("contains blocked-token here")
        self.assertEqual(allowed.media_type, "text")
        self.assertEqual(allowed.decision, "allow")
        self.assertEqual(blocked.decision, "block")
        self.assertEqual(blocked.findings[0].category, "sensitive_term")

    def test_text_rules_load_from_versioned_local_config(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "rules": [
                            {"label": "block_example", "terms": ["bad-token"], "decision": "block"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rules = load_text_rules(path)
        self.assertEqual(rules[0], TextRule("block_example", ("bad-token",), "block"))

    def test_invalid_text_rule_config_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text('{"version": 2, "rules": []}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_text_rules(path)

    def test_empty_text_rule_term_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TextRule("invalid", ("",), "block")

    def test_metrics_skip_recall_without_positive_samples(self) -> None:
        metrics = evaluate_decisions(("allow", "allow"), ("allow", "review")).to_dict()
        self.assertEqual(metrics["false_positive_rate"], 0.5)
        self.assertIsNone(metrics["block_recall"])
        self.assertEqual(metrics["block_recall_status"], "SKIP_NO_EXPECTED_BLOCK")

    def test_metrics_calculate_block_recall_not_false_negative_rate(self) -> None:
        metrics = evaluate_decisions(("block", "block"), ("block", "allow")).to_dict()
        self.assertEqual(metrics["block_recall"], 0.5)
        self.assertEqual(metrics["block_false_negative_rate"], 0.5)

    def test_media_service_deduplicates_by_content_hash(self) -> None:
        class FakeClassifier:
            model_version = "fake/1"

            def __init__(self) -> None:
                self.calls = 0

            def classify(self, image_bytes: bytes) -> ImageScores:
                self.calls += 1
                return ImageScores(normal=0.99, nsfw=0.01)

        classifier = FakeClassifier()
        service = MediaModerationService(classifier)
        first = service.moderate_image(b"same-image")
        second = service.moderate_image(b"same-image")
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(classifier.calls, 1)
        self.assertEqual(service.cache_hits, 1)

    def test_policy_config_validates_thresholds_and_has_stable_version(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "profile": "avatar-default",
                        "mode": "shadow",
                        "enforce": False,
                        "nsfw": {"review_threshold": 0.3, "block_threshold": 0.85},
                    }
                ),
                encoding="utf-8",
            )
            first = load_policy_config(path)
            second = load_policy_config(path)
        self.assertEqual(first.policy_version, second.policy_version)
        self.assertEqual(first.media_policy.review_threshold, 0.3)

    def test_policy_config_rejects_enforce_and_unknown_keys(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            payload = {
                "version": 1,
                "profile": "avatar-default",
                "mode": "shadow",
                "enforce": False,
                "nsfw": {"review_threshold": 0.3, "block_threshold": 0.85},
                "unexpected": True,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_policy_config(path)

            payload.pop("unexpected")
            payload["enforce"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_policy_config(path)


if __name__ == "__main__":
    unittest.main()
