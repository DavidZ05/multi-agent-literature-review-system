"""Canonical package API for the literature review workflow."""

from src.literature_review.cli import main
from src.literature_review.base import AgentBackendError
from src.literature_review.config import (
    AgentAPISettings,
    AgentConfigurationError,
    AgentRuntimeConfig,
)
from src.literature_review.corpus import (
    PROJECT_TITLE,
    citation_label,
    first_author_last_name,
    load_papers,
)
from src.literature_review.evaluation import EvaluationReflectionAgent
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    CorpusDecision,
    ProviderPaper,
    ProviderSearchResult,
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    SearchQuery,
    StageCheckpoint,
    WorkflowEvent,
    WorkflowStage,
    utc_now_iso,
)
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

__version__ = "0.3.0"

__all__ = [
    "main",
    "AgentBackendError",
    "AgentAPISettings",
    "AgentConfigurationError",
    "AgentRuntimeConfig",
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
    "CandidatePaper",
    "CandidateStatus",
    "CorpusDecision",
    "ProviderPaper",
    "ProviderSearchResult",
    "ResearchRun",
    "RunStatus",
    "ScreeningRecommendation",
    "SearchQuery",
    "WorkflowStage",
    "WorkflowEvent",
    "StageCheckpoint",
    "utc_now_iso",
]
