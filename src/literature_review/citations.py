from __future__ import annotations

import re


CITATION_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_-]{2,63}")
CITATION_PATTERN = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]{0,63})\](?!\()")


def validate_citation_key(value: object) -> str:
    if not isinstance(value, str) or not CITATION_KEY_PATTERN.fullmatch(value):
        raise ValueError(
            "citation_key must start with a lowercase letter and contain "
            "3 to 64 lowercase letters, digits, underscores, or hyphens"
        )
    return value


def citation_keys(markdown: str) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for key in CITATION_PATTERN.findall(markdown):
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


__all__ = [
    "CITATION_KEY_PATTERN",
    "CITATION_PATTERN",
    "citation_keys",
    "validate_citation_key",
]
