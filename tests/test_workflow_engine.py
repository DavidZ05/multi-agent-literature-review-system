import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from src.literature_review.models import RunStatus, WorkflowStage, utc_now_iso
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.workflow.checkpoints import fingerprint_inputs
from src.literature_review.workflow.engine import (
    PersistentWorkflowEngine,
    StageContext,
    StageExecutionError,
    StageResult,
)
from src.literature_review.workflow.state import (
    InvalidTransitionError,
    can_transition,
    require_transition,
)


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


if __name__ == "__main__":
    unittest.main()
