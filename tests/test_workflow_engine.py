import unittest
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest.mock import patch

from src.literature_review.activity import RunBusy
from src.literature_review.api import APIRequestError
from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.models import (
    CandidateStatus,
    ResearchRun,
    RunStatus,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.workflow.checkpoints import fingerprint_inputs
from src.literature_review.workflow.engine import (
    PersistentWorkflowEngine,
    StageContext,
    StageExecutionError,
    StageResult,
)
from src.literature_review.workflow.handlers import DraftingHandler, PlanningHandler
from src.literature_review.workflow.handlers import (
    ApprovalGateHandler,
    DiscoveryHandler,
    ScreeningHandler,
)
from src.literature_review.discovery.approval import ApprovalService
from src.literature_review.discovery.planner import QueryPlanner
from src.literature_review.discovery.service import DiscoveryService
from tests.test_discovery import FixtureProvider, provider_paper
from tests.test_pipeline import write_sample_corpus
from src.literature_review.workflow.state import (
    InvalidTransitionError,
    can_transition,
    require_transition,
)
from src.literature_review.workbench.service import WorkbenchService


class WorkflowStateTests(unittest.TestCase):
    def test_expected_paths_are_allowed(self) -> None:
        pairs = [
            (WorkflowStage.CREATED, WorkflowStage.PLANNING),
            (WorkflowStage.PLANNING, WorkflowStage.DRAFTING),
            (WorkflowStage.PLANNING, WorkflowStage.DISCOVERING),
            (WorkflowStage.DISCOVERING, WorkflowStage.SCREENING),
            (
                WorkflowStage.SCREENING,
                WorkflowStage.AWAITING_CORPUS_APPROVAL,
            ),
            (WorkflowStage.SCREENING, WorkflowStage.DRAFTING),
            (
                WorkflowStage.AWAITING_CORPUS_APPROVAL,
                WorkflowStage.DRAFTING,
            ),
            (WorkflowStage.DRAFTING, WorkflowStage.COMPLETED),
        ]
        for current, following in pairs:
            with self.subTest(current=current, following=following):
                self.assertTrue(can_transition(current, following))

    def test_invalid_and_terminal_transitions_are_rejected(self) -> None:
        self.assertFalse(can_transition(WorkflowStage.CREATED, WorkflowStage.COMPLETED))
        self.assertFalse(
            can_transition(WorkflowStage.COMPLETED, WorkflowStage.PLANNING)
        )
        with self.assertRaisesRegex(InvalidTransitionError, "created.*completed"):
            require_transition(WorkflowStage.CREATED, WorkflowStage.COMPLETED)


class CheckpointFingerprintTests(unittest.TestCase):
    def test_mapping_order_does_not_change_fingerprint(self) -> None:
        self.assertEqual(
            fingerprint_inputs({"b": 2, "a": 1}),
            fingerprint_inputs({"a": 1, "b": 2}),
        )

    def test_input_change_changes_fingerprint(self) -> None:
        self.assertNotEqual(
            fingerprint_inputs({"a": 1, "b": 2}),
            fingerprint_inputs({"a": 1, "b": 3}),
        )

    def test_non_json_input_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            fingerprint_inputs({"bad": object()})


class RecordingHandler:
    def __init__(
        self,
        next_stage: WorkflowStage,
        output_path: str,
        *,
        failure: BaseException | None = None,
    ) -> None:
        self.next_stage = next_stage
        self.output_path = output_path
        self.failure = failure
        self.calls: list[StageContext] = []

    def __call__(self, context: StageContext) -> StageResult:
        self.calls.append(context)
        if self.failure is not None:
            raise self.failure
        return StageResult(
            next_stage=self.next_stage,
            output_artifacts={
                self.output_path: {"stage": context.run.current_stage.value}
            },
        )


class FailingAPIClient:
    def __init__(self, failure: APIRequestError) -> None:
        self.failure = failure
        self.calls = []

    def complete_json(self, settings, *, system_prompt, user_payload):
        self.calls.append((settings, system_prompt, user_payload))
        raise self.failure


def api_runtime_config() -> AgentRuntimeConfig:
    return AgentRuntimeConfig.from_env(
        {
            "AGENT_BACKEND": "api",
            "AGENT_API_MODE": "single",
            "AGENT_API_BASE_URL": "https://api.example.com/v1",
            "AGENT_API_KEY": "secret-key",
            "AGENT_MODEL": "shared-model",
        }
    )


class BlockingHandler(RecordingHandler):
    def __init__(
        self,
        next_stage: WorkflowStage,
        output_path: str,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        super().__init__(next_stage, output_path)
        self.entered = entered
        self.release = release

    def __call__(self, context: StageContext) -> StageResult:
        self.entered.set()
        self.release.wait()
        return super().__call__(context)


class PersistentWorkflowEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = SQLiteWorkflowStore(root / "workflow.db")
        self.artifacts = LocalArtifactStore(root / "artifacts")
        self.corpus_path = root / "papers.json"
        self.corpus_path.write_text("[]\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _engine(
        self,
        planning: RecordingHandler,
        drafting: RecordingHandler,
        *,
        runtime_config: dict[str, object] | None = None,
    ) -> PersistentWorkflowEngine:
        return PersistentWorkflowEngine(
            self.store,
            self.artifacts,
            {
                WorkflowStage.PLANNING: planning,
                WorkflowStage.DRAFTING: drafting,
            },
            runtime_config=runtime_config,
        )

    def test_start_executes_stages_and_records_transitions(self) -> None:
        planning = RecordingHandler(WorkflowStage.DRAFTING, "checkpoints/plan.json")
        drafting = RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json")

        run = self._engine(planning, drafting).start("Memory agents", self.corpus_path)

        self.assertEqual(run.status, RunStatus.COMPLETED)
        self.assertEqual(run.current_stage, WorkflowStage.COMPLETED)
        self.assertEqual(len(planning.calls), 1)
        self.assertEqual(len(drafting.calls), 1)
        self.assertEqual(
            [event.event_type for event in self.store.list_events(run.run_id)],
            [
                "run_created",
                "stage_transition",
                "stage_started",
                "stage_completed",
                "stage_transition",
                "stage_started",
                "stage_completed",
                "stage_transition",
                "run_completed",
            ],
        )

    def test_start_reserves_generated_run_before_making_it_visible(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        captured_run_ids: list[str] = []
        worker_errors: list[BaseException] = []
        original_create_run = self.store.create_run
        engine = self._engine(
            RecordingHandler(
                WorkflowStage.DRAFTING,
                "checkpoints/plan.json",
            ),
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
        )

        def blocking_create_run(run: ResearchRun) -> None:
            captured_run_ids.append(run.run_id)
            entered.set()
            release.wait()
            original_create_run(run)

        def start() -> None:
            try:
                engine.start("Memory agents", self.corpus_path)
            except BaseException as exc:
                worker_errors.append(exc)

        with patch.object(self.store, "create_run", side_effect=blocking_create_run):
            worker = threading.Thread(target=start)
            worker.start()
            self.assertTrue(entered.wait(timeout=2))
            try:
                with self.assertRaises(RunBusy):
                    engine.resume(captured_run_ids[0])
            finally:
                release.set()
                worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        if worker_errors:
            raise worker_errors[0]

    def test_cancelled_start_cannot_be_deleted_until_worker_exits(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        worker_errors: list[BaseException] = []
        engine = self._engine(
            BlockingHandler(
                WorkflowStage.DRAFTING,
                "checkpoints/plan.json",
                entered,
                release,
            ),
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
        )

        def start() -> None:
            try:
                engine.start("Memory agents", self.corpus_path)
            except BaseException as exc:
                worker_errors.append(exc)

        worker = threading.Thread(target=start)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))
        run = self.store.list_runs()[0]
        engine.cancel(run.run_id)

        try:
            with self.assertRaises(RunBusy):
                WorkbenchService(
                    self.store,
                    artifact_root=self.artifacts.root,
                ).delete_run(run.run_id)
        finally:
            release.set()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        if worker_errors:
            raise worker_errors[0]

    def test_failed_run_resume_cannot_be_deleted_while_worker_executes(self) -> None:
        self.store.initialize()
        run = replace(
            ResearchRun.create("Retry failed run"),
            status=RunStatus.FAILED,
        )
        self.store.create_run(run)
        self.artifacts.write_json(
            run.run_id,
            "inputs/research_request.json",
            {
                "topic": run.topic,
                "corpus_path": str(self.corpus_path),
                "runtime_config": {},
            },
        )
        entered = threading.Event()
        release = threading.Event()
        worker_errors: list[BaseException] = []
        engine = self._engine(
            BlockingHandler(
                WorkflowStage.DRAFTING,
                "checkpoints/plan.json",
                entered,
                release,
            ),
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
        )

        def resume() -> None:
            try:
                engine.resume(run.run_id)
            except BaseException as exc:
                worker_errors.append(exc)

        worker = threading.Thread(target=resume)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))
        engine.cancel(run.run_id)

        try:
            with self.assertRaises(RunBusy):
                WorkbenchService(
                    self.store,
                    artifact_root=self.artifacts.root,
                ).delete_run(run.run_id)
        finally:
            release.set()
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        if worker_errors:
            raise worker_errors[0]

    def test_second_same_run_engine_resume_is_busy_while_worker_executes(
        self,
    ) -> None:
        self.store.initialize()
        run = replace(
            ResearchRun.create("Exclusive resume"),
            status=RunStatus.FAILED,
        )
        self.store.create_run(run)
        self.artifacts.write_json(
            run.run_id,
            "inputs/research_request.json",
            {
                "topic": run.topic,
                "corpus_path": str(self.corpus_path),
                "runtime_config": {},
            },
        )
        entered = threading.Event()
        release = threading.Event()
        worker_errors: list[BaseException] = []
        engine = self._engine(
            BlockingHandler(
                WorkflowStage.DRAFTING,
                "checkpoints/plan.json",
                entered,
                release,
            ),
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
        )

        def resume() -> None:
            try:
                engine.resume(run.run_id)
            except BaseException as exc:
                worker_errors.append(exc)

        worker = threading.Thread(target=resume)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))
        try:
            with self.assertRaises(RunBusy):
                engine.resume(run.run_id)
        finally:
            release.set()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        if worker_errors:
            raise worker_errors[0]

    def test_cancel_after_worker_check_prevents_checkpoint_and_resurrection(
        self,
    ) -> None:
        entered_outputs = threading.Event()
        release_outputs = threading.Event()
        worker_errors: list[BaseException] = []
        engine = self._engine(
            RecordingHandler(
                WorkflowStage.DRAFTING,
                "checkpoints/plan.json",
            ),
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
        )
        original_write_outputs = engine._write_outputs

        def blocking_write_outputs(
            run_id: str,
            outputs: dict[str, object],
        ):
            entered_outputs.set()
            release_outputs.wait()
            return original_write_outputs(run_id, outputs)

        def start() -> None:
            try:
                engine.start("Memory agents", self.corpus_path)
            except BaseException as exc:
                worker_errors.append(exc)

        with patch.object(engine, "_write_outputs", side_effect=blocking_write_outputs):
            worker = threading.Thread(target=start)
            worker.start()
            self.assertTrue(entered_outputs.wait(timeout=2))
            run_id = self.store.list_runs()[0].run_id
            try:
                cancelled = engine.cancel(run_id)
            finally:
                release_outputs.set()
                worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        if worker_errors:
            raise worker_errors[0]
        self.assertEqual(cancelled.status, RunStatus.CANCELLED)
        final = self.store.get_run(run_id)
        self.assertEqual(final.status, RunStatus.CANCELLED)
        self.assertEqual(final.current_stage, WorkflowStage.PLANNING)
        self.assertIsNone(
            self.store.get_checkpoint(run_id, WorkflowStage.PLANNING)
        )
        events = self.store.list_events(run_id)
        cancelled_index = next(
            index
            for index, event in enumerate(events)
            if event.event_type == "run_cancelled"
        )
        self.assertNotIn(
            "stage_transition",
            [event.event_type for event in events[cancelled_index + 1 :]],
        )

    def test_cancel_retries_stage_race_and_preserves_latest_stage(self) -> None:
        self.store.initialize()
        run = replace(
            ResearchRun.create("Stage race"),
            current_stage=WorkflowStage.PLANNING,
        )
        self.store.create_run(run)
        engine = self._engine(
            RecordingHandler(
                WorkflowStage.DRAFTING,
                "checkpoints/plan.json",
            ),
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
        )
        original_compare = self.store.compare_and_update_run
        attempts = 0

        def racing_compare(
            candidate: ResearchRun,
            *,
            expected_status: RunStatus,
            expected_stage: WorkflowStage,
        ) -> bool:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                moved = replace(
                    self.store.get_run(run.run_id),
                    current_stage=WorkflowStage.DRAFTING,
                    updated_at=utc_now_iso(),
                )
                self.store.update_run(moved)
                return False
            return original_compare(
                candidate,
                expected_status=expected_status,
                expected_stage=expected_stage,
            )

        with patch.object(
            self.store,
            "compare_and_update_run",
            side_effect=racing_compare,
        ):
            cancelled = engine.cancel(run.run_id)

        self.assertEqual(attempts, 2)
        self.assertEqual(cancelled.status, RunStatus.CANCELLED)
        self.assertEqual(cancelled.current_stage, WorkflowStage.DRAFTING)
        self.assertEqual(self.store.get_run(run.run_id), cancelled)

    def test_matching_checkpoints_resume_without_reinvoking_handlers(self) -> None:
        first_planning = RecordingHandler(
            WorkflowStage.DRAFTING, "checkpoints/plan.json"
        )
        first_drafting = RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json")
        completed = self._engine(first_planning, first_drafting).start(
            "Memory agents", self.corpus_path
        )
        interrupted = replace(
            completed,
            status=RunStatus.ACTIVE,
            current_stage=WorkflowStage.PLANNING,
            updated_at=utc_now_iso(),
        )
        self.store.update_run(interrupted)
        resumed_planning = RecordingHandler(
            WorkflowStage.DRAFTING, "checkpoints/plan.json"
        )
        resumed_drafting = RecordingHandler(
            WorkflowStage.COMPLETED, "final/survey.json"
        )

        resumed = self._engine(resumed_planning, resumed_drafting).resume(
            completed.run_id
        )

        self.assertEqual(resumed.status, RunStatus.COMPLETED)
        self.assertEqual(resumed_planning.calls, [])
        self.assertEqual(resumed_drafting.calls, [])
        self.assertIn(
            "stage_checkpoint_reused",
            [event.event_type for event in self.store.list_events(completed.run_id)],
        )

    def test_changed_runtime_config_invalidates_checkpoints(self) -> None:
        completed = self._engine(
            RecordingHandler(WorkflowStage.DRAFTING, "checkpoints/plan.json"),
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
            runtime_config={"model": "deterministic"},
        ).start("Memory agents", self.corpus_path)
        self.store.update_run(
            replace(
                completed,
                status=RunStatus.ACTIVE,
                current_stage=WorkflowStage.PLANNING,
                updated_at=utc_now_iso(),
            )
        )
        planning = RecordingHandler(WorkflowStage.DRAFTING, "checkpoints/plan.json")
        drafting = RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json")

        self._engine(
            planning,
            drafting,
            runtime_config={"model": "api"},
        ).resume(completed.run_id)

        self.assertEqual(len(planning.calls), 1)
        self.assertEqual(len(drafting.calls), 1)

    def test_changed_output_artifact_invalidates_checkpoint(self) -> None:
        completed = self._engine(
            RecordingHandler(WorkflowStage.DRAFTING, "checkpoints/plan.json"),
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
        ).start("Memory agents", self.corpus_path)
        self.artifacts.write_json(
            completed.run_id,
            "checkpoints/plan.json",
            {"stage": "tampered"},
        )
        self.store.update_run(
            replace(
                completed,
                status=RunStatus.ACTIVE,
                current_stage=WorkflowStage.PLANNING,
                updated_at=utc_now_iso(),
            )
        )
        planning = RecordingHandler(WorkflowStage.DRAFTING, "checkpoints/plan.json")
        drafting = RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json")

        self._engine(planning, drafting).resume(completed.run_id)

        self.assertEqual(len(planning.calls), 1)
        self.assertEqual(drafting.calls, [])

    def test_failure_is_persisted_and_can_be_resumed(self) -> None:
        failing = RecordingHandler(
            WorkflowStage.DRAFTING,
            "checkpoints/plan.json",
            failure=RuntimeError("provider unavailable"),
        )
        engine = self._engine(
            failing,
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
        )

        with self.assertRaisesRegex(StageExecutionError, "planning"):
            engine.start("Memory agents", self.corpus_path)

        failed = self.store.list_runs()[0]
        self.assertEqual(failed.status, RunStatus.FAILED)
        self.assertEqual(failed.current_stage, WorkflowStage.PLANNING)
        planning = RecordingHandler(WorkflowStage.DRAFTING, "checkpoints/plan.json")
        drafting = RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json")
        resumed = self._engine(planning, drafting).resume(failed.run_id)
        self.assertEqual(resumed.status, RunStatus.COMPLETED)

    def test_keyboard_interrupt_pauses_without_checkpoint(self) -> None:
        interrupted_handler = RecordingHandler(
            WorkflowStage.DRAFTING,
            "checkpoints/plan.json",
            failure=KeyboardInterrupt(),
        )
        engine = self._engine(
            interrupted_handler,
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
        )

        with self.assertRaises(KeyboardInterrupt):
            engine.start("Memory agents", self.corpus_path)

        paused = self.store.list_runs()[0]
        self.assertEqual(paused.status, RunStatus.PAUSED)
        self.assertIsNone(
            self.store.get_checkpoint(paused.run_id, WorkflowStage.PLANNING)
        )

    def test_cancelled_run_is_terminal_and_not_resumed(self) -> None:
        interrupted_handler = RecordingHandler(
            WorkflowStage.DRAFTING,
            "checkpoints/plan.json",
            failure=KeyboardInterrupt(),
        )
        engine = self._engine(
            interrupted_handler,
            RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json"),
        )
        with self.assertRaises(KeyboardInterrupt):
            engine.start("Memory agents", self.corpus_path)
        paused = self.store.list_runs()[0]

        cancelled = engine.cancel(paused.run_id)
        resumed = engine.resume(paused.run_id)

        self.assertEqual(cancelled.status, RunStatus.CANCELLED)
        self.assertEqual(resumed.status, RunStatus.CANCELLED)


