from __future__ import annotations

import re
import unicodedata


_STOPWORDS = frozenset(
    {"a", "an", "the", "in", "of", "for", "on", "to", "and", "with", "by"}
)


def normalize_space(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_space(value).lower()
    normalized = re.sub(r"^(?:https?://doi\.org/|doi:\s*)", "", normalized)
    return normalized.rstrip(".,;)")


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_space(value).rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", normalized, flags=re.IGNORECASE)


def normalize_title_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    return " ".join(token for token in tokens if token not in _STOPWORDS)


def normalize_author(value: str) -> str:
    return normalize_space(value)


__all__ = [
    "normalize_arxiv_id",
    "normalize_author",
    "normalize_doi",
    "normalize_space",
    "normalize_title_key",
]
