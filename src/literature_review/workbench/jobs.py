from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import CancelledError, Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
import logging
from pathlib import Path
import re
import shlex
import threading
from typing import Any, Protocol
from uuid import uuid4

from src.literature_review.activity import (
    ActivityCoordinator,
    ActivityReservation,
)
from src.literature_review.job_state import ACTIVE_JOB_STATUSES, WorkflowJob
from src.literature_review.models import (
    CandidateStatus,
    ResearchRun,
    RunStatus,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.plugins import build_provider_registry
from src.literature_review.runtime import (
    build_engine,
    load_resume_full_text,
    load_resume_query_texts,
    load_resume_settings,
    retry_discovery,
)
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.workbench.service import PendingCandidatesError


_COMMAND_PREFIX = ("python3", "-m", "src.memory_review_pipeline")
_LOGGER = logging.getLogger(__name__)
_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class WorkflowEngine(Protocol):
    def start(self, topic: str, corpus_path: Path) -> ResearchRun: ...

    def resume(self, run_id: str) -> ResearchRun: ...


EngineBuilder = Callable[..., WorkflowEngine]
ResumeSettingsLoader = Callable[
    [LocalArtifactStore, str],
    tuple[bool, tuple[str, ...], int],
]
ResumeQueryLoader = Callable[[LocalArtifactStore, str], tuple[str, ...]]
ResumeFullTextLoader = Callable[[LocalArtifactStore, str], bool]


@dataclass(frozen=True)
class StartRunRequest:
    topic: str
    corpus_path: Path
    discovery_enabled: bool = False
    full_text_enabled: bool = False
    providers: tuple[str, ...] = ("arxiv", "semantic_scholar")
    max_results: int = 10
    query_texts: tuple[str, ...] = ()

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
        if not isinstance(self.full_text_enabled, bool):
            raise TypeError("full_text_enabled must be a boolean")

        providers = self._normalize_providers(self.providers)
        invalid = [provider for provider in providers if not _PROVIDER_ID.fullmatch(provider)]
        if invalid:
            raise ValueError(f"invalid provider id: {invalid[0]}")
        if self.discovery_enabled and not providers:
            raise ValueError("providers must be nonempty when discovery is enabled")

        if isinstance(self.max_results, bool) or not isinstance(self.max_results, int):
            raise TypeError("max_results must be an integer")
        if not 1 <= self.max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")
        query_texts = self._normalize_queries(self.query_texts)

        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "corpus_path", corpus_path)
        object.__setattr__(self, "providers", providers)
        object.__setattr__(self, "query_texts", query_texts)

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

    @staticmethod
    def _normalize_queries(query_texts: Iterable[str]) -> tuple[str, ...]:
        if isinstance(query_texts, str):
            raise TypeError("query_texts must be an iterable of strings")
        normalized: list[str] = []
        for query in query_texts:
            if not isinstance(query, str):
                raise TypeError("query_texts must contain strings")
            value = " ".join(query.split())
            if not value:
                continue
            if len(value) > 300:
                raise ValueError("each query must be at most 300 characters")
            if value not in normalized:
                normalized.append(value)
        if len(normalized) > 8:
            raise ValueError("at most 8 custom queries are allowed")
        return tuple(normalized)


