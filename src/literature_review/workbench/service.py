from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import shlex

from src.literature_review.discovery import ApprovalService
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    CorpusDecision,
    ResearchRun,
)
from src.literature_review.storage import SQLiteWorkflowStore


class PendingCandidatesError(RuntimeError):
    def __init__(self, run_id: str, pending_count: int) -> None:
        self.run_id = run_id
        self.pending_count = pending_count
        super().__init__(
            f"cannot close discovery while {pending_count} candidates remain pending"
        )


class WorkbenchService:
    _COMMAND_PREFIX = ("python3", "-m", "src.memory_review_pipeline")

    def __init__(
        self,
        store: SQLiteWorkflowStore,
        *,
        cancel: Callable[[str], ResearchRun] | None = None,
    ) -> None:
        self.store = store
        self.approval_service = ApprovalService(store)
        self._cancel = cancel

    def list_runs(self) -> list[dict[str, object]]:
        candidate_counts = self.store.list_candidate_counts_by_run()
        result: list[dict[str, object]] = []
        for run in self.store.list_runs():
            serialized: dict[str, object] = run.to_dict()
            serialized["candidate_counts"] = self._serialize_candidate_counts(
                candidate_counts.get(run.run_id, {})
            )
            result.append(serialized)
        return result

    def get_run_detail(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        candidates = self.store.list_candidates(run_id)
        return {
            "run": run.to_dict(),
            "candidate_counts": self._candidate_counts(candidates),
            "events": [event.to_dict() for event in self.store.list_events(run_id)],
            "candidates": [candidate.to_dict() for candidate in candidates],
        }

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
            self._equivalent_command(
                "approve",
                run_id,
                candidate_id,
                "--reason",
                reason,
                "--category",
                category,
                "--contribution",
                contribution,
                "--tags",
                *tag_values,
            ),
        )

    def reject_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
    ) -> dict[str, object]:
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
            self._equivalent_command(
                "reject",
                run_id,
                candidate_id,
                "--reason",
                reason,
            ),
        )

    def defer_candidate(
        self,
        run_id: str,
        candidate_id: str,
        reason: str,
    ) -> dict[str, object]:
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
            self._equivalent_command(
                "defer",
                run_id,
                candidate_id,
                "--reason",
                reason,
            ),
        )

    def close_discovery(self, run_id: str) -> dict[str, object]:
        pending_count = len(
            self.store.list_candidates(run_id, status=CandidateStatus.PENDING)
        )
        if pending_count:
            raise PendingCandidatesError(run_id, pending_count)
        return {
            "run_id": run_id,
            "status": "ready_to_resume",
            "equivalent_command": self._equivalent_command(
                "close-discovery",
                run_id,
            ),
        }

    def cancel_run(self, run_id: str) -> dict[str, object]:
        if self._cancel is None:
            raise RuntimeError("run cancellation is not configured")
        run = self._cancel(run_id)
        return {
            "run": run.to_dict(),
            "equivalent_command": self._equivalent_command("cancel", run_id),
        }

    def _decision_payload(
        self,
        run_id: str,
        candidate_id: str,
        decision: CorpusDecision,
        equivalent_command: str,
    ) -> dict[str, object]:
        return {
            "candidate": self.store.get_candidate(run_id, candidate_id).to_dict(),
            "decision": decision.to_dict(),
            "equivalent_command": equivalent_command,
        }

    @classmethod
    def _equivalent_command(cls, *arguments: str) -> str:
        return shlex.join([*cls._COMMAND_PREFIX, *arguments])

    @staticmethod
    def _candidate_counts(
        candidates: Iterable[CandidatePaper],
    ) -> dict[str, int]:
        counts = {status: 0 for status in CandidateStatus}
        for candidate in candidates:
            counts[candidate.status] += 1
        return WorkbenchService._serialize_candidate_counts(counts)

    @staticmethod
    def _serialize_candidate_counts(
        counts: Mapping[CandidateStatus, int],
    ) -> dict[str, int]:
        return {status.value: counts.get(status, 0) for status in CandidateStatus}


__all__ = ["PendingCandidatesError", "WorkbenchService"]
