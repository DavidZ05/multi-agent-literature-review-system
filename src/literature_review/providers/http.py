from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import ssl
import time
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_request_failed",
        retryable: bool = False,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status = status


class ProviderResponseTooLargeError(ProviderRequestError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]
    final_url: str | None = None


class HttpTransport(Protocol):
    def get(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> HttpResponse: ...


class _ValidatingRedirectHandler(HTTPRedirectHandler):
    _SENSITIVE_HEADERS = frozenset(
        {"authorization", "proxy-authorization", "x-api-key", "api-key"}
    )

    def __init__(self, validator: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self.validator = validator

    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        if self.validator is not None:
            self.validator(str(new_url))
        request_header_names = {
            str(name).lower() for name, _value in request.header_items()
        }
        if request_header_names & self._SENSITIVE_HEADERS:
            raise ProviderRequestError(
                "provider redirect rejected for a credentialed request",
                code="credentialed_redirect",
            )
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


class UrllibHttpTransport:
    USER_AGENT = "multi-agent-literature-review-system/0.2 (+local-research-workflow)"

    def __init__(
        self,
        *,
        opener: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        timeout_seconds: float = 30,
        max_attempts: int = 3,
        max_response_bytes: int = 10 * 1024 * 1024,
        url_validator: Callable[[str], None] | None = None,
    ) -> None:
        if opener is None:
            context = ssl.create_default_context(cafile=certifi.where())
            handlers = [_ValidatingRedirectHandler(url_validator)]
            handlers.append(HTTPSHandler(context=context))
            opener = build_opener(*handlers)
        self.opener = opener
        self.sleeper = sleeper
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.max_response_bytes = max_response_bytes
        self.url_validator = url_validator

    def get(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> HttpResponse:
        if self.url_validator is not None:
            self.url_validator(url)
        request_headers = {"User-Agent": self.USER_AGENT, **dict(headers)}
        for attempt in range(1, self.max_attempts + 1):
            request = Request(url, headers=request_headers, method="GET")
            try:
                with self.opener.open(
                    request, timeout=self.timeout_seconds
                ) as response:
                    body = response.read(self.max_response_bytes + 1)
                    if len(body) > self.max_response_bytes:
                        raise ProviderResponseTooLargeError(
                            f"provider response exceeded "
                            f"{self.max_response_bytes} bytes"
                        )
                    return HttpResponse(
                        status=response.status,
                        body=body,
                        headers={
                            str(key): str(value)
                            for key, value in response.headers.items()
                        },
                        final_url=(
                            str(response.geturl())
                            if callable(getattr(response, "geturl", None))
                            else url
                        ),
                    )
            except HTTPError as exc:
                if exc.code not in {429, 503} or attempt == self.max_attempts:
                    code = {
                        429: "rate_limited",
                        503: "service_unavailable",
                    }.get(exc.code, "http_error")
                    raise ProviderRequestError(
                        f"provider request failed with HTTP {exc.code}",
                        code=code,
                        retryable=exc.code in {429, 503},
                        status=exc.code,
                    ) from exc
            except (URLError, TimeoutError) as exc:
                if attempt == self.max_attempts:
                    reason = exc.reason if isinstance(exc, URLError) else exc
                    if isinstance(reason, ssl.SSLCertVerificationError):
                        raise ProviderRequestError(
                            "provider TLS certificate verification failed",
                            code="tls_verification_failed",
                        ) from exc
                    raise ProviderRequestError(
                        "provider request failed because the network was unavailable",
                        code=(
                            "timeout"
                            if isinstance(exc, TimeoutError)
                            else "network_error"
                        ),
                        retryable=True,
                    ) from exc
            self.sleeper(min(2 ** (attempt - 1), 8))
        raise AssertionError("unreachable")


__all__ = [
    "HttpResponse",
    "HttpTransport",
    "ProviderRequestError",
    "ProviderResponseTooLargeError",
    "UrllibHttpTransport",
]
