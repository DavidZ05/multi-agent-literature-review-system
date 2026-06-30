from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import time
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener


class ProviderRequestError(RuntimeError):
    pass


class ProviderResponseTooLargeError(ProviderRequestError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


class HttpTransport(Protocol):
    def get(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> HttpResponse: ...


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
    ) -> None:
        self.opener = opener or build_opener()
        self.sleeper = sleeper
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.max_response_bytes = max_response_bytes

    def get(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> HttpResponse:
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
                    )
            except HTTPError as exc:
                if exc.code not in {429, 503} or attempt == self.max_attempts:
                    raise ProviderRequestError(
                        f"provider request failed with HTTP {exc.code}: {url}"
                    ) from exc
            except (URLError, TimeoutError) as exc:
                if attempt == self.max_attempts:
                    raise ProviderRequestError(
                        f"provider request failed: {url}"
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
