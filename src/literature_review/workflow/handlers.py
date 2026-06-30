from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol

from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.models import WorkflowStage
from src.literature_review.orchestrator import Orchestrator
from src.literature_review.workflow.engine import StageContext, StageResult


class OrchestratorRunner(Protocol):
    def run(self) -> dict[str, Any]: ...


OrchestratorFactory = Callable[..., OrchestratorRunner]


class PlanningHandler:
    def __call__(self, context: StageContext) -> StageResult:
        request = {
            "topic": context.run.topic,
            "corpus_path": str(context.corpus_path.resolve()),
            "runtime_config": dict(context.runtime_config),
        }
        return StageResult(
            next_stage=WorkflowStage.DRAFTING,
            output_artifacts={"inputs/research_request.json": request},
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
            orchestrator = self.orchestrator_factory(
                corpus_path=context.corpus_path,
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
    "DraftingHandler",
    "OrchestratorFactory",
    "OrchestratorRunner",
    "PlanningHandler",
]
