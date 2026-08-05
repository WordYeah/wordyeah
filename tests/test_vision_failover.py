from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from wy_media.failover import FailoverVisionProvider, build_primary_vision_provider
from wy_media.g2a import HttpResponse
from wy_media.ollama import OllamaConfig, OllamaVisionProvider
from wy_media.vision_provider import (
    VisionErrorKind,
    VisionProviderError,
    VisionReviewConclusion,
    VisionReviewRequest,
)


def request() -> VisionReviewRequest:
    return VisionReviewRequest(
        image_bytes=b"fixture-image",
        media_type="image/jpeg",
        request_id="request-1",
        categories=("sexual_explicit",),
    )


def conclusion(provider: str) -> VisionReviewConclusion:
    return VisionReviewConclusion(
        decision="allow",
        confidence=0.95,
        reasons=(),
        findings=(),
        evidence=(),
        provider=provider,
        model_id="fixture-model",
        model_version=None,
        prompt_version="fixture-prompt",
        request_id="request-1",
    )


class VisionFailoverTests(unittest.TestCase):
    def test_g2a_failure_falls_back_to_local_provider(self) -> None:
        preferred = MagicMock(enabled=True, model_id="grok-chat-fast")
        preferred.review.side_effect = VisionProviderError(
            VisionErrorKind.UPSTREAM, "fixture failure", retryable=True
        )
        fallback = MagicMock(enabled=True, model_id="qwen3-vl:8b")
        fallback.review.return_value = conclusion("ollama")

        provider = FailoverVisionProvider(preferred, fallback)

        result = provider.review(request())
        self.assertEqual(result.provider, "ollama")
        self.assertEqual(result.evidence[-1].kind, "provider_failover")
        self.assertEqual(result.evidence[-1].description, "g2a_web_upstream")
        preferred.review.assert_called_once()
        fallback.review.assert_called_once()

    def test_primary_builder_uses_web_pool_then_ollama(self) -> None:
        provider = build_primary_vision_provider(
            {
                "WORDYEAH_G2A_ENABLED": "true",
                "WORDYEAH_G2A_ENDPOINT": "http://127.0.0.1:18000/v1/chat/completions",
                "WORDYEAH_G2A_API_KEY": "fixture-key",
                "WORDYEAH_G2A_MODEL": "grok-chat-fast",
                "WORDYEAH_OLLAMA_ENABLED": "true",
            }
        )

        self.assertIsInstance(provider, FailoverVisionProvider)
        self.assertEqual(provider.preferred.model_id, "grok-chat-fast")
        self.assertEqual(provider.fallback.model_id, "qwen3-vl:8b")

    def test_ollama_provider_returns_ollama_provenance(self) -> None:
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "allow",
                                    "confidence": 0.96,
                                    "reasons": [],
                                    "findings": [],
                                    "evidence": [],
                                }
                            )
                        }
                    }
                ]
            }
        ).encode()
        provider = OllamaVisionProvider(
            OllamaConfig(enabled=True),
            transport=lambda _request, _timeout: HttpResponse(200, body),
        )

        result = provider.review(request())

        self.assertEqual(result.provider, "ollama")
        self.assertEqual(result.model_id, "qwen3-vl:8b")


if __name__ == "__main__":
    unittest.main()
