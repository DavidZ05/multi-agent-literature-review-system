from __future__ import annotations

import json
from typing import Any

from src.literature_review.api.errors import APIResponseError


def require_json_object(value: Any, *, code: str = "invalid_response") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise APIResponseError(
            "API response was not a JSON object.",
            code=code,
            retryable=False,
        )
    return value


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise APIResponseError(
            "Model returned empty content.",
            code="empty_content",
            retryable=False,
        )
    if stripped.startswith("```"):
        raise APIResponseError(
            "Model returned fenced JSON instead of a raw object.",
            code="fenced_json",
            retryable=False,
        )
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(stripped)
    except json.JSONDecodeError as exc:
        raise APIResponseError(
            "Model content was not valid JSON.",
            code="invalid_json",
            retryable=False,
        ) from exc
    if stripped[end:].strip():
        raise APIResponseError(
            "Model content contained text outside the JSON object.",
            code="invalid_json",
            retryable=False,
        )
    return require_json_object(value, code="non_object_json")


__all__ = ["parse_json_object", "require_json_object"]
