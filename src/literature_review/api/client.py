from __future__ import annotations

import json
import socket
import ssl
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

import certifi

from src.literature_review.api.errors import (
    APIClientError,
    APIRequestError,
    APIResponseError,
)
from src.literature_review.api.validation import parse_json_object, require_json_object
from src.literature_review.config import AgentAPISettings

USER_AGENT = "multi-agent-literature-review-system/0.3"


class OpenAIChatClient:
    def __init__(
        self,
        *,
        opener: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self.opener = opener or _default_opener()
        self.sleeper = sleeper
        self.max_attempts = max(1, max_attempts)
        self.max_response_bytes = max_response_bytes

    def complete_json(
        self,
        settings: AgentAPISettings,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        request = self._build_request(settings, system_prompt, user_payload)
        response = self._open_with_retries(request, settings.timeout_seconds)
        try:
            payload = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIResponseError(
                "API response was not valid JSON.",
                code="invalid_response_json",
                retryable=False,
            ) from exc
        envelope = require_json_object(
            payload,
            code="invalid_response",
        )
        content = self._message_content(envelope)
        return parse_json_object(content)

    def _build_request(
        self,
        settings: AgentAPISettings,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> Request:
        user_content = json.dumps(
            user_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        body = {
            "model": settings.model,
            "temperature": settings.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        return Request(
            _chat_completions_url(settings.api_base_url),
            data=json.dumps(body, ensure_ascii=True).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )

    def _open_with_retries(self, request: Request, timeout_seconds: int) -> bytes:
        last_error: APIClientError | None = None
        for attempt in range(self.max_attempts):
            try:
                with self.opener.open(request, timeout=timeout_seconds) as response:
                    body = response.read(self.max_response_bytes + 1)
                    if len(body) > self.max_response_bytes:
                        raise APIResponseError(
                            "API response exceeded the configured size limit.",
                            code="response_too_large",
                            retryable=False,
                        )
                    return body
            except HTTPError as exc:
                last_error = _http_error(exc)
            except URLError as exc:
                last_error = _url_error(exc)
            except socket.timeout:
                last_error = APIRequestError(
                    "API request timed out.",
                    code="timeout",
                    retryable=True,
                )
            if (
                last_error is not None
                and last_error.retryable
                and attempt + 1 < self.max_attempts
            ):
                self.sleeper(float(2**attempt))
                continue
            assert last_error is not None
            raise last_error
        assert last_error is not None
        raise last_error

    def _message_content(self, envelope: dict[str, Any]) -> str:
        choices = envelope.get("choices")
        if not isinstance(choices, list) or not choices:
            raise APIResponseError(
                "API response did not include choices.",
                code="missing_choices",
                retryable=False,
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise APIResponseError(
                "API response choice was invalid.",
                code="invalid_response",
                retryable=False,
            )
        message = first.get("message")
        if not isinstance(message, dict):
            raise APIResponseError(
                "API response message was invalid.",
                code="invalid_response",
                retryable=False,
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise APIResponseError(
                "API response message content was invalid.",
                code="invalid_response",
                retryable=False,
            )
        return content


def _default_opener() -> Any:
    context = ssl.create_default_context(cafile=certifi.where())
    return build_opener(HTTPSHandler(context=context))


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _http_error(exc: HTTPError) -> APIRequestError:
    mapping = {
        401: ("auth_failed", False),
        403: ("auth_failed", False),
        429: ("rate_limited", True),
        503: ("service_unavailable", True),
    }
    code, retryable = mapping.get(exc.code, ("http_error", False))
    return APIRequestError(
        f"API request failed with HTTP {exc.code}.",
        code=code,
        retryable=retryable,
        status=exc.code,
    )


def _url_error(exc: URLError) -> APIRequestError:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return APIRequestError(
            "API request timed out.",
            code="timeout",
            retryable=True,
        )
    return APIRequestError(
        "API request failed before a response was received.",
        code="network_error",
        retryable=True,
    )


__all__ = ["OpenAIChatClient"]
