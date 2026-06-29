from __future__ import annotations

from src.literature_review.base import RuntimeAwareAgent
from src.literature_review.config import AgentAPISettings, AgentRuntimeConfig
from src.literature_review.cli import main
from src.literature_review.corpus import load_papers
from src.literature_review.evaluation import EvaluationReflectionAgent
from src.literature_review.orchestrator import Orchestrator
from src.literature_review.review import (
    DomainExpertAgent,
    FinalVerificationReviewer,
    ReviewerAgent,
    ReviewSynthesizerAgent,
    StructureMentorAgent,
)
from src.literature_review.search import SearchAgent
from src.literature_review.writing import PolishAgent, WriterAgent

__all__ = [
    "RuntimeAwareAgent",
    "AgentAPISettings",
    "AgentRuntimeConfig",
    "main",
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
    main()
