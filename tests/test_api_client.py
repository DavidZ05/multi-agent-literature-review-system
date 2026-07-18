from __future__ import annotations

import io
import json
from email.message import Message
import socket
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request

from src.literature_review.config import AgentAPISettings
from src.literature_review.api import (
    APIClientError,
    APIResponseError,
    OpenAIChatClient,
)
from src.literature_review.api.client import _RejectRedirects, _default_opener


class FakeResponse:
    def __init__(self, payload: object | bytes, status: int = 200) -> None:
        if isinstance(payload, bytes):
            body = payload
        else:
            body = json.dumps(payload).encode("utf-8")
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
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def settings(**overrides: object) -> AgentAPISettings:
    values = {
        "agent_id": "writer",
        "backend": "api",
        "api_base_url": "https://api.example.com/v1/",
        "api_key": "secret-key",
        "model": "test-model",
        "temperature": 0.4,
        "timeout_seconds": 17,
    }
    values.update(overrides)
    return AgentAPISettings(**values)


def chat_response(content: str) -> FakeResponse:
    return FakeResponse({"choices": [{"message": {"content": content}}]})


def http_error(status: int, body: bytes = b"secret-key raw failure") -> HTTPError:
    return HTTPError(
        "https://api.example.com/v1/chat/completions?token=secret-key",
        status,
        "error",
        {},
        io.BytesIO(body),
    )


class OpenAIChatClientTests(unittest.TestCase):
    def test_default_opener_installs_only_the_rejecting_redirect_handler(self) -> None:
        redirect_handlers = [
            handler
            for handler in _default_opener().handlers
            if isinstance(handler, _RejectRedirects)
        ]

        self.assertEqual(len(redirect_handlers), 1)

    def test_redirect_handler_rejects_before_authorization_can_be_forwarded(self) -> None:
        request = Request(
            "https://api.example.test/v1/chat/completions",
            data=b"{}",
            headers={"Authorization": "Bearer secret"},
            method="POST",
        )

        with self.assertRaises(HTTPError):
            _RejectRedirects().redirect_request(
                request,
                None,
                302,
                "Found",
                Message(),
                "https://collector.example.test/capture",
            )

    def test_posts_openai_compatible_chat_request_and_parses_json_object(self) -> None:
        opener = FakeOpener([chat_response('{"summary":"ok","score":1}')])
        client = OpenAIChatClient(opener=opener, max_attempts=1)

        result = client.complete_json(
            settings(),
            system_prompt="Return JSON only.",
            user_payload={"topic": "agent memory"},
        )

        self.assertEqual(result, {"summary": "ok", "score": 1})
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, "https://api.example.com/v1/chat/completions")
        self.assertEqual(timeout, 17)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(body["temperature"], 0.4)
        self.assertEqual(body["messages"][0], {"role": "system", "content": "Return JSON only."})
        self.assertEqual(body["messages"][1]["role"], "user")
        self.assertEqual(json.loads(body["messages"][1]["content"]), {"topic": "agent memory"})

    def test_retries_retryable_statuses_with_bounded_backoff(self) -> None:
        opener = FakeOpener([http_error(429), chat_response('{"ok":true}')])
        delays = []
        client = OpenAIChatClient(
            opener=opener,
            sleeper=delays.append,
            max_attempts=2,
        )

        result = client.complete_json(settings(), system_prompt="s", user_payload={})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(delays, [1.0])
        self.assertEqual(len(opener.calls), 2)

    def test_http_errors_are_sanitized_and_classified(self) -> None:
        client = OpenAIChatClient(
            opener=FakeOpener([http_error(401)]),
            max_attempts=1,
        )

        with self.assertRaises(APIClientError) as raised:
            client.complete_json(settings(), system_prompt="s", user_payload={})

        error = raised.exception
        self.assertEqual(error.code, "auth_failed")
        self.assertFalse(error.retryable)
        self.assertEqual(error.status, 401)
        self.assertNotIn("secret-key", str(error))
        self.assertNotIn("token=", str(error))

    def test_timeout_is_retryable_and_sanitized(self) -> None:
        client = OpenAIChatClient(
            opener=FakeOpener([URLError(socket.timeout("secret-key timed out"))]),
            max_attempts=1,
        )

        with self.assertRaises(APIClientError) as raised:
            client.complete_json(settings(), system_prompt="s", user_payload={})

        self.assertEqual(raised.exception.code, "timeout")
        self.assertTrue(raised.exception.retryable)
        self.assertNotIn("secret-key", str(raised.exception))

    def test_rejects_oversized_provider_response(self) -> None:
        client = OpenAIChatClient(
            opener=FakeOpener([FakeResponse(b"12345")]),
            max_attempts=1,
            max_response_bytes=4,
        )

        with self.assertRaises(APIResponseError) as raised:
            client.complete_json(settings(), system_prompt="s", user_payload={})

        self.assertEqual(raised.exception.code, "response_too_large")

    def test_rejects_invalid_provider_json_without_leaking_body(self) -> None:
        client = OpenAIChatClient(
            opener=FakeOpener([FakeResponse(b"{secret-key")]),
            max_attempts=1,
        )

        with self.assertRaises(APIResponseError) as raised:
            client.complete_json(settings(), system_prompt="s", user_payload={})

        self.assertEqual(raised.exception.code, "invalid_response_json")
        self.assertNotIn("secret-key", str(raised.exception))

    def test_rejects_invalid_chat_response_shapes_and_model_output(self) -> None:
        cases = [
            (FakeResponse({"choices": []}), "missing_choices"),
            (chat_response(""), "empty_content"),
            (chat_response('```json\n{"ok": true}\n```'), "fenced_json"),
            (chat_response("[1, 2, 3]"), "non_object_json"),
            (FakeResponse([{"not": "an object"}]), "invalid_response"),
        ]

        for response, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                client = OpenAIChatClient(
                    opener=FakeOpener([response]),
                    max_attempts=1,
                )

                with self.assertRaises(APIResponseError) as raised:
                    client.complete_json(settings(), system_prompt="s", user_payload={})

                self.assertEqual(raised.exception.code, expected_code)


if __name__ == "__main__":
    unittest.main()
