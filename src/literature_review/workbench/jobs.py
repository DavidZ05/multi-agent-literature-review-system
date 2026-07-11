from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import CancelledError, Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
import logging
from pathlib import Path
import shlex
import threading
from typing import Any, Protocol
from uuid import uuid4

from src.literature_review.activity import (
    ActivityCoordinator,
    ActivityReservation,
)
from src.literature_review.models import CandidateStatus, ResearchRun, WorkflowStage
from src.literature_review.runtime import build_engine, load_resume_settings
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.workbench.service import PendingCandidatesError


_ALLOWED_PROVIDERS = frozenset({"arxiv", "semantic_scholar"})
_COMMAND_PREFIX = ("python3", "-m", "src.memory_review_pipeline")
_LOGGER = logging.getLogger(__name__)


class WorkflowEngine(Protocol):
    def start(self, topic: str, corpus_path: Path) -> ResearchRun: ...

    def resume(self, run_id: str) -> ResearchRun: ...


EngineBuilder = Callable[..., WorkflowEngine]
ResumeSettingsLoader = Callable[
    [LocalArtifactStore, str],
    tuple[bool, tuple[str, ...], int],
]


@dataclass(frozen=True)
class StartRunRequest:
    topic: str
    corpus_path: Path
    discovery_enabled: bool = False
    providers: tuple[str, ...] = ("arxiv", "semantic_scholar")
    max_results: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.topic, str):
            raise TypeError("topic must be a string")
        topic = self.topic.strip()
        if not topic:
            raise ValueError("topic must be nonblank")

        corpus_path = Path(self.corpus_path).expanduser().resolve()
        if not corpus_path.is_file():
            raise ValueError("corpus_path must be an existing file")
        if not isinstance(self.discovery_enabled, bool):
            raise TypeError("discovery_enabled must be a boolean")

        providers = self._normalize_providers(self.providers)
        unknown = set(providers) - _ALLOWED_PROVIDERS
        if unknown:
            raise ValueError(f"unknown provider: {sorted(unknown)[0]}")
        if self.discovery_enabled and not providers:
            raise ValueError("providers must be nonempty when discovery is enabled")

        if isinstance(self.max_results, bool) or not isinstance(self.max_results, int):
            raise TypeError("max_results must be an integer")
        if not 1 <= self.max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")

        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "corpus_path", corpus_path)
        object.__setattr__(self, "providers", providers)

    @staticmethod
    def _normalize_providers(providers: Iterable[str]) -> tuple[str, ...]:
        if isinstance(providers, str):
            raise TypeError("providers must be an iterable of provider names")
        normalized: list[str] = []
        for provider in providers:
            if not isinstance(provider, str):
                raise TypeError("providers must contain strings")
            value = provider.strip().lower()
            if value not in normalized:
                normalized.append(value)
        return tuple(normalized)


class DuplicateResumeJobError(RuntimeError):
    def __init__(self, run_id: str, existing_job_id: str) -> None:
        self.run_id = run_id
        self.existing_job_id = existing_job_id
        super().__init__(
            f"resume job {existing_job_id} is already active for run {run_id}"
        )


class JobNotFoundError(KeyError):
    pass


@dataclass
class _JobRecord:
    job_id: str
    kind: str
    status: str
    equivalent_command: str
    run_id: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    reservation: ActivityReservation | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "run_id": self.run_id,
            "equivalent_command": self.equivalent_command,
            "result": None if self.result is None else dict(self.result),
            "error": None if self.error is None else dict(self.error),
        }


