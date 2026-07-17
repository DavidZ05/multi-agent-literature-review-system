from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from src.literature_review.models import (
    CandidateStatus,
    ResearchRun,
)
from src.literature_review.storage import SQLiteWorkflowStore
from src.literature_review.workbench.deletion import ArtifactDeletionManager
from src.literature_review.workbench.discovery_service import (
    DiscoveryWorkbenchService,
    PendingCandidatesError,
)
from src.literature_review.workbench.evidence_service import (
    EvidenceWorkbenchService,
)
from src.literature_review.workbench.export_service import ExportWorkbenchService
from src.literature_review.workbench.run_service import (
    RunDeletionConflictError,
    RunDeletionRollbackError,
    RunNotDeletableError,
    RunWorkbenchService,
)


class WorkbenchService:
    """Compatibility facade for the Workbench application services."""

    def __init__(
        self,
        store: SQLiteWorkflowStore,
        *,
        cancel: Callable[[str], ResearchRun] | None = None,
        artifact_root: Path | None = None,
        deletion_manager: ArtifactDeletionManager | None = None,
    ) -> None:
        self.store = store
        self._runs = RunWorkbenchService(
            store,
            cancel=cancel,
            artifact_root=artifact_root,
            deletion_manager=deletion_manager,
        )
        self.artifact_root = self._runs.artifact_root
        self._discovery = DiscoveryWorkbenchService(store, self._runs.activity)
        self._evidence = EvidenceWorkbenchService(
            store,
            self.artifact_root,
            self._runs.activity,
            self._runs.evidence_presenter,
        )
        self._exports = ExportWorkbenchService(store, self.artifact_root)

    def list_runs(self) -> list[dict[str, object]]:
        return self._runs.list_runs()

    def get_run_detail(self, run_id: str) -> dict[str, object]:
        return self._runs.get_run_detail(run_id)

    def decide_evidence(
        self,
        run_id: str,
        claim_id: str,
        action: str,
        reason: str,
    ) -> dict[str, object]:
        return self._evidence.decide(run_id, claim_id, action, reason)

    def import_pdf(
        self,
        run_id: str,
        citation_key: str,
        pdf_path: str,
    ) -> dict[str, object]:
        return self._evidence.import_pdf(run_id, citation_key, pdf_path)

    def export_run(
        self,
        run_id: str,
        *,
        include_pdfs: bool = True,
    ) -> dict[str, object]:
        return self._exports.export_run(run_id, include_pdfs=include_pdfs)

    def list_candidates(
        self,
        run_id: str,
        status: CandidateStatus | None = None,
    ) -> list[dict[str, object]]:
        return self._discovery.list_candidates(run_id, status)

    def approve_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
        category: str,
        contribution: str,
        tags: Iterable[str],
    ) -> dict[str, object]:
        return self._discovery.approve_candidate(
            run_id,
            candidate_id,
            reason,
            category,
            contribution,
            tags,
        )

    def reject_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
    ) -> dict[str, object]:
        return self._discovery.reject_candidate(run_id, candidate_id, reason)

    def defer_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
    ) -> dict[str, object]:
        return self._discovery.defer_candidate(run_id, candidate_id, reason)

    def close_discovery(self, run_id: str) -> dict[str, object]:
        return self._discovery.close_discovery(run_id)

    def cancel_run(self, run_id: str) -> dict[str, object]:
        return self._runs.cancel_run(run_id)

    def delete_run(self, run_id: str) -> dict[str, object]:
        return self._runs.delete_run(run_id)


__all__ = [
    "PendingCandidatesError",
    "RunDeletionConflictError",
    "RunDeletionRollbackError",
    "RunNotDeletableError",
    "WorkbenchService",
]
