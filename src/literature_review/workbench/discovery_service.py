from __future__ import annotations

from collections.abc import Iterable

from src.literature_review.activity import ActivityCoordinator
from src.literature_review.discovery import ApprovalService
from src.literature_review.models import CandidateStatus, CorpusDecision
from src.literature_review.storage import SQLiteWorkflowStore
from src.literature_review.workbench.commands import equivalent_command


class PendingCandidatesError(RuntimeError):
    def __init__(self, run_id: str, pending_count: int) -> None:
        self.run_id = run_id
        self.pending_count = pending_count
        super().__init__(
            f"cannot close discovery while {pending_count} candidates remain pending"
        )


class DiscoveryWorkbenchService:
    def __init__(
        self,
        store: SQLiteWorkflowStore,
        activity: ActivityCoordinator,
    ) -> None:
        self.store = store
        self.activity = activity
        self.approval_service = ApprovalService(store)

    def list_candidates(
        self,
        run_id: str,
        status: CandidateStatus | None = None,
    ) -> list[dict[str, object]]:
        return [
            candidate.to_dict()
            for candidate in self.store.list_candidates(run_id, status=status)
        ]

    def approve_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
        category: str,
        contribution: str,
        tags: Iterable[str],
    ) -> dict[str, object]:
        tag_values = tuple(tags)
        with self.activity.resume_execution(run_id):
            decision = self.approval_service.approve(
                run_id,
                candidate_id,
                reason=reason,
                category=category,
                contribution=contribution,
                tags=tag_values,
                actor="workbench",
            )
        return self._decision_payload(
            run_id,
            candidate_id,
            decision,
            equivalent_command(
                "approve",
                run_id,
                candidate_id,
                f"--reason={reason}",
                f"--category={category}",
                f"--contribution={contribution}",
                *(f"--tags={tag}" for tag in tag_values),
            ),
        )

    def reject_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
    ) -> dict[str, object]:
        with self.activity.resume_execution(run_id):
            decision = self.approval_service.reject(
                run_id,
                candidate_id,
                reason=reason,
                actor="workbench",
            )
        return self._decision_payload(
            run_id,
            candidate_id,
            decision,
            equivalent_command(
                "reject",
                run_id,
                candidate_id,
                f"--reason={reason}",
            ),
        )

    def defer_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
    ) -> dict[str, object]:
        with self.activity.resume_execution(run_id):
            decision = self.approval_service.defer(
                run_id,
                candidate_id,
                reason=reason,
                actor="workbench",
            )
        return self._decision_payload(
            run_id,
            candidate_id,
            decision,
            equivalent_command(
                "defer",
                run_id,
                candidate_id,
                f"--reason={reason}",
            ),
        )

    def close_discovery(self, run_id: str) -> dict[str, object]:
        with self.activity.resume_execution(run_id):
            pending_count = len(
                self.store.list_candidates(
                    run_id,
                    status=CandidateStatus.PENDING,
                )
            )
            if pending_count:
                raise PendingCandidatesError(run_id, pending_count)
        return {
            "run_id": run_id,
            "status": "ready_to_resume",
            "equivalent_command": equivalent_command("close-discovery", run_id),
        }

    def _decision_payload(
        self,
        run_id: str,
        candidate_id: str,
        decision: CorpusDecision,
        command: str,
    ) -> dict[str, object]:
        return {
            "candidate": self.store.get_candidate(run_id, candidate_id).to_dict(),
            "decision": decision.to_dict(),
            "equivalent_command": command,
        }


__all__ = ["DiscoveryWorkbenchService", "PendingCandidatesError"]
