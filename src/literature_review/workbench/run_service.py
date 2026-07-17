from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from src.literature_review.activity import ActivityCoordinator
from src.literature_review.models import ResearchRun, RunStatus
from src.literature_review.storage import (
    RunNotFoundError,
    RunStatusMismatchError,
    SQLiteWorkflowStore,
)
from src.literature_review.workbench.commands import (
    equivalent_command,
    scoped_command_arguments,
)
from src.literature_review.workbench.deletion import ArtifactDeletionManager
from src.literature_review.workbench.diagnostics import (
    DiscoveryDiagnostics,
    RuntimeDiagnostics,
)
from src.literature_review.workbench.presenters import (
    EvidencePresenter,
    OutputPresenter,
    candidate_counts,
    serialize_candidate_counts,
)


class RunNotDeletableError(RuntimeError):
    def __init__(self, run_id: str, status: RunStatus) -> None:
        self.run_id = run_id
        self.status = status
        super().__init__(f"run {run_id} cannot be deleted while {status.value}")


class RunDeletionRollbackError(RuntimeError):
    def __init__(
        self,
        run_id: str,
        delete_error: Exception,
        restore_error: Exception,
    ) -> None:
        self.run_id = run_id
        self.delete_error = delete_error
        self.restore_error = restore_error
        super().__init__(f"failed to delete run {run_id} and restore its artifacts")


class RunDeletionConflictError(RuntimeError):
    def __init__(
        self,
        run_id: str,
        expected_status: RunStatus,
        actual_status: RunStatus,
    ) -> None:
        self.run_id = run_id
        self.expected_status = expected_status
        self.actual_status = actual_status
        super().__init__(
            f"run {run_id} changed from {expected_status.value} "
            f"to {actual_status.value} during deletion"
        )


class RunWorkbenchService:
    DELETABLE_STATUSES = frozenset(
        {
            RunStatus.CANCELLED,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        }
    )

    def __init__(
        self,
        store: SQLiteWorkflowStore,
        *,
        cancel: Callable[[str], ResearchRun] | None = None,
        artifact_root: Path | None = None,
        deletion_manager: ArtifactDeletionManager | None = None,
    ) -> None:
        self.store = store
        self.cancel_callback = cancel
        if deletion_manager is not None:
            manager_root = Path(deletion_manager.artifact_root).expanduser().resolve()
            if (
                artifact_root is not None
                and Path(artifact_root).expanduser().resolve() != manager_root
            ):
                raise ValueError(
                    "artifact root must match the deletion manager artifact root"
                )
            self.artifact_root = manager_root
            self.deletion_manager = deletion_manager
        else:
            configured_root = (
                Path(".review-workflow/artifacts")
                if artifact_root is None
                else Path(artifact_root)
            )
            self.artifact_root = configured_root.expanduser().resolve()
            self.deletion_manager = ArtifactDeletionManager(self.artifact_root)
        self.activity = ActivityCoordinator.for_artifact_root(self.artifact_root)
        self.evidence_presenter = EvidencePresenter(store)
        self.output_presenter = OutputPresenter(self.artifact_root)
        self.runtime_diagnostics = RuntimeDiagnostics(self.artifact_root)
        self.discovery_diagnostics = DiscoveryDiagnostics(self.runtime_diagnostics)

    def list_runs(self) -> list[dict[str, object]]:
        stored_counts = self.store.list_candidate_counts_by_run()
        result: list[dict[str, object]] = []
        for run in self.store.list_runs():
            serialized: dict[str, object] = run.to_dict()
            serialized["candidate_counts"] = serialize_candidate_counts(
                stored_counts.get(run.run_id, {})
            )
            result.append(serialized)
        return result

    def get_run_detail(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        candidates = self.store.list_candidates(run_id)
        events = self.store.list_events(run_id)
        attempts = self.store.list_discovery_attempts(run_id)
        detail: dict[str, object] = {
            "run": run.to_dict(),
            "candidate_counts": candidate_counts(candidates),
            "events": [event.to_dict() for event in events],
            "discovery_attempts": [attempt.to_dict() for attempt in attempts],
            "candidates": [candidate.to_dict() for candidate in candidates],
            "runtime": self.runtime_diagnostics.summarize(run, events),
            "discovery_summary": self.discovery_diagnostics.summarize(
                run,
                candidates,
                events,
                attempts,
            ),
        }
        evidence = self.evidence_presenter.detail(run_id)
        outputs = self.output_presenter.detail(run_id)
        if evidence["enabled"]:
            detail["evidence"] = evidence
        if outputs["survey_available"]:
            detail["outputs"] = outputs
        return detail

    def cancel_run(self, run_id: str) -> dict[str, object]:
        if self.cancel_callback is None:
            raise RuntimeError("run cancellation is not configured")
        run = self.cancel_callback(run_id)
        return {
            "run": run.to_dict(),
            "equivalent_command": equivalent_command("cancel", run_id),
        }

    def delete_run(self, run_id: str) -> dict[str, object]:
        with self.activity.reserve_deletion(run_id):
            return self._delete_run(run_id)

    def _delete_run(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        if run.status not in self.DELETABLE_STATUSES:
            raise RunNotDeletableError(run_id, run.status)

        handle = self.deletion_manager.quarantine(run_id)
        try:
            self.store.delete_run(run_id, expected_status=run.status)
        except RunNotFoundError:
            pass
        except Exception as delete_error:
            if handle is not None:
                try:
                    handle.restore()
                except Exception as restore_error:
                    raise RunDeletionRollbackError(
                        run_id,
                        delete_error,
                        restore_error,
                    ) from delete_error
            if isinstance(delete_error, RunStatusMismatchError):
                if delete_error.actual_status in self.DELETABLE_STATUSES:
                    raise RunDeletionConflictError(
                        run_id,
                        delete_error.expected_status,
                        delete_error.actual_status,
                    ) from delete_error
                raise RunNotDeletableError(
                    run_id,
                    delete_error.actual_status,
                ) from delete_error
            raise

        cleanup_pending = False
        if handle is not None:
            try:
                handle.purge()
            except Exception:
                cleanup_pending = True

        return {
            "run_id": run_id,
            "status": "deleted",
            "artifacts_removed": handle is not None,
            "cleanup_pending": cleanup_pending,
            "equivalent_command": equivalent_command(
                *scoped_command_arguments(self.store, self.artifact_root),
                "delete",
                run_id,
            ),
        }


__all__ = [
    "RunDeletionConflictError",
    "RunDeletionRollbackError",
    "RunNotDeletableError",
    "RunWorkbenchService",
]
