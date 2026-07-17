from __future__ import annotations

from pathlib import Path

from src.literature_review.activity import ActivityCoordinator
from src.literature_review.documents.service import DocumentImportService
from src.literature_review.models import RunStatus, WorkflowStage
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.verification import (
    EvidenceReviewDecision,
    VerificationStatus,
)
from src.literature_review.workbench.commands import (
    equivalent_command,
    scoped_command_arguments,
)
from src.literature_review.workbench.presenters import EvidencePresenter


class EvidenceWorkbenchService:
    def __init__(
        self,
        store: SQLiteWorkflowStore,
        artifact_root: Path,
        activity: ActivityCoordinator,
        presenter: EvidencePresenter,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root
        self.activity = activity
        self.presenter = presenter

    def decide(
        self,
        run_id: str,
        claim_id: str,
        action: str,
        reason: str,
    ) -> dict[str, object]:
        if not reason.strip():
            raise ValueError("decision reason must be nonblank")
        with self.activity.resume_execution(run_id):
            run = self.store.get_run(run_id)
            if (
                run.status != RunStatus.WAITING
                or run.current_stage != WorkflowStage.AWAITING_EVIDENCE_REVIEW
            ):
                raise ValueError("evidence decisions require the evidence review gate")
            blocking = self.store.list_claim_verifications(
                run_id,
                claim_id=claim_id,
                blocking_only=True,
            )
            if not blocking:
                raise ValueError("claim has no blocking verification result")
            if action == "accept_risk" and any(
                item.status != VerificationStatus.FULL_TEXT_UNAVAILABLE
                for item in blocking
            ):
                raise ValueError("risk acceptance requires unavailable full text")
            decision = EvidenceReviewDecision.create(
                run_id,
                claim_id,
                action,
                reason.strip(),
                "human-workbench",
                verification_fingerprints=tuple(
                    item.fingerprint for item in blocking
                ),
            )
            self.store.put_evidence_review_decision(decision)
        return {
            "decision": decision.to_dict(),
            "evidence": self.presenter.detail(run_id),
            "equivalent_command": equivalent_command(
                "evidence-decide",
                run_id,
                claim_id,
                f"--action={action}",
                f"--reason={reason.strip()}",
            ),
        }

    def import_pdf(
        self,
        run_id: str,
        citation_key: str,
        pdf_path: str,
    ) -> dict[str, object]:
        document = DocumentImportService(
            self.store,
            LocalArtifactStore(self.artifact_root),
        ).import_pdf(run_id, citation_key, Path(pdf_path))
        return {
            "document": document.to_dict(),
            "evidence": self.presenter.detail(run_id),
            "equivalent_command": equivalent_command(
                *scoped_command_arguments(self.store, self.artifact_root),
                "import-pdf",
                run_id,
                citation_key,
                str(Path(pdf_path).expanduser().resolve()),
            ),
        }


__all__ = ["EvidenceWorkbenchService"]