@dataclass(frozen=True)
class RetryDiscoveryRequest:
    run_id: str
    providers: tuple[str, ...]
    max_results: int
    query_texts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        providers = StartRunRequest._normalize_providers(self.providers)
        if not providers:
            raise ValueError("providers must be nonempty")
        invalid = [provider for provider in providers if not _PROVIDER_ID.fullmatch(provider)]
        if invalid:
            raise ValueError(f"invalid provider id: {invalid[0]}")
        if isinstance(self.max_results, bool) or not isinstance(self.max_results, int):
            raise TypeError("max_results must be an integer")
        if not 1 <= self.max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")
        object.__setattr__(self, "providers", providers)
        object.__setattr__(
            self,
            "query_texts",
            StartRunRequest._normalize_queries(self.query_texts),
        )


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
    created_at: str = ""
    updated_at: str = ""

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

    def to_stored_job(self) -> WorkflowJob:
        return WorkflowJob(
            job_id=self.job_id,
            kind=self.kind,
            status=self.status,
            equivalent_command=self.equivalent_command,
            run_id=self.run_id,
            result=None if self.result is None else dict(self.result),
            error=None if self.error is None else dict(self.error),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_stored_job(cls, job: WorkflowJob) -> _JobRecord:
        return cls(
            job_id=job.job_id,
            kind=job.kind,
            status=job.status,
            equivalent_command=job.equivalent_command,
            run_id=job.run_id,
            result=None if job.result is None else dict(job.result),
            error=None if job.error is None else dict(job.error),
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class WorkflowJobManager:
    def __init__(
        self,
        store: SQLiteWorkflowStore,
        artifact_root: Path,
        *,
        engine_builder: EngineBuilder = build_engine,
        resume_settings_loader: ResumeSettingsLoader = load_resume_settings,
        resume_query_loader: ResumeQueryLoader = load_resume_query_texts,
        resume_full_text_loader: ResumeFullTextLoader = load_resume_full_text,
        executor: Executor | None = None,
        max_workers: int = 2,
        max_retained_jobs: int = 200,
        provider_options: tuple[dict[str, object], ...] | None = None,
    ) -> None:
        if isinstance(max_retained_jobs, bool) or max_retained_jobs < 1:
            raise ValueError("max_retained_jobs must be a positive integer")
        self.store = store
        self.store.path = self.store.path.expanduser().resolve()
        self.store.initialize()
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self._engine_builder = engine_builder
        self._resume_settings_loader = resume_settings_loader
        self._resume_query_loader = resume_query_loader
        self._resume_full_text_loader = resume_full_text_loader
        options = (
            build_provider_registry().options()
            if provider_options is None
            else provider_options
        )
        self.provider_options = tuple(dict(option) for option in options)
        self.provider_names = tuple(option["id"] for option in self.provider_options)
        if not self.provider_names:
            raise ValueError("at least one literature provider must be registered")
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
        self.store.interrupt_active_jobs()
        self.store.interrupt_active_discovery_attempts()
        stored_jobs = self.store.list_jobs()
        self._recover_interrupted_discovery_retries(stored_jobs)
        self._jobs: dict[str, _JobRecord] = {
            job.job_id: _JobRecord.from_stored_job(job) for job in stored_jobs
        }
        self._active_resume_jobs: dict[str, str] = {}
        self._futures: set[Future[Any]] = set()
        self._max_retained_jobs = max_retained_jobs
        with self._lock:
            self._prune_terminal_jobs_locked()

    def _recover_interrupted_discovery_retries(
        self,
        jobs: Iterable[WorkflowJob],
    ) -> None:
        for job in jobs:
            if (
                job.kind != "discovery_retry"
                or job.status != "interrupted"
                or job.run_id is None
            ):
                continue
            run = self.store.get_run(job.run_id)
            if (
                run.status != RunStatus.ACTIVE
                or run.current_stage != WorkflowStage.DISCOVERING
            ):
                continue
            return_status = RunStatus.WAITING
            return_stage = WorkflowStage.AWAITING_CORPUS_APPROVAL
            for event in reversed(self.store.list_events(run.run_id)):
                if event.event_type != "discovery_retry_started":
                    continue
                if (
                    event.payload.get("return_status") == RunStatus.RETRY_WAIT.value
                    and event.payload.get("return_stage")
                    == WorkflowStage.DISCOVERING.value
                ):
                    return_status = RunStatus.RETRY_WAIT
                    return_stage = WorkflowStage.DISCOVERING
                break
            recovered = replace(
                run,
                status=return_status,
                current_stage=return_stage,
                updated_at=utc_now_iso(),
            )
            if not self.store.compare_and_update_run(
                recovered,
                expected_status=RunStatus.ACTIVE,
                expected_stage=WorkflowStage.DISCOVERING,
            ):
                continue
            self.store.append_event(
                run.run_id,
                "discovery_retry_interrupted",
                {
                    "job_id": job.job_id,
                    "return_status": return_status.value,
                    "return_stage": return_stage.value,
                },
                return_stage,
            )

    def submit_start(self, request: StartRunRequest) -> dict[str, object]:
        if not isinstance(request, StartRunRequest):
            raise TypeError("request must be a StartRunRequest")
        request = StartRunRequest(
            topic=request.topic,
            corpus_path=request.corpus_path,
            discovery_enabled=request.discovery_enabled,
            full_text_enabled=request.full_text_enabled,
            providers=request.providers,
            max_results=request.max_results,
            query_texts=request.query_texts,
        )
        unknown = set(request.providers) - set(self.provider_names)
        if unknown:
            raise ValueError(f"unknown provider: {sorted(unknown)[0]}")
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
                    full_text_enabled=request.full_text_enabled,
                    providers=request.providers,
                    max_results=request.max_results,
                    query_texts=request.query_texts,
                ).start(request.topic, request.corpus_path),
            )
        except BaseException:
            reservation.release()
            raise
        return self._accepted_payload(job)

    def submit_discovery_retry(
        self,
        request: RetryDiscoveryRequest,
    ) -> dict[str, object]:
        if not isinstance(request, RetryDiscoveryRequest):
            raise TypeError("request must be a RetryDiscoveryRequest")
        unknown = set(request.providers) - set(self.provider_names)
        if unknown:
            raise ValueError(f"unknown provider: {sorted(unknown)[0]}")
        run = self.store.get_run(request.run_id)
        allowed = (
            run.status.value == "waiting"
            and run.current_stage == WorkflowStage.AWAITING_CORPUS_APPROVAL
        ) or (
            run.status.value == "retry_wait"
            and run.current_stage == WorkflowStage.DISCOVERING
        )
        if not allowed:
            raise ValueError("discovery retry is not available for this run")

        reservation = self._activity.reserve_resume(request.run_id)
        try:
            command = self._retry_discovery_command(request)
            job = self._new_job(
                "discovery_retry",
                command,
                run_id=request.run_id,
                reservation=reservation,
            )
            self._schedule(
                job,
                lambda: retry_discovery(
                    self.store,
                    self.artifact_root,
                    request.run_id,
                    providers=request.providers,
                    max_results=request.max_results,
                    query_texts=request.query_texts,
                ),
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
                jobs = [job for job in jobs if job.status in ACTIVE_JOB_STATUSES]
            return [job.to_dict() for job in jobs]

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def _resume(self, run_id: str) -> ResearchRun:
        artifact_store = LocalArtifactStore(self.artifact_root)
        enabled, providers, max_results = self._resume_settings_loader(
            artifact_store,
            run_id,
        )
        query_texts = self._resume_query_loader(artifact_store, run_id)
        full_text_enabled = self._resume_full_text_loader(artifact_store, run_id)
        kwargs: dict[str, object] = {
            "discovery_enabled": enabled,
            "providers": providers,
            "max_results": max_results,
        }
        if full_text_enabled:
            kwargs["full_text_enabled"] = True
        if query_texts:
            kwargs["query_texts"] = query_texts
        engine = self._engine_builder(self.store, self.artifact_root, **kwargs)
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
            stored = job.to_stored_job()
            job.created_at = stored.created_at
            job.updated_at = stored.updated_at
            self.store.put_job(job.to_stored_job())
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
                self.store.delete_job(job.job_id)
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
            self._persist_job_locked(job)
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
                self._persist_job_locked(job)
            _LOGGER.exception("Workflow job %s failed", job_id)
            if not isinstance(exc, Exception):
                raise
        else:
            with self._lock:
                job.status = "succeeded"
                job.result = result
                self._persist_job_locked(job)
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
            if job is not None and job.status in ACTIVE_JOB_STATUSES:
                if job.status == "queued":
                    job.status = "failed"
                    job.error = self._public_error(failure)
                    self._persist_job_locked(job)
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
            if stored.status in {"succeeded", "failed", "interrupted"}
        ]
        overflow = len(terminal_ids) - self._max_retained_jobs
        for job_id in terminal_ids[:max(0, overflow)]:
            self._jobs.pop(job_id, None)
            self.store.delete_job(job_id)

    def _persist_job_locked(self, job: _JobRecord) -> None:
        stored = job.to_stored_job().evolve()
        job.created_at = stored.created_at
        job.updated_at = stored.updated_at
        self.store.put_job(stored)

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
        if request.full_text_enabled:
            arguments.append("--full-text")
        arguments.extend(f"--providers={provider}" for provider in request.providers)
        arguments.append(f"--max-results={request.max_results}")
        arguments.extend(f"--query={query}" for query in request.query_texts)
        return self._equivalent_command(*arguments)

    def _retry_discovery_command(self, request: RetryDiscoveryRequest) -> str:
        arguments = ["retry-discovery", request.run_id]
        arguments.extend(f"--providers={provider}" for provider in request.providers)
        arguments.append(f"--max-results={request.max_results}")
        arguments.extend(f"--query={query}" for query in request.query_texts)
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
    "RetryDiscoveryRequest",
    "StartRunRequest",
    "WorkflowJobManager",
]
