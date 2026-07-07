from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
import shlex

from src.literature_review.activity import ActivityCoordinator
from src.literature_review.discovery import ApprovalService
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    CorpusDecision,
    ResearchRun,
    RunStatus,
)
from src.literature_review.storage import (
    LocalArtifactStore,
    RunNotFoundError,
    RunStatusMismatchError,
    SQLiteWorkflowStore,
)
from src.literature_review.workbench.deletion import ArtifactDeletionManager


class PendingCandidatesError(RuntimeError):
    def __init__(self, run_id: str, pending_count: int) -> None:
        self.run_id = run_id
        self.pending_count = pending_count
        super().__init__(
            f"cannot close discovery while {pending_count} candidates remain pending"
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
        super().__init__(
            f"failed to delete run {run_id} and restore its artifacts"
        )


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


class WorkbenchService:
    _COMMAND_PREFIX = ("python3", "-m", "src.memory_review_pipeline")
    _DELETABLE_STATUSES = frozenset(
        {
            RunStatus.CANCELLED,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        }
    )
    _MODEL_BACKED_AGENT_IDS = (
        "writer",
        "domain_expert",
        "structure_mentor",
        "review_synthesizer",
        "polish",
        "evaluation_reflection",
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
        self.approval_service = ApprovalService(store)
        self._cancel = cancel
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
            self._deletion_manager = deletion_manager
        else:
            configured_root = (
                Path(".review-workflow/artifacts")
                if artifact_root is None
                else Path(artifact_root)
            )
            self.artifact_root = configured_root.expanduser().resolve()
            self._deletion_manager = ArtifactDeletionManager(self.artifact_root)
        self._activity = ActivityCoordinator.for_artifact_root(self.artifact_root)

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
        events = self.store.list_events(run_id)
        return {
            "run": run.to_dict(),
            "candidate_counts": self._candidate_counts(candidates),
            "events": [event.to_dict() for event in events],
            "candidates": [candidate.to_dict() for candidate in candidates],
            "runtime": self._runtime_state(run, events),
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
                f"--reason={reason}",
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
                f"--reason={reason}",
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

    def delete_run(self, run_id: str) -> dict[str, object]:
        with self._activity.reserve_deletion(run_id):
            return self._delete_run(run_id)

    def _delete_run(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        if run.status not in self._DELETABLE_STATUSES:
            raise RunNotDeletableError(run_id, run.status)

        handle = self._deletion_manager.quarantine(run_id)
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
                if delete_error.actual_status in self._DELETABLE_STATUSES:
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
            "equivalent_command": self._equivalent_delete_command(run_id),
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

    def _equivalent_delete_command(self, run_id: str) -> str:
        return self._equivalent_command(
            f"--db={self.store.path.expanduser().resolve()}",
            f"--artifacts={self.artifact_root}",
            "delete",
            run_id,
        )

    def _runtime_state(
        self,
        run: ResearchRun,
        events: Iterable[object],
    ) -> dict[str, object]:
        config = self._stored_runtime_config(run.run_id)
        agent_settings = config.get("agent_settings", {})
        if not isinstance(agent_settings, dict):
            agent_settings = {}
        backend = str(
            config.get("active_backend")
            or config.get("backend")
            or "deterministic"
        )
        if backend not in {"deterministic", "api"}:
            backend = "deterministic"
        api_mode = str(config.get("api_mode") or "single")
        if api_mode not in {"single", "multi"}:
            api_mode = "single"

        api_enabled_agents = []
        model_names = []
        for agent_id in self._MODEL_BACKED_AGENT_IDS:
            settings = agent_settings.get(agent_id, {})
            if not isinstance(settings, dict):
                continue
            if settings.get("active_backend") == "api":
                api_enabled_agents.append(agent_id)
                model = settings.get("model")
                if isinstance(model, str) and model and model not in model_names:
                    model_names.append(model)
        if backend != "api":
            model_summary = "deterministic"
            model_names = []
            api_enabled_agents = []
        elif len(model_names) == 1:
            model_summary = "single_model"
        elif len(model_names) > 1:
            model_summary = "multiple_models"
        else:
            model_summary = "api_configured"

        return {
            "backend": backend,
            "api_mode": api_mode,
            "model_summary": model_summary,
            "model_names": model_names,
            "api_enabled_agents": api_enabled_agents,
            "current_executor": self._current_executor(run, backend),
            "safe_error_category": self._safe_error_category(events),
        }

    def _stored_runtime_config(self, run_id: str) -> dict[str, object]:
        artifact_store = LocalArtifactStore(self.artifact_root)
        try:
            request = artifact_store.read_json(
                run_id,
                "inputs/research_request.json",
            )
        except Exception:
            return {}
        if not isinstance(request, dict):
            return {}
        config = request.get("runtime_config", {})
        return config if isinstance(config, dict) else {}

    @staticmethod
    def _current_executor(run: ResearchRun, backend: str) -> str:
        stage = run.current_stage.value
        mapping = {
            "created": "workflow_planner",
            "planning": "workflow_planner",
            "discovering": "literature_discovery",
            "screening": "screening_agent",
            "awaiting_corpus_approval": "human_approval",
            "completed": "completed",
        }
        agent_loop_stages = {
            "drafting",
            "reviewing",
            "revising",
            "polishing",
            "final_verification",
        }
        if stage in agent_loop_stages:
            if backend == "api":
                return "model_agent_loop"
            return "deterministic_agent_loop"
        return mapping.get(stage, "workflow_engine")

    @staticmethod
    def _safe_error_category(events: Iterable[object]) -> str | None:
        for event in reversed(list(events)):
            event_type = getattr(event, "event_type", "")
            payload = getattr(event, "payload", {})
            message = ""
            if isinstance(payload, Mapping):
                message = str(payload.get("message", ""))
            if event_type == "stage_retry_wait":
                if message.startswith("API provider retryable failure"):
                    return "retryable_api_failure"
                return "retryable_workflow_failure"
            if event_type == "stage_failed":
                if message.startswith("API provider permanent failure"):
                    return "permanent_api_failure"
                return "workflow_failure"
        return None

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


__all__ = [
    "PendingCandidatesError",
    "RunDeletionConflictError",
    "RunDeletionRollbackError",
    "RunNotDeletableError",
    "WorkbenchService",
]
