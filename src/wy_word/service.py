from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from wy_core.contracts import Finding, ModerationResult, sha256_bytes


@dataclass(frozen=True)
class TextRule:
    label: str
    terms: tuple[str, ...]
    decision: str = "review"

    def __post_init__(self) -> None:
        if self.decision not in {"review", "block"}:
            raise ValueError("text rule decision must be review or block")
        if not self.terms:
            raise ValueError("text rule must contain at least one term")


class TextModerationService:
    """Deterministic text-rule baseline; no default sensitive-word list."""

    model_version = "wy-word.rules/0.1"

    def __init__(self, rules: tuple[TextRule, ...] = ()) -> None:
        self.rules = rules

    def moderate(self, text: str, request_id: str | None = None) -> ModerationResult:
        started = perf_counter()
        request_id = request_id or uuid4().hex
        payload = text.encode("utf-8")
        content_hash = sha256_bytes(payload)
        if not text.strip():
            return ModerationResult(
                request_id=request_id,
                content_sha256=content_hash,
                media_type="text",
                decision="error",
                reasons=("empty_text",),
                model_versions={"word.rules": self.model_version},
                elapsed_ms=round((perf_counter() - started) * 1000, 3),
                error="text is empty",
            )

        normalized = text.casefold()
        matches: list[Finding] = []
        decisions: list[str] = []
        for rule in self.rules:
            matched_terms = [term for term in rule.terms if term.casefold() in normalized]
            if matched_terms:
                decisions.append(rule.decision)
                matches.append(
                    Finding(
                        category="sensitive_term",
                        label=rule.label,
                        score=1.0,
                        source=self.model_version,
                    )
                )

        decision = "block" if "block" in decisions else "review" if decisions else "allow"
        reasons = ("configured_text_rule_match",) if matches else ()
        return ModerationResult(
            request_id=request_id,
            content_sha256=content_hash,
            media_type="text",
            decision=decision,
            reasons=reasons,
            findings=tuple(matches),
            top_score=1.0 if matches else 0.0,
            model_versions={"word.rules": self.model_version},
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
        )
