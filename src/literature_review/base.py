from __future__ import annotations

from typing import Any

from src.literature_review.config import AgentRuntimeConfig

__all__ = ["AgentBackendError", "RuntimeAwareAgent"]


class AgentBackendError(RuntimeError):
    """Raised when an agent cannot execute through its configured backend."""


class RuntimeAwareAgent:
    """Common base for agents that may later swap deterministic logic for API calls."""

    supports_api = True

    def __init__(
        self,
        runtime_config: AgentRuntimeConfig | None = None,
        *,
        api_client: Any | None = None,
    ) -> None:
        self.runtime_config = runtime_config or AgentRuntimeConfig.from_env()
        self.api_client = api_client
        self.agent_id = self._agent_id_from_class_name()

    def backend_note(self) -> str:
        if not self.supports_api:
            return "deterministic"
        return self.runtime_config.for_agent(self.agent_id).active_backend

    def call_api(
        self,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(user_payload, dict):
            raise TypeError("API user payload must be a JSON object")
        if not self.supports_api:
            raise AgentBackendError(
                f"{self.agent_id} is a protected deterministic agent"
            )
        settings = self.runtime_config.for_agent(self.agent_id)
        if settings.active_backend != "api":
            raise AgentBackendError(
                f"{self.agent_id} is configured for deterministic execution"
            )
        if self.api_client is None:
            raise AgentBackendError(
                f"{self.agent_id} requires an API client for API execution"
            )
        return self.api_client.complete_json(
            settings,
            system_prompt=system_prompt,
            user_payload=user_payload,
        )

    def _agent_id_from_class_name(self) -> str:
        name = self.__class__.__name__
        mapping = {
            "SearchAgent": "search",
            "WriterAgent": "writer",
            "ReviewerAgent": "reviewer",
            "DomainExpertAgent": "domain_expert",
            "StructureMentorAgent": "structure_mentor",
            "ReviewSynthesizerAgent": "review_synthesizer",
            "PolishAgent": "polish",
            "FinalVerificationReviewer": "final_verification",
            "EvaluationReflectionAgent": "evaluation_reflection",
        }
        return mapping.get(name, name.lower())
