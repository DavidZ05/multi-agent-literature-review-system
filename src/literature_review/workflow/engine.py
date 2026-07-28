from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from src.literature_review.activity import ActivityCoordinator
from src.literature_review.models import (
    ResearchRun,
    RunStatus,
    StageCheckpoint,
    WorkflowEvent,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.storage import ArtifactRecord, LocalArtifactStore
from src.literature_review.workflow.checkpoints import fingerprint_inputs
from src.literature_review.workflow.state import require_transition


class WorkflowStore(Protocol):
    def initialize(self) -> None: ...

    def create_run(self, run: ResearchRun) -> None: ...

    def get_run(self, run_id: str) -> ResearchRun: ...

    def update_run(self, run: ResearchRun) -> None: ...

    def compare_and_update_run(
        self,
        run: ResearchRun,
        *,
        expected_status: RunStatus,
        expected_stage: WorkflowStage,
    ) -> bool: ...

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        stage: WorkflowStage | None = None,
    ) -> WorkflowEvent: ...

    def put_checkpoint(self, checkpoint: StageCheckpoint) -> None: ...

    def get_checkpoint(
        self,
        run_id: str,
        stage: WorkflowStage,
    ) -> StageCheckpoint | None: ...


@dataclass(frozen=True)
class StageContext:
    run: ResearchRun
    artifact_store: LocalArtifactStore
    workflow_store: WorkflowStore
    corpus_path: Path
    runtime_config: Mapping[str, Any]
    _cancellation_check: Callable[[], bool]

    def is_cancelled(self) -> bool:
        return self._cancellation_check()


@dataclass(frozen=True)
class StageResult:
    next_stage: WorkflowStage
    output_artifacts: Mapping[str, Any]
    waiting_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.next_stage, WorkflowStage):
            raise TypeError("next_stage must be a WorkflowStage")
        object.__setattr__(
            self,
            "output_artifacts",
            MappingProxyType(dict(self.output_artifacts)),
        )


class StageHandler(Protocol):
    def __call__(self, context: StageContext) -> StageResult: ...


class StageExecutionError(RuntimeError):
    pass


class RetryableStageError(RuntimeError):
    pass


class StageWaitingError(RuntimeError):
    pass