class WorkflowJobManager:
    def __init__(
        self,
        store: SQLiteWorkflowStore,
        artifact_root: Path,
        *,
        engine_builder: EngineBuilder = build_engine,
        resume_settings_loader: ResumeSettingsLoader = load_resume_settings,
        executor: Executor | None = None,
        max_workers: int = 2,
        max_retained_jobs: int = 200,
    ) -> None:
        if isinstance(max_retained_jobs, bool) or max_retained_jobs < 1:
            raise ValueError("max_retained_jobs must be a positive integer")
        self.store = store
        self.store.path = self.store.path.expanduser().resolve()
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self._engine_builder = engine_builder
        self._resume_settings_loader = resume_settings_loader
        self._activity = ActivityCoordinator.for_artifact_root(self.artifact_root)
        self._executor = (
            executor
            if executor is not None
            else ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="workflow-job",
            )
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, _JobRecord] = {}
        self._active_resume_jobs: dict[str, str] = {}
        self._futures: set[Future[Any]] = set()
        self._max_retained_jobs = max_retained_jobs

    def submit_start(self, request: StartRunRequest) -> dict[str, object]:
        if not isinstance(request, StartRunRequest):
            raise TypeError("request must be a StartRunRequest")
        request = StartRunRequest(
            topic=request.topic,
            corpus_path=request.corpus_path,
            discovery_enabled=request.discovery_enabled,
            providers=request.providers,
            max_results=request.max_results,
        )
        reservation = self._activity.reserve_start()
        try:
            command = self._start_command(request)
            job = self._new_job("start", command, reservation=reservation)
            self._schedule(
                job,
                lambda: self._engine_builder(
                    self.store,
                    self.artifact_root,
                    discovery_enabled=request.discovery_enabled,
                    providers=request.providers,
                    max_results=request.max_results,
                ).start(request.topic, request.corpus_path),
            )
        except BaseException:
            reservation.release()
            raise
        return self._accepted_payload(job)

    def submit_resume(self, run_id: str) -> dict[str, object]:
        with self._lock:
            existing_job_id = self._active_resume_jobs.get(run_id)
        if existing_job_id is not None:
            raise DuplicateResumeJobError(run_id, existing_job_id)

        reservation = self._activity.reserve_resume(run_id)
        try:
            run = self.store.get_run(run_id)
            if run.current_stage == WorkflowStage.AWAITING_CORPUS_APPROVAL:
                pending_count = len(
                    self.store.list_candidates(
                        run_id,
                        status=CandidateStatus.PENDING,
                    )
                )
                if pending_count:
                    raise PendingCandidatesError(run_id, pending_count)
            command = self._equivalent_command("resume", run_id)
            job = self._new_job(
                "resume",
                command,
                run_id=run_id,
                reservation=reservation,
            )
            self._schedule(job, lambda: self._resume(run_id))
        except BaseException:
            reservation.release()
            raise
        return self._accepted_payload(job)

    def get_job(self, job_id: str) -> dict[str, object]:
        with self._lock:
            try:
                return self._jobs[job_id].to_dict()
            except KeyError as exc:
                raise JobNotFoundError(job_id) from exc

    def list_jobs(self, *, active_only: bool = False) -> list[dict[str, object]]:
        with self._lock:
            jobs = list(self._jobs.values())
            if active_only:
                jobs = [job for job in jobs if job.status in {"queued", "running"}]
            return [job.to_dict() for job in jobs]

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def _resume(self, run_id: str) -> ResearchRun:
        artifact_store = LocalArtifactStore(self.artifact_root)
        enabled, providers, max_results = self._resume_settings_loader(
            artifact_store,
            run_id,
        )
        engine = self._engine_builder(
            self.store,
            self.artifact_root,
            discovery_enabled=enabled,
            providers=providers,
            max_results=max_results,
        )
        return engine.resume(run_id)

    def _new_job(
        self,
        kind: str,
        equivalent_command: str,
        *,
        run_id: str | None = None,
        reservation: ActivityReservation | None = None,
    ) -> _JobRecord:
        with self._lock:
            if run_id is not None:
                existing_job_id = self._active_resume_jobs.get(run_id)
                if existing_job_id is not None:
                    raise DuplicateResumeJobError(run_id, existing_job_id)
            job = _JobRecord(
                job_id=f"job_{uuid4().hex}",
                kind=kind,
                status="queued",
                equivalent_command=equivalent_command,
                run_id=run_id,
                reservation=reservation,
            )
            self._jobs[job.job_id] = job
            if run_id is not None:
                self._active_resume_jobs[run_id] = job.job_id
            return job

    def _schedule(
        self,
        job: _JobRecord,
        operation: Callable[[], ResearchRun],
    ) -> None:
        try:
            future = self._executor.submit(self._run_job, job.job_id, operation)
        except BaseException:
            with self._lock:
                self._jobs.pop(job.job_id, None)
                if job.run_id is not None:
                    self._active_resume_jobs.pop(job.run_id, None)
                if job.reservation is not None:
                    job.reservation.release()
            raise
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(
            lambda completed: self._observe_future(job.job_id, completed)
        )

    def _run_job(
        self,
        job_id: str,
        operation: Callable[[], ResearchRun],
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
        try:
            if job.reservation is None:
                result = operation().to_dict()
            else:
                with job.reservation.activate():
                    result = operation().to_dict()
        except BaseException as exc:
            with self._lock:
                job.status = "failed"
                job.error = self._public_error(exc)
            _LOGGER.exception("Workflow job %s failed", job_id)
            if not isinstance(exc, Exception):
                raise
        else:
            with self._lock:
                job.status = "succeeded"
                job.result = result
        finally:
            with self._lock:
                self._release_job(job)

    def _observe_future(
        self,
        job_id: str,
        future: Future[Any],
    ) -> None:
        try:
            failure = future.exception()
        except CancelledError as exc:
            failure = exc
        finally:
            with self._lock:
                self._futures.discard(future)

        if failure is None:
            return
        _LOGGER.error(
            "Workflow job %s worker terminated",
            job_id,
            exc_info=(type(failure), failure, failure.__traceback__),
        )
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.status in {"queued", "running"}:
                if job.status == "queued":
                    job.status = "failed"
                    job.error = self._public_error(failure)
                    self._release_job(job)

    def _release_job(self, job: _JobRecord) -> None:
        if job.run_id is not None:
            self._active_resume_jobs.pop(job.run_id, None)
        if job.reservation is not None:
            job.reservation.release()
        self._prune_terminal_jobs_locked()

    def _prune_terminal_jobs_locked(self) -> None:
        terminal_ids = [
            job_id
            for job_id, stored in self._jobs.items()
            if stored.status in {"succeeded", "failed"}
        ]
        overflow = len(terminal_ids) - self._max_retained_jobs
        for job_id in terminal_ids[:max(0, overflow)]:
            self._jobs.pop(job_id, None)

    @staticmethod
    def _public_error(exc: BaseException) -> dict[str, str]:
        if isinstance(exc, (ValueError, TypeError, FileNotFoundError)):
            return {
                "type": "invalid_workflow_input",
                "message": "Workflow input is invalid.",
            }
        if isinstance(exc, DuplicateResumeJobError):
            return {
                "type": "resume_conflict",
                "message": "A resume job is already active for this run.",
            }
        if isinstance(exc, PendingCandidatesError):
            return {
                "type": "approval_required",
                "message": "Candidate approval is required before resuming.",
            }
        return {
            "type": "workflow_failed",
            "message": "Workflow execution failed.",
        }

    @staticmethod
    def _accepted_payload(job: _JobRecord) -> dict[str, object]:
        return {
            "job_id": job.job_id,
            "kind": job.kind,
            "status": "queued",
            "equivalent_command": job.equivalent_command,
        }

    def _start_command(self, request: StartRunRequest) -> str:
        arguments = [
            "start",
            f"--topic={request.topic}",
            f"--corpus={request.corpus_path}",
        ]
        if request.discovery_enabled:
            arguments.append("--discover")
        arguments.extend(f"--providers={provider}" for provider in request.providers)
        arguments.append(f"--max-results={request.max_results}")
        return self._equivalent_command(*arguments)

    def _equivalent_command(self, *arguments: str) -> str:
        return shlex.join(
            [
                *_COMMAND_PREFIX,
                f"--db={self.store.path}",
                f"--artifacts={self.artifact_root}",
                *arguments,
            ]
        )


__all__ = [
    "DuplicateResumeJobError",
    "JobNotFoundError",
    "StartRunRequest",
    "WorkflowJobManager",
]
