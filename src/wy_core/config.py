from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .policy import MediaPolicy


@dataclass(frozen=True)
class PolicyConfig:
    """Validated, immutable policy metadata used by an avatar worker."""

    version: int
    profile: str
    mode: str
    enforce: bool
    media_policy: MediaPolicy
    policy_version: str


def load_policy_config(path: str | Path) -> PolicyConfig:
    """Load the local policy file and reject unsafe or ambiguous settings."""

    policy_path = Path(path).expanduser()
    try:
        raw: Any = json.loads(policy_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"policy file does not exist: {policy_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"policy file is not valid JSON: {policy_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("policy must be a JSON object")
    allowed = {"version", "profile", "mode", "nsfw", "enforce", "政治"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"policy contains unknown keys: {', '.join(unknown)}")
    if type(raw.get("version")) is not int or raw["version"] != 1:
        raise ValueError("policy version must be 1")

    profile = raw.get("profile")
    if not isinstance(profile, str) or not profile or len(profile) > 64:
        raise ValueError("policy profile must be a non-empty string of at most 64 characters")
    mode = raw.get("mode")
    if mode not in {"shadow", "review", "enforce"}:
        raise ValueError("policy mode must be shadow, review, or enforce")
    enforce = raw.get("enforce")
    if enforce is not False:
        raise ValueError("enforce must remain false until the avatar gate explicitly authorizes it")
    if mode == "enforce":
        raise ValueError("enforce mode is not authorized for the avatar MVP")

    nsfw = raw.get("nsfw")
    if not isinstance(nsfw, dict) or set(nsfw) != {"review_threshold", "block_threshold"}:
        raise ValueError("nsfw must contain only review_threshold and block_threshold")
    review_threshold = nsfw["review_threshold"]
    block_threshold = nsfw["block_threshold"]
    if isinstance(review_threshold, bool) or isinstance(block_threshold, bool):
        raise ValueError("NSFW thresholds must be numbers")
    if not isinstance(review_threshold, (int, float)) or not isinstance(block_threshold, (int, float)):
        raise ValueError("NSFW thresholds must be numbers")
    media_policy = MediaPolicy(float(review_threshold), float(block_threshold))

    political = raw.get("政治")
    if political is not None:
        if not isinstance(political, dict) or set(political) - {"enabled", "decision"}:
            raise ValueError("政治 may only contain enabled and decision")
        if "enabled" in political and not isinstance(political["enabled"], bool):
            raise ValueError("政治.enabled must be boolean")
        if political.get("decision", "review") != "review":
            raise ValueError("政治 decision must remain review")

    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    policy_version = f"policy-1-{sha256(canonical.encode('utf-8')).hexdigest()[:16]}"
    return PolicyConfig(
        version=1,
        profile=profile,
        mode=mode,
        enforce=False,
        media_policy=media_policy,
        policy_version=policy_version,
    )
