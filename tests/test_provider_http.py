import io
import unittest
from urllib.error import HTTPError

from src.literature_review.providers.http import (
    ProviderRequestError,
    ProviderResponseTooLargeError,
    UrllibHttpTransport,
)


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class FakeOpener:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def http_error(status: int) -> HTTPError:
    return HTTPError(
        "https://example.com",
        status,
        "error",
        {},
        None,
    )


class UrllibHttpTransportTests(unittest.TestCase):
    def test_retries_429_and_503_with_bounded_backoff(self) -> None:
        opener = FakeOpener([http_error(429), http_error(503), FakeResponse(b"ok")])
        delays = []
        transport = UrllibHttpTransport(
            opener=opener,
            sleeper=delays.append,
            max_attempts=3,
        )

        response = transport.get("https://example.com", {})

        self.assertEqual(response.body, b"ok")
        self.assertEqual(delays, [1.0, 2.0])

    def test_non_retryable_status_raises(self) -> None:
        transport = UrllibHttpTransport(
            opener=FakeOpener([http_error(400)]),
            sleeper=lambda _delay: None,
        )
        with self.assertRaisesRegex(ProviderRequestError, "400"):
            transport.get("https://example.com", {})

    def test_rejects_oversized_response(self) -> None:
        transport = UrllibHttpTransport(
            opener=FakeOpener([FakeResponse(b"12345")]),
            max_response_bytes=4,
        )
        with self.assertRaises(ProviderResponseTooLargeError):
            transport.get("https://example.com", {})

    def test_passes_timeout_and_user_agent(self) -> None:
        opener = FakeOpener([FakeResponse(b"ok")])
        transport = UrllibHttpTransport(opener=opener, timeout_seconds=12)

        transport.get("https://example.com", {"Accept": "application/json"})

        request, timeout = opener.calls[0]
        self.assertEqual(timeout, 12)
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertIn(
            "multi-agent-literature-review-system",
            request.get_header("User-agent"),
        )


if __name__ == "__main__":
    unittest.main()