class FakeOrchestrator:
    instances: list["FakeOrchestrator"] = []

    def __init__(
        self,
        corpus_path: Path,
        output_dir: Path,
        runtime_config: AgentRuntimeConfig,
        run_id: str | None = None,
    ) -> None:
        self.corpus_path = corpus_path
        self.output_dir = output_dir
        self.runtime_config = runtime_config
        self.run_id = run_id
        self.__class__.instances.append(self)

    def run(self) -> dict[str, object]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "survey.md").write_text(
            "# Durable survey\n", encoding="utf-8"
        )
        for filename in (
            "review_report.json",
            "final_verification.json",
            "evaluation_report.json",
            "revision_log.json",
        ):
            (self.output_dir / filename).write_text(
                json.dumps({"status": "accepted"}),
                encoding="utf-8",
            )
        (self.output_dir / "reflection_log.md").write_text(
            "# Reflection\n", encoding="utf-8"
        )
        return {"status": "accepted"}


class DurableHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = SQLiteWorkflowStore(root / "workflow.db")
        self.store.initialize()
        self.artifacts = LocalArtifactStore(root / "artifacts")
        self.corpus_path = root / "papers.json"
        self.corpus_path.write_text("[]\n", encoding="utf-8")
        self.run = self._create_run()
        self.context = StageContext(
            run=replace(
                self.run,
                current_stage=WorkflowStage.PLANNING,
                updated_at=utc_now_iso(),
            ),
            artifact_store=self.artifacts,
            workflow_store=self.store,
            corpus_path=self.corpus_path,
            runtime_config={"backend": "deterministic"},
            _cancellation_check=lambda: False,
        )
        FakeOrchestrator.instances.clear()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_run(self):
        from src.literature_review.models import ResearchRun

        run = ResearchRun.create("Memory agents")
        self.store.create_run(run)
        return run

    def test_planning_handler_emits_research_request(self) -> None:
        result = PlanningHandler()(self.context)

        self.assertEqual(result.next_stage, WorkflowStage.DRAFTING)
        self.assertEqual(
            result.output_artifacts["inputs/research_request.json"],
            {
                "topic": "Memory agents",
                "corpus_path": str(self.corpus_path.resolve()),
                "runtime_config": {"backend": "deterministic"},
            },
        )

    def test_drafting_handler_imports_final_artifact_contract(self) -> None:
        runtime_config = AgentRuntimeConfig()
        drafting_context = replace(
            self.context,
            run=replace(
                self.context.run,
                current_stage=WorkflowStage.DRAFTING,
                updated_at=utc_now_iso(),
            ),
        )
        handler = DraftingHandler(
            runtime_config,
            orchestrator_factory=FakeOrchestrator,
        )

        result = handler(drafting_context)

        self.assertEqual(result.next_stage, WorkflowStage.COMPLETED)
        self.assertEqual(
            set(result.output_artifacts),
            {
                "final/survey.md",
                "final/review_report.json",
                "final/final_verification.json",
                "final/evaluation_report.json",
                "final/reflection_log.md",
                "final/revision_log.json",
            },
        )
        instance = FakeOrchestrator.instances[0]
        self.assertEqual(instance.run_id, self.run.run_id)
        self.assertEqual(instance.corpus_path, self.corpus_path)
        self.assertEqual(instance.runtime_config, runtime_config)

    def test_real_orchestrator_completes_inside_persistent_engine(self) -> None:
        runtime_config = AgentRuntimeConfig()
        engine = PersistentWorkflowEngine(
            self.store,
            self.artifacts,
            {
                WorkflowStage.PLANNING: PlanningHandler(),
                WorkflowStage.DRAFTING: DraftingHandler(runtime_config),
            },
            runtime_config=runtime_config.public_dict(),
        )
        corpus = Path(__file__).resolve().parents[1] / "data" / "papers.json"

        completed = engine.start("Memory agents", corpus)

        self.assertEqual(completed.status, RunStatus.COMPLETED)
        for relative_path in (
            "final/survey.md",
            "final/review_report.json",
            "final/final_verification.json",
            "final/evaluation_report.json",
            "final/reflection_log.md",
            "final/revision_log.json",
        ):
            self.assertTrue(
                self.artifacts.exists(completed.run_id, relative_path),
                relative_path,
            )

    def test_retryable_api_failure_enters_retry_wait_without_secret_leak(self) -> None:
        write_sample_corpus(self.corpus_path)
        runtime_config = api_runtime_config()
        client = FailingAPIClient(
            APIRequestError(
                "secret-key timeout talking to provider",
                code="timeout",
                retryable=True,
            )
        )
        engine = PersistentWorkflowEngine(
            self.store,
            self.artifacts,
            {
                WorkflowStage.PLANNING: PlanningHandler(),
                WorkflowStage.DRAFTING: DraftingHandler(
                    runtime_config,
                    api_client=client,
                ),
            },
            runtime_config=runtime_config.public_dict(),
        )

        run = engine.start("Memory agents", self.corpus_path)

        self.assertEqual(run.status, RunStatus.RETRY_WAIT)
        self.assertEqual(run.current_stage, WorkflowStage.DRAFTING)
        retry_events = [
            event
            for event in self.store.list_events(run.run_id)
            if event.event_type == "stage_retry_wait"
        ]
        self.assertEqual(len(retry_events), 1)
        self.assertEqual(
            retry_events[0].payload["message"],
            "API provider retryable failure (timeout)",
        )
        self.assertNotIn("secret-key", json.dumps(dict(retry_events[0].payload)))
        self.assertEqual(client.calls[0][0].agent_id, "writer")

    def test_permanent_api_failure_is_failed_and_sanitized(self) -> None:
        write_sample_corpus(self.corpus_path)
        runtime_config = api_runtime_config()
        client = FailingAPIClient(
            APIRequestError(
                "secret-key rejected by provider",
                code="auth_failed",
                retryable=False,
                status=401,
            )
        )
        engine = PersistentWorkflowEngine(
            self.store,
            self.artifacts,
            {
                WorkflowStage.PLANNING: PlanningHandler(),
                WorkflowStage.DRAFTING: DraftingHandler(
                    runtime_config,
                    api_client=client,
                ),
            },
            runtime_config=runtime_config.public_dict(),
        )

        with self.assertRaisesRegex(StageExecutionError, "drafting stage failed"):
            engine.start("Memory agents", self.corpus_path)

        failed = self.store.list_runs()[0]
        self.assertEqual(failed.status, RunStatus.FAILED)
        self.assertEqual(failed.current_stage, WorkflowStage.DRAFTING)
        failure_events = [
            event
            for event in self.store.list_events(failed.run_id)
            if event.event_type == "stage_failed"
        ]
        self.assertEqual(len(failure_events), 1)
        self.assertEqual(
            failure_events[0].payload["message"],
            "API provider permanent failure (auth_failed, status=401)",
        )
        self.assertNotIn("secret-key", json.dumps(dict(failure_events[0].payload)))

    def test_discovery_path_waits_before_drafting(self) -> None:
        paper = provider_paper("arxiv", "2304.03442", arxiv_id="2304.03442")
        service = DiscoveryService(
            QueryPlanner(max_results=1),
            {"arxiv": FixtureProvider("arxiv", (paper,))},
        )
        drafting = RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json")
        engine = PersistentWorkflowEngine(
            self.store,
            self.artifacts,
            {
                WorkflowStage.PLANNING: PlanningHandler(discovery_enabled=True),
                WorkflowStage.DISCOVERING: DiscoveryHandler(service),
                WorkflowStage.SCREENING: ScreeningHandler(),
                WorkflowStage.DRAFTING: drafting,
            },
            runtime_config={"discovery_enabled": True},
        )

        run = engine.start("LLM agent memory", self.corpus_path)

        self.assertEqual(run.status, RunStatus.WAITING)
        self.assertEqual(run.current_stage, WorkflowStage.AWAITING_CORPUS_APPROVAL)
        self.assertEqual(drafting.calls, [])
        self.assertFalse(self.artifacts.exists(run.run_id, "final/survey.json"))

    def test_zero_candidate_discovery_waits_for_human_review(self) -> None:
        service = DiscoveryService(
            QueryPlanner(max_results=1),
            {"arxiv": FixtureProvider("arxiv", ())},
        )
        drafting = RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json")
        engine = PersistentWorkflowEngine(
            self.store,
            self.artifacts,
            {
                WorkflowStage.PLANNING: PlanningHandler(discovery_enabled=True),
                WorkflowStage.DISCOVERING: DiscoveryHandler(service),
                WorkflowStage.SCREENING: ScreeningHandler(),
                WorkflowStage.DRAFTING: drafting,
            },
            runtime_config={"discovery_enabled": True},
        )

        run = engine.start("Football", self.corpus_path)

        self.assertEqual(run.status, RunStatus.WAITING)
        self.assertEqual(run.current_stage, WorkflowStage.AWAITING_CORPUS_APPROVAL)
        self.assertEqual(drafting.calls, [])
        self.assertEqual(self.store.list_candidates(run.run_id), [])
        self.assertEqual(
            self.artifacts.read_json(
                run.run_id,
                "discovery/screening_summary.json",
            ),
            {
                "pending_candidate_count": 0,
                "candidate_ids": [],
                "review_required": True,
                "reason": "zero_candidate_discovery",
            },
        )
        waiting_events = [
            event
            for event in self.store.list_events(run.run_id)
            if event.event_type == "run_waiting"
        ]
        self.assertEqual(
            waiting_events[-1].payload["reason"],
            "discovery produced no candidate papers",
        )

    def test_all_provider_failures_enter_retry_wait(self) -> None:
        service = DiscoveryService(
            QueryPlanner(max_results=1),
            {"arxiv": FixtureProvider("arxiv", error=RuntimeError("temporary outage"))},
        )
        engine = PersistentWorkflowEngine(
            self.store,
            self.artifacts,
            {
                WorkflowStage.PLANNING: PlanningHandler(discovery_enabled=True),
                WorkflowStage.DISCOVERING: DiscoveryHandler(service),
            },
            runtime_config={"discovery_enabled": True},
        )

        run = engine.start("LLM agent memory", self.corpus_path)

        self.assertEqual(run.status, RunStatus.RETRY_WAIT)
        self.assertEqual(run.current_stage, WorkflowStage.DISCOVERING)

    def test_approved_candidate_allows_resume_to_drafting(self) -> None:
        paper = provider_paper(
            "arxiv",
            "novel-memory",
            arxiv_id="2601.00001",
            title="Novel Memory Reflection for LLM Agents",
            year=2026,
        )
        service = DiscoveryService(
            QueryPlanner(max_results=1),
            {"arxiv": FixtureProvider("arxiv", (paper,))},
        )
        approval = ApprovalService(self.store)
        drafting = RecordingHandler(WorkflowStage.COMPLETED, "final/survey.json")
        engine = PersistentWorkflowEngine(
            self.store,
            self.artifacts,
            {
                WorkflowStage.PLANNING: PlanningHandler(discovery_enabled=True),
                WorkflowStage.DISCOVERING: DiscoveryHandler(service),
                WorkflowStage.SCREENING: ScreeningHandler(),
                WorkflowStage.AWAITING_CORPUS_APPROVAL: ApprovalGateHandler(approval),
                WorkflowStage.DRAFTING: drafting,
            },
            runtime_config={"discovery_enabled": True},
        )
        waiting = engine.start("LLM agent memory", self.corpus_path)
        pending = self.store.list_candidates(
            waiting.run_id, status=CandidateStatus.PENDING
        )
        approval.approve(
            waiting.run_id,
            pending[0].candidate_id,
            reason="Relevant new evidence",
            category="memory mechanism",
            contribution="Introduces a memory reflection mechanism.",
            tags=("memory", "reflection"),
        )

        completed = engine.resume(waiting.run_id)

        self.assertEqual(completed.status, RunStatus.COMPLETED)
        self.assertEqual(len(drafting.calls), 1)
        approved = self.artifacts.read_json(
            waiting.run_id, "discovery/approved_corpus.json"
        )
        self.assertIn(
            "Novel Memory Reflection for LLM Agents",
            [item["title"] for item in approved],
        )


if __name__ == "__main__":
    unittest.main()
