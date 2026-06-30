import unittest

from src.literature_review.models import WorkflowStage
from src.literature_review.workflow.checkpoints import fingerprint_inputs
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
        self.assertFalse(
            can_transition(WorkflowStage.CREATED, WorkflowStage.COMPLETED)
        )
        self.assertFalse(
            can_transition(WorkflowStage.COMPLETED, WorkflowStage.PLANNING)
        )
        with self.assertRaisesRegex(
            InvalidTransitionError, "created.*completed"
        ):
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


if __name__ == "__main__":
    unittest.main()
