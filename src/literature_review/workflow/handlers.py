from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol

from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.discovery.approval import ApprovalService
from src.literature_review.discovery.service import DiscoveryService
from src.literature_review.models import CandidateStatus
from src.literature_review.models import WorkflowStage
from src.literature_review.orchestrator import Orchestrator
from src.literature_review.workflow.engine import StageContext, StageResult


class OrchestratorRunner(Protocol):
    def run(self) -> dict[str, Any]: ...


OrchestratorFactory = Callable[..., OrchestratorRunner]


class PlanningHandler:
    def __init__(self, *, discovery_enabled: bool = False) -> None:
        self.discovery_enabled = discovery_enabled

    def __call__(self, context: StageContext) -> StageResult:
        request = {
            "topic": context.run.topic,
            "corpus_path": str(context.corpus_path.resolve()),
            "runtime_config": dict(context.runtime_config),
        }
        return StageResult(
            next_stage=(
                WorkflowStage.DISCOVERING
                if self.discovery_enabled
                else WorkflowStage.DRAFTING
            ),
            output_artifacts={"inputs/research_request.json": request},
        )


class DiscoveryHandler:
    def __init__(self, service: DiscoveryService) -> None:
        self.service = service

    def __call__(self, context: StageContext) -> StageResult:
        outcome = self.service.run(
            context.run,
            context.artifact_store,
            context.workflow_store,
        )
        return StageResult(
            next_stage=WorkflowStage.SCREENING,
            output_artifacts=outcome.output_artifacts,
        )


class ScreeningHandler:
    def __call__(self, context: StageContext) -> StageResult:
        candidates = context.workflow_store.list_candidates(
            context.run.run_id,
            status=CandidateStatus.PENDING,
        )
        return StageResult(
            next_stage=(
                WorkflowStage.AWAITING_CORPUS_APPROVAL
                if candidates
                else WorkflowStage.DRAFTING
            ),
            output_artifacts={
                "discovery/screening_summary.json": {
                    "pending_candidate_count": len(candidates),
                    "candidate_ids": [
                        candidate.candidate_id for candidate in candidates
                    ],
                }
            },
            waiting_reason=(
                "candidate corpus approval required" if candidates else None
            ),
        )


class ApprovalGateHandler:
    def __init__(self, approval_service: ApprovalService) -> None:
        self.approval_service = approval_service

    def __call__(self, context: StageContext) -> StageResult:
        pending = context.workflow_store.list_candidates(
            context.run.run_id,
            status=CandidateStatus.PENDING,
        )
        if pending:
            raise ValueError(f"{len(pending)} candidate decisions are still pending")
        records = self.approval_service.build_approved_corpus(
            context.run.run_id,
            context.corpus_path,
        )
        return StageResult(
            next_stage=WorkflowStage.DRAFTING,
            output_artifacts={
                "discovery/approved_corpus.json": records,
            },
        )


class DraftingHandler:
    _JSON_ARTIFACTS = (
        "review_report.json",
        "final_verification.json",
        "evaluation_report.json",
        "revision_log.json",
    )
    _TEXT_ARTIFACTS = ("survey.md", "reflection_log.md")

    def __init__(
        self,
        runtime_config: AgentRuntimeConfig | None = None,
        *,
        orchestrator_factory: OrchestratorFactory = Orchestrator,
    ) -> None:
        self.runtime_config = runtime_config or AgentRuntimeConfig.from_env()
        self.orchestrator_factory = orchestrator_factory

    def __call__(self, context: StageContext) -> StageResult:
        with TemporaryDirectory(prefix=f"{context.run.run_id}-") as temporary:
            output_dir = Path(temporary)
            corpus_path = context.corpus_path
            approved_path = "discovery/approved_corpus.json"
            if context.artifact_store.exists(context.run.run_id, approved_path):
                corpus_path = output_dir / "approved_corpus.json"
                corpus_path.write_text(
                    context.artifact_store.read_text(context.run.run_id, approved_path),
                    encoding="utf-8",
                )
            orchestrator = self.orchestrator_factory(
                corpus_path=corpus_path,
                output_dir=output_dir,
                runtime_config=self.runtime_config,
                run_id=context.run.run_id,
            )
            orchestrator.run()
            artifacts: dict[str, Any] = {}
            for filename in self._JSON_ARTIFACTS:
                artifacts[f"final/{filename}"] = json.loads(
                    (output_dir / filename).read_text(encoding="utf-8")
                )
            for filename in self._TEXT_ARTIFACTS:
                artifacts[f"final/{filename}"] = (output_dir / filename).read_text(
                    encoding="utf-8"
                )

        return StageResult(
            next_stage=WorkflowStage.COMPLETED,
            output_artifacts=artifacts,
        )


__all__ = [
    "ApprovalGateHandler",
    "DiscoveryHandler",
    "DraftingHandler",
    "OrchestratorFactory",
    "OrchestratorRunner",
    "PlanningHandler",
    "ScreeningHandler",
]
