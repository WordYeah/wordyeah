from __future__ import annotations

import json
import socket
import unittest

from wy_media.g2a import G2AConfig, G2AVisionProvider, HttpResponse
from wy_media.vision_provider import (
    AdvancedVisionProvider,
    VisionErrorKind,
    VisionProviderError,
    VisionReviewRequest,
)


def request() -> VisionReviewRequest:
    return VisionReviewRequest(
        image_bytes=b"fixture-image",
        media_type="image/png",
        request_id="request-1",
        categories=("sexual_explicit", "violence_gore"),
    )


def enabled_config(**changes: object) -> G2AConfig:
    values: dict[str, object] = {
        "enabled": True,
        "endpoint": "https://g2a.invalid/v1/chat/completions",
        "api_key": "fixture-key",
        "model_id": "advanced-vision-fixture",
        "model_version": "fixture-1",
        "timeout_seconds": 7.5,
    }
    values.update(changes)
    return G2AConfig(**values)  # type: ignore[arg-type]


class G2AProviderTests(unittest.TestCase):
    def test_real_calls_are_disabled_by_default(self) -> None:
        config = G2AConfig.from_env({})
        self.assertFalse(config.enabled)
        provider = G2AVisionProvider(config, transport=lambda _request, _timeout: self.fail("called"))
        with self.assertRaises(VisionProviderError) as raised:
            provider.review(request())
        self.assertEqual(raised.exception.kind, VisionErrorKind.DISABLED)
        self.assertFalse(raised.exception.retryable)

    def test_enabled_configuration_requires_runtime_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires endpoint"):
            G2AConfig.from_env({"WORDYEAH_G2A_ENABLED": "true"})

    def test_enabled_remote_endpoint_requires_https(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires HTTPS"):
            enabled_config(endpoint="http://g2a.invalid/v1/chat/completions")
        self.assertTrue(
            enabled_config(endpoint="http://127.0.0.1:8080/v1/chat/completions").enabled
        )
        with self.assertRaisesRegex(ValueError, "requires HTTPS"):
            enabled_config(endpoint="http://10.211.55.107:18000/v1/chat/completions")
        self.assertTrue(
            enabled_config(
                endpoint="http://10.211.55.107:18000/v1/chat/completions",
                allow_private_http=True,
            ).enabled
        )
        with self.assertRaisesRegex(ValueError, "requires HTTPS"):
            enabled_config(
                endpoint="http://8.8.8.8/v1/chat/completions",
                allow_private_http=True,
            )

    def test_mock_transport_receives_timeout_and_returns_structured_conclusion(self) -> None:
        seen: dict[str, object] = {}

        def transport(http_request, timeout: float) -> HttpResponse:
            seen["timeout"] = timeout
            seen["authorization"] = http_request.get_header("Authorization")
            payload = json.loads(http_request.data)
            seen["payload"] = payload
            content = {
                "decision": "review",
                "confidence": 0.78,
                "reasons": ["boundary_content"],
                "findings": [
                    {
                        "category": "sexual_suggestive",
                        "label": "possible",
                        "score": 0.78,
                        "explanation": "ambiguous clothing",
                        "region": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
                    }
                ],
                "evidence": [{"kind": "region", "description": "upper body"}],
            }
            return HttpResponse(
                200,
                json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode(),
            )

        provider = G2AVisionProvider(enabled_config(), transport=transport)
        self.assertIsInstance(provider, AdvancedVisionProvider)
        conclusion = provider.review(request())

        self.assertEqual(seen["timeout"], 7.5)
        self.assertEqual(seen["authorization"], "Bearer fixture-key")
        payload = seen["payload"]
        self.assertEqual(payload["model"], "advanced-vision-fixture")  # type: ignore[index]
        image_url = payload["messages"][1]["content"][1]["image_url"]["url"]  # type: ignore[index]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertEqual(conclusion.decision, "review")
        self.assertEqual(conclusion.findings[0].category, "sexual_suggestive")
        self.assertEqual(conclusion.provider, "g2a")
        attempt = conclusion.to_attempt_payload(stage="vision_review_1", attempt_number=2)
        self.assertEqual(attempt["status"], "succeeded")
        self.assertEqual(attempt["prompt_version"], "wordyeah-avatar-review-v1")

    def test_direct_structured_response_is_supported(self) -> None:
        body = json.dumps(
            {
                "decision": "allow",
                "confidence": 0.99,
                "reasons": [],
                "findings": [],
                "evidence": [],
            }
        ).encode()
        provider = G2AVisionProvider(enabled_config(), transport=lambda _r, _t: HttpResponse(200, body))
        self.assertEqual(provider.review(request()).decision, "allow")

    def test_complete_markdown_json_fence_is_supported(self) -> None:
        content = """```json
{"decision":"allow","confidence":0.9,"reasons":[],"findings":[],"evidence":[]}
```"""
        body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        provider = G2AVisionProvider(
            enabled_config(), transport=lambda _r, _t: HttpResponse(200, body)
        )

        self.assertEqual(provider.review(request()).decision, "allow")

    def test_markdown_json_with_surrounding_prose_remains_fail_closed(self) -> None:
        content = """Result follows:
```json
{"decision":"allow","confidence":0.9,"reasons":[],"findings":[],"evidence":[]}
```"""
        body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        provider = G2AVisionProvider(
            enabled_config(), transport=lambda _r, _t: HttpResponse(200, body)
        )

        with self.assertRaises(VisionProviderError) as raised:
            provider.review(request())
        self.assertEqual(raised.exception.kind, VisionErrorKind.INVALID_RESPONSE)

    def test_string_region_label_is_normalized(self) -> None:
        body = json.dumps(
            {
                "decision": "review",
                "confidence": 0.7,
                "reasons": ["ambiguous"],
                "findings": [
                    {
                        "category": "other",
                        "label": "ambiguous",
                        "region": "full_image",
                    }
                ],
                "evidence": [
                    {"kind": "visual", "description": "whole avatar", "region": "full_image"}
                ],
            }
        ).encode()
        provider = G2AVisionProvider(
            enabled_config(), transport=lambda _r, _t: HttpResponse(200, body)
        )

        result = provider.review(request())

        self.assertEqual(result.findings[0].region, {"label": "full_image"})
        self.assertEqual(result.evidence[0].region, {"label": "full_image"})

    def test_blank_finding_label_is_normalized_without_allowing_invalid_decision(self) -> None:
        body = json.dumps(
            {
                "decision": "review",
                "confidence": 0.72,
                "reasons": ["ambiguous"],
                "findings": [{"category": "sexual_content", "label": ""}],
                "evidence": [],
            }
        ).encode()
        provider = G2AVisionProvider(
            enabled_config(), transport=lambda _r, _t: HttpResponse(200, body)
        )

        result = provider.review(request())

        self.assertEqual(result.findings[0].label, "unspecified")

    def test_timeout_is_retryable_and_classified(self) -> None:
        def timeout(_request, _seconds):
            raise socket.timeout("fixture timeout")

        provider = G2AVisionProvider(enabled_config(), transport=timeout)
        with self.assertRaises(VisionProviderError) as raised:
            provider.review(request())
        self.assertEqual(raised.exception.kind, VisionErrorKind.TIMEOUT)
        self.assertTrue(raised.exception.retryable)
        self.assertNotIn("fixture-key", str(raised.exception))

    def test_http_errors_have_stable_retry_classification(self) -> None:
        cases = (
            (401, VisionErrorKind.AUTHENTICATION, False),
            (429, VisionErrorKind.RATE_LIMIT, True),
            (422, VisionErrorKind.BAD_REQUEST, False),
            (503, VisionErrorKind.UPSTREAM, True),
        )
        for status, kind, retryable in cases:
            with self.subTest(status=status):
                provider = G2AVisionProvider(
                    enabled_config(), transport=lambda _r, _t, status=status: HttpResponse(status, b"ignored")
                )
                with self.assertRaises(VisionProviderError) as raised:
                    provider.review(request())
                self.assertEqual(raised.exception.kind, kind)
                self.assertEqual(raised.exception.retryable, retryable)
                self.assertEqual(raised.exception.status_code, status)

    def test_invalid_model_output_is_not_treated_as_allow(self) -> None:
        provider = G2AVisionProvider(
            enabled_config(),
            transport=lambda _r, _t: HttpResponse(
                200,
                json.dumps({"decision": "allow", "confidence": "certain"}).encode(),
            ),
        )
        with self.assertRaises(VisionProviderError) as raised:
            provider.review(request())
        self.assertEqual(raised.exception.kind, VisionErrorKind.INVALID_RESPONSE)
        self.assertTrue(raised.exception.retryable)

    def test_image_limit_fails_before_transport(self) -> None:
        provider = G2AVisionProvider(
            enabled_config(max_image_bytes=3),
            transport=lambda _r, _t: self.fail("transport must not be called"),
        )
        with self.assertRaises(VisionProviderError) as raised:
            provider.review(request())
        self.assertEqual(raised.exception.kind, VisionErrorKind.BAD_REQUEST)


if __name__ == "__main__":
    unittest.main()