class PersistentWorkflowEngine:
    _TERMINAL_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.CANCELLED})

    def __init__(
        self,
        workflow_store: WorkflowStore,
        artifact_store: LocalArtifactStore,
        handlers: Mapping[WorkflowStage, StageHandler],
        *,
        runtime_config: Mapping[str, Any] | None = None,
    ) -> None:
        self.workflow_store = workflow_store
        self.artifact_store = artifact_store
        self.handlers = MappingProxyType(dict(handlers))
        self.runtime_config = MappingProxyType(dict(runtime_config or {}))
        self.activity = ActivityCoordinator.for_artifact_root(
            self.artifact_store.root
        )
        self.workflow_store.initialize()

    def start(
        self,
        topic: str,
        corpus_path: Path,
        *,
        run: ResearchRun | None = None,
    ) -> ResearchRun:
        resolved_corpus = Path(corpus_path).resolve()
        if not resolved_corpus.is_file():
            raise FileNotFoundError(resolved_corpus)
        run = ResearchRun.create(topic) if run is None else run
        if run.topic != topic.strip():
            raise ValueError("prepared run topic does not match start topic")
        if run.status != RunStatus.ACTIVE or run.current_stage != WorkflowStage.CREATED:
            raise ValueError("prepared run must be active at the created stage")
        with self.activity.start_execution():
            with self.activity.resume_execution(run.run_id):
                return self._start(run, resolved_corpus)

    def _start(self, run: ResearchRun, resolved_corpus: Path) -> ResearchRun:
        self.workflow_store.create_run(run)
        request = {
            "topic": run.topic,
            "corpus_path": str(resolved_corpus),
            "runtime_config": dict(self.runtime_config),
        }
        record = self.artifact_store.write_json(
            run.run_id,
            "inputs/research_request.json",
            request,
        )
        self.workflow_store.append_event(
            run.run_id,
            "run_created",
            {
                "topic": run.topic,
                "request_artifact": record.relative_path,
                "request_sha256": record.sha256,
            },
            WorkflowStage.CREATED,
        )
        return self._resume(run.run_id)

    def resume(self, run_id: str) -> ResearchRun:
        with self.activity.resume_execution(run_id):
            return self._resume(run_id)

    def _resume(self, run_id: str) -> ResearchRun:
        run = self.workflow_store.get_run(run_id)
        if run.status in self._TERMINAL_STATUSES:
            return run
        if run.status in {
            RunStatus.PAUSED,
            RunStatus.WAITING,
            RunStatus.FAILED,
            RunStatus.RETRY_WAIT,
        }:
            previous = run
            run = replace(
                run,
                status=RunStatus.ACTIVE,
                updated_at=utc_now_iso(),
            )
            if not self.workflow_store.compare_and_update_run(
                run,
                expected_status=previous.status,
                expected_stage=previous.current_stage,
            ):
                return self.workflow_store.get_run(run_id)
            self.workflow_store.append_event(
                run_id,
                "run_resumed",
                {"stage": run.current_stage.value},
                run.current_stage,
            )
        if run.current_stage == WorkflowStage.CREATED:
            run = self._advance(run, WorkflowStage.PLANNING)

        while run.status == RunStatus.ACTIVE:
            run = self.workflow_store.get_run(run_id)
            if run.status != RunStatus.ACTIVE:
                return run
            if run.current_stage == WorkflowStage.COMPLETED:
                return self._complete(run)

            stage = run.current_stage
            input_fingerprint = self._input_fingerprint(run)
            checkpoint = self.workflow_store.get_checkpoint(run_id, stage)
            if self._checkpoint_is_reusable(checkpoint, input_fingerprint):
                assert checkpoint is not None
                assert checkpoint.next_stage is not None
                self.workflow_store.append_event(
                    run_id,
                    "stage_checkpoint_reused",
                    {"input_fingerprint": input_fingerprint},
                    stage,
                )
                run = self._advance(run, checkpoint.next_stage)
                continue

            handler = self.handlers.get(stage)
            if handler is None:
                error = StageExecutionError(f"no handler registered for {stage.value}")
                self._fail(run, error)
                raise error

            self.workflow_store.append_event(
                run_id,
                "stage_started",
                {"input_fingerprint": input_fingerprint},
                stage,
            )
            context = StageContext(
                run=run,
                artifact_store=self.artifact_store,
                workflow_store=self.workflow_store,
                corpus_path=self._corpus_path(run_id),
                runtime_config=self.runtime_config,
                _cancellation_check=lambda: self._is_cancelled(run_id),
            )
            try:
                result = handler(context)
                require_transition(stage, result.next_stage)
                if self._is_cancelled(run_id):
                    return self.workflow_store.get_run(run_id)
                records = self._write_outputs(run_id, result.output_artifacts)
                if self._is_cancelled(run_id):
                    return self.workflow_store.get_run(run_id)
                checkpoint = StageCheckpoint(
                    run_id=run_id,
                    stage=stage,
                    input_fingerprint=input_fingerprint,
                    output_artifact_hashes={
                        record.relative_path: record.sha256 for record in records
                    },
                    status="completed",
                    created_at=utc_now_iso(),
                    next_stage=result.next_stage,
                )
                self.workflow_store.put_checkpoint(checkpoint)
                if self._is_cancelled(run_id):
                    return self.workflow_store.get_run(run_id)
            except KeyboardInterrupt:
                self.pause(run_id)
                raise
            except RetryableStageError as exc:
                retrying = replace(
                    run,
                    status=RunStatus.RETRY_WAIT,
                    updated_at=utc_now_iso(),
                )
                if not self.workflow_store.compare_and_update_run(
                    retrying,
                    expected_status=run.status,
                    expected_stage=run.current_stage,
                ):
                    return self.workflow_store.get_run(run_id)
                self.workflow_store.append_event(
                    run_id,
                    "stage_retry_wait",
                    {
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    stage,
                )
                return retrying
            except StageWaitingError as exc:
                waiting = replace(
                    run,
                    status=RunStatus.WAITING,
                    updated_at=utc_now_iso(),
                )
                if not self.workflow_store.compare_and_update_run(
                    waiting,
                    expected_status=run.status,
                    expected_stage=run.current_stage,
                ):
                    return self.workflow_store.get_run(run_id)
                self.workflow_store.append_event(
                    run_id,
                    "run_waiting",
                    {"reason": str(exc)},
                    stage,
                )
                return waiting
            except Exception as exc:
                self._fail(run, exc)
                raise StageExecutionError(f"{stage.value} stage failed: {exc}") from exc

            self.workflow_store.append_event(
                run_id,
                "stage_completed",
                {
                    "next_stage": result.next_stage.value,
                    "output_artifacts": [record.relative_path for record in records],
                },
                stage,
            )
            run = self._advance(run, result.next_stage)
            if run.status != RunStatus.ACTIVE:
                return run
            if result.waiting_reason is not None:
                waiting = replace(
                    run,
                    status=RunStatus.WAITING,
                    updated_at=utc_now_iso(),
                )
                if not self.workflow_store.compare_and_update_run(
                    waiting,
                    expected_status=run.status,
                    expected_stage=run.current_stage,
                ):
                    return self.workflow_store.get_run(run_id)
                self.workflow_store.append_event(
                    run_id,
                    "run_waiting",
                    {"reason": result.waiting_reason},
                    waiting.current_stage,
                )
                return waiting

        return run

    def pause(self, run_id: str) -> ResearchRun:
        with self.activity.resume_execution(run_id):
            return self._pause(run_id)

    def _pause(self, run_id: str) -> ResearchRun:
        while True:
            run = self.workflow_store.get_run(run_id)
            if run.status in self._TERMINAL_STATUSES:
                return run
            paused = replace(
                run,
                status=RunStatus.PAUSED,
                updated_at=utc_now_iso(),
            )
            if self.workflow_store.compare_and_update_run(
                paused,
                expected_status=run.status,
                expected_stage=run.current_stage,
            ):
                self.workflow_store.append_event(
                    run_id,
                    "run_paused",
                    {"stage": paused.current_stage.value},
                    paused.current_stage,
                )
                return paused

    def cancel(self, run_id: str) -> ResearchRun:
        return self._cancel(run_id)

    def _cancel(self, run_id: str) -> ResearchRun:
        while True:
            run = self.workflow_store.get_run(run_id)
            if run.status in self._TERMINAL_STATUSES:
                return run
            cancelled = replace(
                run,
                status=RunStatus.CANCELLED,
                updated_at=utc_now_iso(),
            )
            if self.workflow_store.compare_and_update_run(
                cancelled,
                expected_status=run.status,
                expected_stage=run.current_stage,
            ):
                self.workflow_store.append_event(
                    run_id,
                    "run_cancelled",
                    {"stage": cancelled.current_stage.value},
                    cancelled.current_stage,
                )
                return cancelled

    def _advance(
        self,
        run: ResearchRun,
        next_stage: WorkflowStage,
    ) -> ResearchRun:
        require_transition(run.current_stage, next_stage)
        evidence_revision_requested = (
            run.current_stage == WorkflowStage.AWAITING_EVIDENCE_REVIEW
            and next_stage == WorkflowStage.DRAFTING
        )
        advanced = replace(
            run,
            current_stage=next_stage,
            # Writer's inner loop is counted separately in revision_log.json.
            revision_count=run.revision_count + int(evidence_revision_requested),
            updated_at=utc_now_iso(),
        )
        if not self.workflow_store.compare_and_update_run(
            advanced,
            expected_status=run.status,
            expected_stage=run.current_stage,
        ):
            return self.workflow_store.get_run(run.run_id)
        transition_payload: dict[str, object] = {
            "from_stage": run.current_stage.value,
            "to_stage": next_stage.value,
        }
        if evidence_revision_requested:
            transition_payload["revision_count"] = advanced.revision_count
        self.workflow_store.append_event(
            run.run_id,
            "stage_transition",
            transition_payload,
            next_stage,
        )
        if next_stage == WorkflowStage.COMPLETED:
            return self._complete(advanced)
        return advanced

    def _complete(self, run: ResearchRun) -> ResearchRun:
        if run.status == RunStatus.COMPLETED:
            return run
        completed = replace(
            run,
            status=RunStatus.COMPLETED,
            current_stage=WorkflowStage.COMPLETED,
            updated_at=utc_now_iso(),
        )
        if not self.workflow_store.compare_and_update_run(
            completed,
            expected_status=run.status,
            expected_stage=run.current_stage,
        ):
            return self.workflow_store.get_run(run.run_id)
        self.workflow_store.append_event(
            run.run_id,
            "run_completed",
            {},
            WorkflowStage.COMPLETED,
        )
        return completed

    def _fail(self, run: ResearchRun, error: BaseException) -> ResearchRun:
        while True:
            latest = self.workflow_store.get_run(run.run_id)
            if latest.status == RunStatus.CANCELLED:
                return latest
            failed = replace(
                latest,
                status=RunStatus.FAILED,
                updated_at=utc_now_iso(),
            )
            if self.workflow_store.compare_and_update_run(
                failed,
                expected_status=latest.status,
                expected_stage=latest.current_stage,
            ):
                self.workflow_store.append_event(
                    run.run_id,
                    "stage_failed",
                    {
                        "error_type": type(error).__name__,
                        "message": str(error),
                    },
                    latest.current_stage,
                )
                return failed

    def _request(self, run_id: str) -> dict[str, Any]:
        request = self.artifact_store.read_json(run_id, "inputs/research_request.json")
        if not isinstance(request, dict):
            raise TypeError("research request artifact must contain an object")
        return request

    def _corpus_path(self, run_id: str) -> Path:
        return Path(self._request(run_id)["corpus_path"])

    def _input_fingerprint(self, run: ResearchRun) -> str:
        corpus_path = self._corpus_path(run.run_id)
        upstream_hashes: dict[str, dict[str, str]] = {}
        stage_order = list(WorkflowStage)
        current_index = stage_order.index(run.current_stage)
        for stage in stage_order[:current_index]:
            checkpoint = self.workflow_store.get_checkpoint(run.run_id, stage)
            if checkpoint is not None and checkpoint.status == "completed":
                upstream_hashes[stage.value] = dict(checkpoint.output_artifact_hashes)
        return fingerprint_inputs(
            {
                "stage": run.current_stage.value,
                "topic": run.topic,
                "corpus_version": run.corpus_version,
                "revision_count": run.revision_count,
                "corpus_sha256": self._hash_path(corpus_path),
                "runtime_config": dict(self.runtime_config),
                "upstream_artifact_hashes": upstream_hashes,
                "control_artifact_hashes": self._control_artifact_hashes(run),
            }
        )

    def _control_artifact_hashes(self, run: ResearchRun) -> dict[str, str]:
        paths = ()
        if run.current_stage == WorkflowStage.DRAFTING:
            paths = ("evidence/revision_feedback.json",)
        return {
            path: self.artifact_store.hash_file(run.run_id, path)
            for path in paths
            if self.artifact_store.exists(run.run_id, path)
        }

    def _checkpoint_is_reusable(
        self,
        checkpoint: StageCheckpoint | None,
        input_fingerprint: str,
    ) -> bool:
        if (
            checkpoint is None
            or checkpoint.status != "completed"
            or checkpoint.next_stage is None
            or checkpoint.input_fingerprint != input_fingerprint
        ):
            return False
        return all(
            self.artifact_store.exists(checkpoint.run_id, path)
            and self.artifact_store.hash_file(checkpoint.run_id, path) == expected_hash
            for path, expected_hash in checkpoint.output_artifact_hashes.items()
        )

    def _write_outputs(
        self,
        run_id: str,
        outputs: Mapping[str, Any],
    ) -> list[ArtifactRecord]:
        records = []
        for relative_path, content in outputs.items():
            if isinstance(content, str):
                record = self.artifact_store.write_text(run_id, relative_path, content)
            elif isinstance(content, bytes):
                record = self.artifact_store.write_bytes(run_id, relative_path, content)
            else:
                record = self.artifact_store.write_json(run_id, relative_path, content)
            records.append(record)
        return records

    def _is_cancelled(self, run_id: str) -> bool:
        return self.workflow_store.get_run(run_id).status == RunStatus.CANCELLED

    @staticmethod
    def _hash_path(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


__all__ = [
    "PersistentWorkflowEngine",
    "RetryableStageError",
    "StageWaitingError",
    "StageContext",
    "StageExecutionError",
    "StageHandler",
    "StageResult",
    "WorkflowStore",
]
