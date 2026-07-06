import io
import ssl
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

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
    def test_default_opener_uses_certifi_ca_bundle(self) -> None:
        context = MagicMock()
        handler = MagicMock()
        opener = MagicMock()
        with (
            patch(
                "src.literature_review.providers.http.certifi.where",
                return_value="/trusted/cacert.pem",
            ),
            patch(
                "src.literature_review.providers.http.ssl.create_default_context",
                return_value=context,
            ) as create_context,
            patch(
                "src.literature_review.providers.http.HTTPSHandler",
                return_value=handler,
            ) as https_handler,
            patch(
                "src.literature_review.providers.http.build_opener",
                return_value=opener,
            ) as build,
        ):
            transport = UrllibHttpTransport()

        create_context.assert_called_once_with(cafile="/trusted/cacert.pem")
        https_handler.assert_called_once_with(context=context)
        build.assert_called_once_with(handler)
        self.assertIs(transport.opener, opener)

    def test_injected_opener_does_not_build_ssl_context(self) -> None:
        opener = FakeOpener([FakeResponse(b"ok")])
        with patch(
            "src.literature_review.providers.http.ssl.create_default_context"
        ) as create_context:
            transport = UrllibHttpTransport(opener=opener)

        create_context.assert_not_called()
        self.assertIs(transport.opener, opener)

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

    def test_tls_failure_is_sanitized_and_actionable(self) -> None:
        certificate_error = ssl.SSLCertVerificationError(
            1,
            "unable to get local issuer certificate",
        )
        transport = UrllibHttpTransport(
            opener=FakeOpener([URLError(certificate_error)]),
            sleeper=lambda _delay: None,
            max_attempts=1,
        )

        with self.assertRaises(ProviderRequestError) as raised:
            transport.get(
                "https://example.com/search?query=private-research-topic",
                {"Authorization": "Bearer secret-value"},
            )

        self.assertEqual(raised.exception.code, "tls_verification_failed")
        self.assertFalse(raised.exception.retryable)
        self.assertNotIn("private-research-topic", str(raised.exception))
        self.assertNotIn("secret-value", str(raised.exception))

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
