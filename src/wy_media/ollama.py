from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from .g2a import G2AConfig, G2AVisionProvider, Transport
from .vision_provider import VisionReviewRequest


@dataclass(frozen=True)
class OllamaConfig:
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:11434/v1/chat/completions"
    model_id: str = "qwen3-vl:8b"
    timeout_seconds: float = 120.0
    prompt_version: str = "wordyeah-avatar-review-ollama-v1"
    max_image_bytes: int = 10 * 1024 * 1024
    reasoning_effort: str = "none"
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        if self.reasoning_effort not in {"none", "low", "medium", "high"}:
            raise ValueError("Ollama reasoning_effort must be none, low, medium or high")
        if self.max_tokens < 64 or self.max_tokens > 4096:
            raise ValueError("Ollama max_tokens must be between 64 and 4096")

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        secondary: bool = False,
        inherit_enabled: bool = False,
    ) -> "OllamaConfig":
        values = os.environ if env is None else env
        prefix = "WORDYEAH_OLLAMA_SECONDARY_" if secondary else "WORDYEAH_OLLAMA_"
        enabled_value = values.get(f"{prefix}ENABLED")
        enabled = inherit_enabled if enabled_value is None else _parse_bool(enabled_value)
        default_model = "gemma3:12b" if secondary else "qwen3-vl:8b"
        default_prompt = (
            "wordyeah-avatar-review-ollama-secondary-v1"
            if secondary
            else "wordyeah-avatar-review-ollama-v1"
        )
        try:
            timeout = float(values.get(f"{prefix}TIMEOUT_SECONDS", "120"))
            max_bytes = int(
                values.get(f"{prefix}MAX_IMAGE_BYTES", str(10 * 1024 * 1024))
            )
            max_tokens = int(values.get(f"{prefix}MAX_TOKENS", "1024"))
        except ValueError as exc:
            raise ValueError(
                "Ollama timeout, image limit and token limit must be numeric"
            ) from exc
        return cls(
            enabled=enabled,
            endpoint=values.get(
                f"{prefix}ENDPOINT", "http://127.0.0.1:11434/v1/chat/completions"
            ).strip(),
            model_id=values.get(f"{prefix}MODEL", default_model).strip(),
            timeout_seconds=timeout,
            prompt_version=values.get(f"{prefix}PROMPT_VERSION", default_prompt).strip(),
            max_image_bytes=max_bytes,
            reasoning_effort=values.get(
                f"{prefix}REASONING_EFFORT", "none"
            ).strip().lower(),
            max_tokens=max_tokens,
        )


class OllamaVisionProvider(G2AVisionProvider):
    """Local Ollama vision provider through its OpenAI-compatible endpoint."""

    provider_name = "ollama"

    def __init__(self, config: OllamaConfig, transport: Transport | None = None) -> None:
        self.ollama_config = config
        super().__init__(
            G2AConfig(
                enabled=config.enabled,
                endpoint=config.endpoint,
                api_key="ollama-local",
                model_id=config.model_id,
                timeout_seconds=config.timeout_seconds,
                prompt_version=config.prompt_version,
                max_image_bytes=config.max_image_bytes,
            ),
            transport=transport,
        )

    def _build_payload(self, request: VisionReviewRequest) -> dict[str, object]:
        payload = super()._build_payload(request)
        # Ollama's OpenAI-compatible endpoint accepts reasoning_effort. Avatar
        # moderation needs a bounded structured verdict, not a long hidden
        # reasoning trace; disabling it materially reduces local queue latency.
        payload["reasoning_effort"] = self.ollama_config.reasoning_effort
        payload["max_tokens"] = self.ollama_config.max_tokens
        return payload


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError("Ollama boolean setting is invalid")
