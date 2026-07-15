from concurrent.futures import Future
from contextlib import chdir
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from src.literature_review import cli
from src.literature_review.activity import (
    ActivityCoordinator,
    RunBusy,
    RunDeletionBusy,
)
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    DiscoveryAttempt,
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.job_state import WorkflowJob
from src.literature_review.runtime import load_resume_settings
from src.literature_review.storage import (
    LocalArtifactStore,
    RunNotFoundError,
    SQLiteWorkflowStore,
)
from src.literature_review.workbench import PendingCandidatesError, WorkbenchService
from src.literature_review.workbench.jobs import (
    DuplicateResumeJobError,
    JobNotFoundError,
    RetryDiscoveryRequest,
    StartRunRequest,
    WorkflowJobManager,
)


class ManualExecutor:
    def __init__(self) -> None:
        self.tasks: list[tuple[Future[object], object, tuple[object, ...]]] = []
        self.futures: list[Future[object]] = []
        self.shutdown_calls: list[bool] = []

    def submit(self, function: object, *args: object) -> Future[object]:
        future: Future[object] = Future()
        self.tasks.append((future, function, args))
        self.futures.append(future)
        return future

    def run_next(self) -> None:
        future, function, args = self.tasks.pop(0)
        future.set_running_or_notify_cancel()
        try:
            result = function(*args)  # type: ignore[operator]
        except BaseException as exc:
            future.set_exception(exc)
        else:
            future.set_result(result)

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)


class RejectingExecutor(ManualExecutor):
    def submit(self, function: object, *args: object) -> Future[object]:
        raise RuntimeError("executor rejected submission")


