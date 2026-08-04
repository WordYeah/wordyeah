from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
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
        if not self.terms or any(not isinstance(term, str) or not term.strip() for term in self.terms):
            raise ValueError("text rule must contain non-empty terms")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TextRule":
        """Build a rule from the versioned, local JSON configuration shape."""

        if not isinstance(value, dict):
            raise ValueError("text rule must be an object")
        label = value.get("label")
        terms = value.get("terms")
        decision = value.get("decision", "review")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("text rule label must be a non-empty string")
        if not isinstance(terms, list) or any(not isinstance(term, str) for term in terms):
            raise ValueError("text rule terms must be a list of strings")
        if not isinstance(decision, str):
            raise ValueError("text rule decision must be a string")
        return cls(label=label, terms=tuple(terms), decision=decision)


def load_text_rules(path: str | Path) -> tuple[TextRule, ...]:
    """Load only local JSON rules; invalid configuration fails closed at startup."""

    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to load text rules from {config_path}: {exc}") from exc

    if isinstance(payload, dict):
        if payload.get("version") != 1:
            raise ValueError("text rule config version must be 1")
        raw_rules = payload.get("rules")
    else:
        raise ValueError("text rule config must be an object")
    if not isinstance(raw_rules, list):
        raise ValueError("text rule config rules must be a list")
    return tuple(TextRule.from_dict(rule) for rule in raw_rules)


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
