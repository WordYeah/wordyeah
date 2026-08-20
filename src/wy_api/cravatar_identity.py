"""Cravatar identity helpers for reviewer-facing UI."""

from __future__ import annotations

import hashlib
import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_reviewer_email(value: str | None) -> str | None:
    """Normalize and validate a reviewer email address."""
    if not value or not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized or len(normalized) > 320:
        return None
    if not _EMAIL_RE.match(normalized):
        return None
    return normalized


def resolve_reviewer_email(
    *,
    email: str | None = None,
    username: str | None = None,
    reviewer_id: str | None = None,
) -> str | None:
    """Pick the first configured value that looks like a reviewer email."""
    for candidate in (email, username, reviewer_id):
        resolved = normalize_reviewer_email(candidate)
        if resolved is not None:
            return resolved
    return None


def cravatar_default_avatar_url(*, size: int = 96) -> str:
    """Build the Cravatar platform default avatar URL."""
    bounded = max(16, min(int(size), 512))
    return f"https://cn.cravatar.com/avatar/{'0' * 32}?s={bounded}&f=y"


def cravatar_avatar_url(email: str, *, size: int = 96) -> str:
    """Build an allowlisted Cravatar URL from a reviewer email."""
    normalized = normalize_reviewer_email(email)
    if normalized is None:
        raise ValueError("email must be a valid reviewer email")
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()  # noqa: S324
    bounded = max(16, min(int(size), 512))
    return f"https://cn.cravatar.com/avatar/{digest}?s={bounded}&d=mp&r=g"


def reviewer_avatar_url(
    *,
    email: str | None = None,
    username: str | None = None,
    reviewer_id: str | None = None,
    explicit_url: str | None = None,
    size: int = 96,
) -> str:
    """Resolve the reviewer avatar URL, preferring Cravatar when email is known."""
    if explicit_url:
        return explicit_url
    resolved = resolve_reviewer_email(
        email=email,
        username=username,
        reviewer_id=reviewer_id,
    )
    if resolved is not None:
        return cravatar_avatar_url(resolved, size=size)
    return cravatar_default_avatar_url(size=size)


__all__ = [
    "cravatar_avatar_url",
    "cravatar_default_avatar_url",
    "normalize_reviewer_email",
    "resolve_reviewer_email",
    "reviewer_avatar_url",
]
