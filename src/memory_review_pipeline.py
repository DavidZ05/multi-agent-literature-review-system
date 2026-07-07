"""Legacy compatibility wrapper for the canonical literature_review package."""

from __future__ import annotations

from src.literature_review import (
    AgentBackendError,
    AgentAPISettings,
    AgentConfigurationError,
    AgentRuntimeConfig,
    DomainExpertAgent,
    EvaluationReflectionAgent,
    FinalVerificationReviewer,
    Orchestrator,
    PROJECT_TITLE,
    PolishAgent,
    ReviewerAgent,
    ReviewSynthesizerAgent,
    SearchAgent,
    StructureMentorAgent,
    WriterAgent,
    citation_label,
    first_author_last_name,
    load_papers,
    main,
)
from src.literature_review.base import RuntimeAwareAgent

__all__ = [
    "RuntimeAwareAgent",
    "AgentBackendError",
    "AgentAPISettings",
    "AgentConfigurationError",
    "AgentRuntimeConfig",
    "main",
    "PROJECT_TITLE",
    "citation_label",
    "first_author_last_name",
    "load_papers",
    "EvaluationReflectionAgent",
    "Orchestrator",
    "DomainExpertAgent",
    "FinalVerificationReviewer",
    "ReviewerAgent",
    "ReviewSynthesizerAgent",
    "StructureMentorAgent",
    "SearchAgent",
    "PolishAgent",
    "WriterAgent",
]


if __name__ == "__main__":
    raise SystemExit(main())
