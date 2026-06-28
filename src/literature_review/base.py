from __future__ import annotations

from src.literature_review.config import AgentRuntimeConfig

__all__ = ["RuntimeAwareAgent"]


class RuntimeAwareAgent:
    """Common base for agents that may later swap deterministic logic for API calls."""

    def __init__(self, runtime_config: AgentRuntimeConfig | None = None) -> None:
        self.runtime_config = runtime_config or AgentRuntimeConfig.from_env()
        self.agent_id = self._agent_id_from_class_name()

    def backend_note(self) -> str:
        if self.runtime_config.for_agent(self.agent_id).api_enabled:
            return "api"
        return "deterministic-fallback"

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
