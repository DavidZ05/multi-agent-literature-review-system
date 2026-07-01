from __future__ import annotations

from collections.abc import Iterable

from src.literature_review.models import CandidatePaper, CandidateStatus
from src.literature_review.storage import SQLiteWorkflowStore


class WorkbenchService:
    def __init__(self, store: SQLiteWorkflowStore) -> None:
        self.store = store

    def list_runs(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for run in self.store.list_runs():
            candidates = self.store.list_candidates(run.run_id)
            serialized: dict[str, object] = run.to_dict()
            serialized["candidate_counts"] = self._candidate_counts(candidates)
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

    @staticmethod
    def _candidate_counts(
        candidates: Iterable[CandidatePaper],
    ) -> dict[str, int]:
        counts = {status.value: 0 for status in CandidateStatus}
        for candidate in candidates:
            counts[candidate.status.value] += 1
        return counts


__all__ = ["WorkbenchService"]
