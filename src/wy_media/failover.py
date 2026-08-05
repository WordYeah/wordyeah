from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from .g2a import G2AConfig, G2AVisionProvider
from .ollama import OllamaConfig, OllamaVisionProvider
from .vision_provider import (
    AdvancedVisionProvider,
    VisionEvidence,
    VisionProviderError,
    VisionReviewConclusion,
    VisionReviewRequest,
)


class FailoverVisionProvider:
    """Use the local provider whenever the preferred provider cannot conclude."""

    provider_name = "g2a-web+ollama"

    def __init__(
        self,
        preferred: AdvancedVisionProvider,
        fallback: AdvancedVisionProvider,
    ) -> None:
        self.preferred = preferred
        self.fallback = fallback
        self.enabled = bool(preferred.enabled or fallback.enabled)
        self.model_id = f"{preferred.model_id or 'disabled'}->{fallback.model_id or 'disabled'}"

    def review(self, request: VisionReviewRequest) -> VisionReviewConclusion:
        if self.preferred.enabled:
            try:
                return self.preferred.review(request)
            except VisionProviderError as error:
                if not self.fallback.enabled:
                    raise
                conclusion = self.fallback.review(request)
                return replace(
                    conclusion,
                    evidence=conclusion.evidence
                    + (
                        VisionEvidence(
                            kind="provider_failover",
                            description=f"g2a_web_{error.kind.value}",
                        ),
                    ),
                )
        return self.fallback.review(request)


def build_primary_vision_provider(
    env: Mapping[str, str] | None = None,
) -> AdvancedVisionProvider:
    g2a = G2AVisionProvider(G2AConfig.from_env(env))
    ollama = OllamaVisionProvider(OllamaConfig.from_env(env))
    if g2a.enabled and ollama.enabled:
        return FailoverVisionProvider(g2a, ollama)
    if ollama.enabled:
        return ollama
    return g2a
