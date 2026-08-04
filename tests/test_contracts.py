import unittest

from wy_core.contracts import Finding, ModerationResult, sha256_bytes
from wy_core.metrics import evaluate_decisions
from wy_core.policy import MediaPolicy
from wy_word.service import TextModerationService, TextRule


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

    def test_metrics_skip_recall_without_positive_samples(self) -> None:
        metrics = evaluate_decisions(("allow", "allow"), ("allow", "review")).to_dict()
        self.assertEqual(metrics["false_positive_rate"], 0.5)
        self.assertIsNone(metrics["block_recall"])
        self.assertEqual(metrics["block_recall_status"], "SKIP_NO_EXPECTED_BLOCK")


if __name__ == "__main__":
    unittest.main()