class FakeEngine:
    def __init__(
        self,
        run: ResearchRun,
        *,
        entered: threading.Event | None = None,
        release: threading.Event | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.run = run
        self.entered = entered
        self.release = release
        self.error = error
        self.calls: list[tuple[str, object]] = []

    def start(self, topic: str, corpus_path: Path) -> ResearchRun:
        self.calls.append(("start", (topic, corpus_path)))
        return self._finish()

    def resume(self, run_id: str) -> ResearchRun:
        self.calls.append(("resume", run_id))
        return self._finish()

    def _finish(self) -> ResearchRun:
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait()
        if self.error is not None:
            raise self.error
        return self.run


def pending_candidate() -> CandidatePaper:
    return CandidatePaper(
        candidate_id="cand_pending",
        title="Pending paper",
        authors=("Ada Researcher",),
        year=2026,
        venue="Test",
        abstract="Pending review.",
        doi=None,
        arxiv_id="2601.00001",
        semantic_scholar_id=None,
        source_urls=("https://example.test/pending",),
        open_access_pdf_url=None,
        provenance=("test:pending",),
        recommendation=ScreeningRecommendation.REVIEW,
        relevance_score=0.5,
        status=CandidateStatus.PENDING,
    )


class StartRunRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.corpus_path = Path(self.tmp.name) / "papers.json"
        self.corpus_path.write_text("[]", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_normalizes_values_and_is_immutable(self) -> None:
        request = StartRunRequest(
            topic="  Memory agents  ",
            corpus_path=self.corpus_path.parent / "." / self.corpus_path.name,
            discovery_enabled=True,
            providers=(" Semantic_Scholar ", "ARXIV", "arxiv"),
            max_results=25,
        )

        self.assertEqual(request.topic, "Memory agents")
        self.assertEqual(request.corpus_path, self.corpus_path.resolve())
        self.assertEqual(request.providers, ("semantic_scholar", "arxiv"))
        with self.assertRaises(FrozenInstanceError):
            request.topic = "Changed"  # type: ignore[misc]

    def test_custom_queries_are_normalized_and_bounded(self) -> None:
        request = StartRunRequest(
            topic="Memory",
            corpus_path=self.corpus_path,
            query_texts=("  agent   memory  ", "agent memory", "benchmark"),
        )
        self.assertEqual(request.query_texts, ("agent memory", "benchmark"))

        with self.assertRaisesRegex(ValueError, "at most 8"):
            StartRunRequest(
                topic="Memory",
                corpus_path=self.corpus_path,
                query_texts=tuple(f"query {index}" for index in range(9)),
            )

    def test_rejects_invalid_inputs_before_scheduling(self) -> None:
        missing = self.corpus_path.with_name("missing.json")
        cases = (
            ({"topic": " "}, "topic must be nonblank"),
            ({"corpus_path": missing}, "corpus_path must be an existing file"),
            ({"discovery_enabled": True, "providers": ()}, "providers must be nonempty"),
            ({"providers": ("Cross-Ref",)}, "invalid provider id"),
            ({"max_results": True}, "max_results must be an integer"),
            ({"max_results": 0}, "max_results must be between 1 and 50"),
            ({"max_results": 51}, "max_results must be between 1 and 50"),
        )
        defaults = {
            "topic": "Memory",
            "corpus_path": self.corpus_path,
            "discovery_enabled": False,
            "providers": ("arxiv",),
            "max_results": 10,
        }
        for changes, message in cases:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex((TypeError, ValueError), message):
                    StartRunRequest(**{**defaults, **changes})


class WorkflowJobManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = SQLiteWorkflowStore(root / "workflow.db")
        self.store.initialize()
        self.artifact_root = root / "artifacts"
        self.corpus_path = root / "papers.json"
        self.corpus_path.write_text("[]", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _request(self, **changes: object) -> StartRunRequest:
        values = {
            "topic": "Memory agents",
            "corpus_path": self.corpus_path,
            "discovery_enabled": True,
            "providers": ("arxiv", "semantic_scholar"),
            "max_results": 7,
        }
        return StartRunRequest(**{**values, **changes})

    def test_submit_start_returns_while_engine_is_blocked_and_tracks_lifecycle(
        self,
    ) -> None:
        entered = threading.Event()
        release = threading.Event()
        run = ResearchRun.create("Memory agents")
        engine = FakeEngine(run, entered=entered, release=release)
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: engine,
            max_workers=1,
        )

        try:
            accepted = manager.submit_start(self._request())
            self.assertEqual(accepted["status"], "queued")
            self.assertTrue(entered.wait(timeout=2), "worker did not start")
            self.assertEqual(
                manager.get_job(accepted["job_id"])["status"],
                "running",
            )
            self.assertFalse(release.is_set())
        finally:
            release.set()
            manager.shutdown()

        completed = manager.get_job(accepted["job_id"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(completed["result"], run.to_dict())
        self.assertIsNone(completed["error"])
        self.assertEqual(
            engine.calls,
            [("start", ("Memory agents", self.corpus_path.resolve()))],
        )
        json.dumps(accepted)
        json.dumps(completed)

    def test_cancelled_start_future_does_not_release_executing_worker_reservation(
        self,
    ) -> None:
        entered = threading.Event()
        release = threading.Event()
        run = replace(ResearchRun.create("Cancelled"), status=RunStatus.CANCELLED)
        self.store.create_run(run)
        engine = FakeEngine(run, entered=entered, release=release)
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: engine,
            max_workers=1,
        )
        accepted = manager.submit_start(self._request())
        self.assertTrue(entered.wait(timeout=2))
        cancelled_future: Future[object] = Future()
        cancelled_future.cancel()

        try:
            with self.assertLogs(
                "src.literature_review.workbench.jobs",
                level="ERROR",
            ):
                manager._observe_future(  # type: ignore[attr-defined]
                    accepted["job_id"],
                    cancelled_future,
                )
            with self.assertRaises(RunBusy):
                WorkbenchService(
                    self.store,
                    artifact_root=self.artifact_root,
                ).delete_run(run.run_id)
        finally:
            release.set()
            manager.shutdown()

        deletion = WorkbenchService(
            self.store,
            artifact_root=self.artifact_root,
        ).delete_run(run.run_id)
        self.assertEqual(deletion["status"], "deleted")

    def test_manual_executor_exposes_queued_to_succeeded_transition(self) -> None:
        executor = ManualExecutor()
        run = ResearchRun.create("Memory agents")
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(run),
            executor=executor,
        )

        accepted = manager.submit_start(self._request())

        self.assertEqual(manager.get_job(accepted["job_id"])["status"], "queued")
        self.assertEqual(
            [job["job_id"] for job in manager.list_jobs(active_only=True)],
            [accepted["job_id"]],
        )
        executor.run_next()
        self.assertEqual(manager.get_job(accepted["job_id"])["status"], "succeeded")
        self.assertEqual(manager.list_jobs(active_only=True), [])
        self.assertEqual(manager.list_jobs()[0]["run_id"], None)
        manager.shutdown(wait=False)

    def test_discovery_retry_is_a_durable_same_run_job(self) -> None:
        run = replace(
            ResearchRun.create("Memory agents"),
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            updated_at=utc_now_iso(),
        )
        self.store.create_run(run)
        executor = ManualExecutor()
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            executor=executor,
        )
        request = RetryDiscoveryRequest(
            run_id=run.run_id,
            providers=("arxiv",),
            max_results=8,
            query_texts=("agent memory verification",),
        )

        try:
            accepted = manager.submit_discovery_retry(request)
            self.assertEqual(accepted["kind"], "discovery_retry")
            tokens = shlex.split(accepted["equivalent_command"])
            self.assertIn("retry-discovery", tokens)
            self.assertIn("--providers=arxiv", tokens)
            self.assertIn("--query=agent memory verification", tokens)
            with patch(
                "src.literature_review.workbench.jobs.retry_discovery",
                return_value=run,
            ) as retry:
                executor.run_next()
            retry.assert_called_once()
            self.assertEqual(
                manager.get_job(accepted["job_id"])["status"],
                "succeeded",
            )
        finally:
            manager.shutdown(wait=False)
        self.assertEqual(executor.shutdown_calls, [False])

    def test_manager_rejects_provider_that_is_not_registered(self) -> None:
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            executor=ManualExecutor(),
        )

        with self.assertRaisesRegex(ValueError, "unknown provider: crossref"):
            manager.submit_start(self._request(providers=("crossref",)))
        manager.shutdown(wait=False)

    def test_manager_accepts_provider_from_injected_plugin_catalog(self) -> None:
        executor = ManualExecutor()
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(
                ResearchRun.create("Plugin provider")
            ),
            executor=executor,
            provider_options=(
                {
                    "id": "crossref",
                    "label": "Crossref",
                    "source": "test",
                    "default_enabled": False,
                },
            ),
        )

        accepted = manager.submit_start(self._request(providers=("crossref",)))

        self.assertEqual(accepted["status"], "queued")
        self.assertEqual(manager.provider_names, ("crossref",))
        executor.run_next()
        self.assertEqual(manager.get_job(accepted["job_id"])["status"], "succeeded")
        manager.shutdown(wait=False)

    def test_manager_loads_history_and_marks_stale_active_job_interrupted(self) -> None:
        stale = WorkflowJob(
            job_id="job_stale",
            kind="start",
            status="running",
            equivalent_command="literature-review start --topic=Memory",
        )
        self.store.put_job(stale)
        run = ResearchRun.create("Interrupted discovery")
        self.store.create_run(run)
        attempt = DiscoveryAttempt.create(
            run.run_id,
            ("arxiv",),
            ("agent memory",),
            10,
        )
        self.store.put_discovery_attempt(attempt)

        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            executor=ManualExecutor(),
        )

        recovered = manager.get_job(stale.job_id)
        self.assertEqual(recovered["status"], "interrupted")
        self.assertEqual(recovered["error"]["type"], "backend_restarted")
        self.assertEqual(manager.list_jobs(active_only=True), [])
        self.assertEqual(
            self.store.get_discovery_attempt(attempt.attempt_id).status,
            "interrupted",
        )
        manager.shutdown(wait=False)

    def test_manager_restores_gate_for_interrupted_discovery_retry(self) -> None:
        run = replace(
            ResearchRun.create("Interrupted retry"),
            status=RunStatus.ACTIVE,
            current_stage=WorkflowStage.DISCOVERING,
            updated_at=utc_now_iso(),
        )
        self.store.create_run(run)
        self.store.append_event(
            run.run_id,
            "discovery_retry_started",
            {
                "return_status": RunStatus.WAITING.value,
                "return_stage": WorkflowStage.AWAITING_CORPUS_APPROVAL.value,
            },
            WorkflowStage.DISCOVERING,
        )
        attempt = DiscoveryAttempt.create(
            run.run_id,
            ("arxiv",),
            ("agent memory",),
            10,
        )
        self.store.put_discovery_attempt(attempt)
        job = WorkflowJob(
            job_id="job_retry_stale",
            kind="discovery_retry",
            status="running",
            run_id=run.run_id,
            equivalent_command="literature-review retry-discovery RUN_ID",
        )
        self.store.put_job(job)

        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            executor=ManualExecutor(),
        )

        recovered = self.store.get_run(run.run_id)
        self.assertEqual(recovered.status, RunStatus.WAITING)
        self.assertEqual(
            recovered.current_stage,
            WorkflowStage.AWAITING_CORPUS_APPROVAL,
        )
        self.assertEqual(manager.get_job(job.job_id)["status"], "interrupted")
        self.assertEqual(
            self.store.get_discovery_attempt(attempt.attempt_id).status,
            "interrupted",
        )
        self.assertEqual(
            self.store.list_events(run.run_id)[-1].event_type,
            "discovery_retry_interrupted",
        )
        manager.shutdown(wait=False)

    def test_terminal_job_history_is_bounded(self) -> None:
        executor = ManualExecutor()
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(
                ResearchRun.create("Memory agents")
            ),
            executor=executor,
            max_retained_jobs=1,
        )

        first = manager.submit_start(self._request())
        executor.run_next()
        second = manager.submit_start(self._request())
        executor.run_next()

        with self.assertRaises(JobNotFoundError):
            manager.get_job(first["job_id"])
        self.assertEqual(manager.get_job(second["job_id"])["status"], "succeeded")
        manager.shutdown(wait=False)

    def test_start_command_is_replay_safe_and_contains_discovery_settings(self) -> None:
        executor = ManualExecutor()
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(
                ResearchRun.create("Memory agents")
            ),
            executor=executor,
        )
        request = self._request(
            topic="-memory agents",
            query_texts=("agent memory benchmark",),
        )

        accepted = manager.submit_start(request)
        tokens = shlex.split(accepted["equivalent_command"])
        parsed = cli._parser().parse_args(tokens[3:])

        self.assertEqual(parsed.command, "start")
        self.assertEqual(parsed.db, self.store.path)
        self.assertEqual(parsed.artifacts, self.artifact_root.resolve())
        self.assertEqual(parsed.topic, request.topic)
        self.assertEqual(parsed.corpus, request.corpus_path)
        self.assertTrue(parsed.discover)
        self.assertEqual(tuple(parsed.providers), request.providers)
        self.assertEqual(parsed.max_results, request.max_results)
        self.assertEqual(tuple(parsed.query), request.query_texts)
        self.assertEqual(tokens[3], f"--db={self.store.path}")
        self.assertEqual(tokens[4], f"--artifacts={self.artifact_root.resolve()}")
        self.assertEqual(tokens[5], "start")
        self.assertIn(f"--topic={request.topic}", tokens)
        self.assertIn(f"--corpus={request.corpus_path}", tokens)
        self.assertIn(f"--max-results={request.max_results}", tokens)

    def test_resume_command_replays_configured_persistence_paths(self) -> None:
        executor = ManualExecutor()
        run = ResearchRun.create("Memory agents")
        self.store.create_run(run)
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(run),
            executor=executor,
        )

        accepted = manager.submit_resume(run.run_id)
        tokens = shlex.split(accepted["equivalent_command"])
        parsed = cli._parser().parse_args(tokens[3:])

        self.assertEqual(parsed.db, self.store.path)
        self.assertEqual(parsed.artifacts, self.artifact_root.resolve())
        self.assertEqual(parsed.command, "resume")
        self.assertEqual(parsed.run_id, run.run_id)
        self.assertEqual(tokens[3], f"--db={self.store.path}")
        self.assertEqual(tokens[4], f"--artifacts={self.artifact_root.resolve()}")
        self.assertEqual(tokens[5:], ["resume", run.run_id])

    def test_queued_resume_reservation_blocks_terminal_run_deletion(self) -> None:
        executor = ManualExecutor()
        run = replace(ResearchRun.create("Cancelled"), status=RunStatus.CANCELLED)
        self.store.create_run(run)
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(run),
            resume_settings_loader=lambda *args: (
                False,
                ("arxiv", "semantic_scholar"),
                10,
            ),
            executor=executor,
        )

        manager.submit_resume(run.run_id)

        with self.assertRaises(RunBusy):
            WorkbenchService(
                self.store,
                artifact_root=self.artifact_root,
            ).delete_run(run.run_id)
        executor.run_next()

    def test_deletion_reservation_prevents_resume_submission(self) -> None:
        executor = ManualExecutor()
        run = replace(ResearchRun.create("Cancelled"), status=RunStatus.CANCELLED)
        self.store.create_run(run)
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            executor=executor,
        )
        deletion = ActivityCoordinator.for_artifact_root(
            self.artifact_root
        ).reserve_deletion(run.run_id)

        try:
            with self.assertRaises(RunDeletionBusy):
                manager.submit_resume(run.run_id)
        finally:
            deletion.release()
        self.assertEqual(executor.tasks, [])

    def test_resume_admission_blocks_deletion_during_store_preflight(self) -> None:
        executor = ManualExecutor()
        run = replace(ResearchRun.create("Cancelled"), status=RunStatus.CANCELLED)
        self.store.create_run(run)
        entered = threading.Event()
        release = threading.Event()
        original_get_run = self.store.get_run
        accepted: list[dict[str, object]] = []
        failures: list[BaseException] = []

        def blocking_get_run(run_id: str) -> ResearchRun:
            if threading.current_thread().name == "resume-submitter":
                entered.set()
                release.wait()
            return original_get_run(run_id)

        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(run),
            resume_settings_loader=lambda *args: (
                False,
                ("arxiv", "semantic_scholar"),
                10,
            ),
            executor=executor,
        )

        def submit() -> None:
            try:
                accepted.append(manager.submit_resume(run.run_id))
            except BaseException as exc:
                failures.append(exc)

        with patch.object(self.store, "get_run", side_effect=blocking_get_run):
            thread = threading.Thread(target=submit, name="resume-submitter")
            thread.start()
            self.assertTrue(entered.wait(timeout=2))
            try:
                with self.assertRaises(RunBusy):
                    WorkbenchService(
                        self.store,
                        artifact_root=self.artifact_root,
                    ).delete_run(run.run_id)
            finally:
                release.set()
                thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(accepted), 1)
        executor.run_next()

    def test_resume_preflight_rejections_release_activity_reservation(self) -> None:
        executor = ManualExecutor()
        pending = replace(
            ResearchRun.create("Pending"),
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            updated_at=utc_now_iso(),
        )
        self.store.create_run(pending)
        self.store.upsert_candidate(pending.run_id, pending_candidate())
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            executor=executor,
        )

        with self.assertRaises(PendingCandidatesError):
            manager.submit_resume(pending.run_id)
        pending_deletion = ActivityCoordinator.for_artifact_root(
            self.artifact_root
        ).reserve_deletion(pending.run_id)
        pending_deletion.release()

        missing_run_id = ResearchRun.create("Missing").run_id
        with self.assertRaises(RunNotFoundError):
            manager.submit_resume(missing_run_id)
        missing_deletion = ActivityCoordinator.for_artifact_root(
            self.artifact_root
        ).reserve_deletion(missing_run_id)
        missing_deletion.release()

    def test_resume_scheduling_failure_releases_activity_reservation(self) -> None:
        run = ResearchRun.create("Scheduling failure")
        self.store.create_run(run)
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            executor=RejectingExecutor(),
        )

        with self.assertRaisesRegex(RuntimeError, "executor rejected"):
            manager.submit_resume(run.run_id)

        deletion = ActivityCoordinator.for_artifact_root(
            self.artifact_root
        ).reserve_deletion(run.run_id)
        deletion.release()

    def test_commands_resolve_relative_persistence_paths(self) -> None:
        executor = ManualExecutor()
        root = Path(self.tmp.name)
        with chdir(root):
            store = SQLiteWorkflowStore(Path("state/workflow.db"))
            artifact_root = Path("state/artifacts")
            manager = WorkflowJobManager(
                store,
                artifact_root,
                engine_builder=lambda *args, **kwargs: FakeEngine(
                    ResearchRun.create("Memory agents")
                ),
                executor=executor,
            )
            accepted = manager.submit_start(self._request())

        parsed = cli._parser().parse_args(
            shlex.split(accepted["equivalent_command"])[3:]
        )
        self.assertEqual(store.path, (root / "state/workflow.db").resolve())
        self.assertEqual(parsed.db, store.path)
        self.assertEqual(
            parsed.artifacts,
            (root / "state/artifacts").resolve(),
        )

    def test_failure_is_sanitized_and_logged_without_public_details(self) -> None:
        executor = ManualExecutor()
        engine = FakeEngine(
            ResearchRun.create("Memory agents"),
            error=RuntimeError("provider token=secret-value"),
        )
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: engine,
            executor=executor,
        )
        accepted = manager.submit_start(self._request())

        with self.assertLogs("src.literature_review.workbench.jobs", level="ERROR"):
            executor.run_next()

        failed = manager.get_job(accepted["job_id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(
            failed["error"],
            {
                "type": "workflow_failed",
                "message": "Workflow execution failed.",
            },
        )
        self.assertIsNone(failed["result"])
        public_payload = json.dumps(failed).lower()
        self.assertNotIn("traceback", public_payload)
        self.assertNotIn("secret-value", public_payload)

    def test_validation_failure_uses_allowlisted_public_error(self) -> None:
        executor = ManualExecutor()
        engine = FakeEngine(
            ResearchRun.create("Memory agents"),
            error=ValueError("invalid value containing secret-value"),
        )
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: engine,
            executor=executor,
        )
        accepted = manager.submit_start(self._request())

        with self.assertLogs("src.literature_review.workbench.jobs", level="ERROR"):
            executor.run_next()

        self.assertEqual(
            manager.get_job(accepted["job_id"])["error"],
            {
                "type": "invalid_workflow_input",
                "message": "Workflow input is invalid.",
            },
        )

    def test_worker_interrupt_fails_job_and_releases_resume_reservation(self) -> None:
        executor = ManualExecutor()
        run = ResearchRun.create("Memory agents")
        self.store.create_run(run)
        engine = FakeEngine(run, error=KeyboardInterrupt("secret interrupt"))
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: engine,
            resume_settings_loader=lambda *args: (
                False,
                ("arxiv", "semantic_scholar"),
                10,
            ),
            executor=executor,
        )
        accepted = manager.submit_resume(run.run_id)

        with self.assertLogs("src.literature_review.workbench.jobs", level="ERROR"):
            executor.run_next()

        self.assertIsInstance(executor.futures[0].exception(), KeyboardInterrupt)
        self.assertEqual(
            manager.get_job(accepted["job_id"]),
            {
                **accepted,
                "status": "failed",
                "run_id": run.run_id,
                "result": None,
                "error": {
                    "type": "workflow_failed",
                    "message": "Workflow execution failed.",
                },
            },
        )
        next_job = manager.submit_resume(run.run_id)
        self.assertNotEqual(next_job["job_id"], accepted["job_id"])

    def test_duplicate_resume_conflicts_only_while_existing_job_is_active(
        self,
    ) -> None:
        executor = ManualExecutor()
        run = ResearchRun.create("Memory agents")
        self.store.create_run(run)
        artifact_store = LocalArtifactStore(self.artifact_root)
        artifact_store.write_json(
            run.run_id,
            "inputs/research_request.json",
            {"runtime_config": {}},
        )
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: FakeEngine(run),
            executor=executor,
        )

        first = manager.submit_resume(run.run_id)
        with self.assertRaises(DuplicateResumeJobError) as raised:
            manager.submit_resume(run.run_id)
        self.assertEqual(raised.exception.existing_job_id, first["job_id"])

        executor.run_next()
        second = manager.submit_resume(run.run_id)

        self.assertNotEqual(second["job_id"], first["job_id"])
        self.assertEqual(
            shlex.split(second["equivalent_command"])[-2:],
            ["resume", run.run_id],
        )

    def test_resume_rejects_pending_approval_before_scheduling(self) -> None:
        executor = ManualExecutor()
        run = replace(
            ResearchRun.create("Memory agents"),
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            updated_at=utc_now_iso(),
        )
        self.store.create_run(run)
        self.store.upsert_candidate(run.run_id, pending_candidate())
        builder_calls: list[object] = []
        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=lambda *args, **kwargs: builder_calls.append(kwargs),
            executor=executor,
        )

        with self.assertRaises(PendingCandidatesError) as raised:
            manager.submit_resume(run.run_id)

        self.assertEqual(raised.exception.run_id, run.run_id)
        self.assertEqual(raised.exception.pending_count, 1)
        self.assertEqual(executor.tasks, [])
        self.assertEqual(builder_calls, [])

    def test_resume_loads_stored_settings_and_builds_matching_engine(self) -> None:
        executor = ManualExecutor()
        run = ResearchRun.create("Memory agents")
        self.store.create_run(run)
        LocalArtifactStore(self.artifact_root).write_json(
            run.run_id,
            "inputs/research_request.json",
            {
                "runtime_config": {
                    "discovery_enabled": True,
                    "discovery_providers": ["semantic_scholar"],
                    "discovery_max_results": 23,
                }
            },
        )
        builder_calls: list[tuple[object, Path, dict[str, object]]] = []
        engine = FakeEngine(run)

        def build(
            store: object,
            artifact_root: Path,
            **settings: object,
        ) -> FakeEngine:
            builder_calls.append((store, artifact_root, settings))
            return engine

        manager = WorkflowJobManager(
            self.store,
            self.artifact_root,
            engine_builder=build,
            executor=executor,
        )

        accepted = manager.submit_resume(run.run_id)
        executor.run_next()

        self.assertEqual(
            builder_calls,
            [
                (
                    self.store,
                    self.artifact_root.resolve(),
                    {
                        "discovery_enabled": True,
                        "providers": ("semantic_scholar",),
                        "max_results": 23,
                    },
                )
            ],
        )
        self.assertEqual(engine.calls, [("resume", run.run_id)])
        self.assertEqual(manager.get_job(accepted["job_id"])["status"], "succeeded")

    def test_resume_settings_public_loader_preserves_cli_defaults(self) -> None:
        run = ResearchRun.create("Memory agents")
        artifact_store = LocalArtifactStore(self.artifact_root)
        artifact_store.write_json(
            run.run_id,
            "inputs/research_request.json",
            {"runtime_config": {}},
        )

        self.assertEqual(
            load_resume_settings(artifact_store, run.run_id),
            (False, ("arxiv", "semantic_scholar"), 10),
        )

    def test_resume_settings_loader_rejects_malformed_stored_types(self) -> None:
        run = ResearchRun.create("Memory agents")
        artifact_store = LocalArtifactStore(self.artifact_root)
        invalid_configs = (
            {"discovery_enabled": "false"},
            {"discovery_providers": "arxiv"},
            {"discovery_max_results": True},
        )

        for config in invalid_configs:
            with self.subTest(config=config):
                artifact_store.write_json(
                    run.run_id,
                    "inputs/research_request.json",
                    {"runtime_config": config},
                )
                with self.assertRaises((TypeError, ValueError)):
                    load_resume_settings(artifact_store, run.run_id)


if __name__ == "__main__":
    unittest.main()
