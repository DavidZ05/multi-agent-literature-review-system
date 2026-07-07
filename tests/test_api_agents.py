from __future__ import annotations

import unittest

from src.literature_review.api.prompts import PromptNotFoundError, load_prompt
from src.literature_review.base import AgentBackendError
from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.writing import WriterAgent


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def complete_json(self, settings, *, system_prompt, user_payload):
        self.calls.append((settings, system_prompt, user_payload))
        return {"accepted": True, "agent": settings.agent_id}


def api_runtime() -> AgentRuntimeConfig:
    return AgentRuntimeConfig.from_env(
        {
            "AGENT_BACKEND": "api",
            "AGENT_API_MODE": "single",
            "AGENT_API_BASE_URL": "https://api.example.com/v1",
            "AGENT_API_KEY": "shared-key",
            "AGENT_MODEL": "shared-model",
        }
    )


class APIDispatchTests(unittest.TestCase):
    def test_deterministic_backend_note_is_explicit(self) -> None:
        agent = WriterAgent(AgentRuntimeConfig())

        self.assertEqual(agent.backend_note(), "deterministic")

    def test_api_call_uses_agent_profile_and_injected_client(self) -> None:
        client = FakeClient()
        agent = WriterAgent(api_runtime(), api_client=client)

        result = agent.call_api("Return JSON.", {"draft": "text"})

        self.assertEqual(result, {"accepted": True, "agent": "writer"})
        settings, system_prompt, user_payload = client.calls[0]
        self.assertEqual(settings.agent_id, "writer")
        self.assertEqual(settings.model, "shared-model")
        self.assertEqual(system_prompt, "Return JSON.")
        self.assertEqual(user_payload, {"draft": "text"})

    def test_api_backend_requires_injected_client(self) -> None:
        agent = WriterAgent(api_runtime())

        with self.assertRaisesRegex(AgentBackendError, "API client"):
            agent.call_api("Return JSON.", {"draft": "text"})

    def test_api_call_rejects_non_object_payload(self) -> None:
        agent = WriterAgent(api_runtime(), api_client=FakeClient())

        with self.assertRaisesRegex(TypeError, "JSON object"):
            agent.call_api("Return JSON.", ["not", "an", "object"])

    def test_prompt_loader_reads_packaged_prompt_files(self) -> None:
        prompt = load_prompt("writer")

        self.assertIn("Return JSON", prompt)
        self.assertIn("citation", prompt.lower())

    def test_prompt_loader_rejects_missing_prompt_files(self) -> None:
        with self.assertRaises(PromptNotFoundError):
            load_prompt("missing-prompt")


if __name__ == "__main__":
    unittest.main()
