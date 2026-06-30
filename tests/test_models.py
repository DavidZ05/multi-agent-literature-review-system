import json
import unittest
from datetime import UTC, datetime
from types import MappingProxyType


class ResearchRunTests(unittest.TestCase):
    def test_create_populates_defaults_and_utc_timestamps(self) -> None:
        from src.literature_review.models import ResearchRun, RunStatus, WorkflowStage

        run = ResearchRun.create("Agent memory evaluation")

        self.assertTrue(run.run_id.startswith("run_"))
        self.assertEqual(run.topic, "Agent memory evaluation")
        self.assertEqual(run.status, RunStatus.ACTIVE)
        self.assertEqual(run.current_stage, WorkflowStage.CREATED)
        self.assertEqual(run.revision_count, 0)
        self.assertEqual(run.corpus_version, 1)

        created_at = datetime.fromisoformat(run.created_at)
        updated_at = datetime.fromisoformat(run.updated_at)

        self.assertEqual(created_at.tzinfo, UTC)
        self.assertEqual(updated_at.tzinfo, UTC)

    def test_round_trip_dict_serialization_preserves_value_equality(self) -> None:
        from src.literature_review.models import ResearchRun

        run = ResearchRun.create("Agent memory evaluation")

        self.assertEqual(ResearchRun.from_dict(run.to_dict()), run)

    def test_from_dict_rejects_invalid_enum_strings(self) -> None:
        from src.literature_review.models import ResearchRun

        payload = {
            "run_id": "run_example",
            "topic": "Agent memory evaluation",
            "status": "unknown",
            "current_stage": "created",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "corpus_version": 1,
            "revision_count": 0,
        }

        with self.assertRaises(ValueError):
            ResearchRun.from_dict(payload)


class WorkflowEventTests(unittest.TestCase):
    def test_direct_construction_copies_and_freezes_payload_mapping(self) -> None:
        from src.literature_review.models import WorkflowEvent

        source_payload = {"count": 1}
        event = WorkflowEvent(
            event_id=1,
            run_id="run_example",
            event_type="stage_entered",
            stage=None,
            payload=source_payload,
            created_at="2026-01-01T00:00:00+00:00",
        )

        source_payload["count"] = 2

        self.assertEqual(event.payload["count"], 1)
        self.assertIsInstance(event.payload, MappingProxyType)

        with self.assertRaises(TypeError):
            event.payload["count"] = 3

    def test_round_trip_dict_serialization_is_json_safe(self) -> None:
        from src.literature_review.models import WorkflowEvent, WorkflowStage

        payload = {
            "count": 3,
            "approved": True,
            "notes": ["a", "b"],
            "nested": {"topic": "Agent memory evaluation"},
            "optional": None,
        }
        event = WorkflowEvent(
            event_id=7,
            run_id="run_example",
            event_type="stage_entered",
            stage=WorkflowStage.PLANNING,
            payload=payload,
            created_at="2026-01-01T00:00:00+00:00",
        )

        serialized = event.to_dict()

        self.assertEqual(serialized["stage"], "planning")
        self.assertEqual(json.loads(json.dumps(serialized)), serialized)
        self.assertEqual(WorkflowEvent.from_dict(serialized), event)

    def test_from_dict_copies_payload_mapping(self) -> None:
        from src.literature_review.models import WorkflowEvent

        payload = {
            "event_id": 1,
            "run_id": "run_example",
            "event_type": "stage_entered",
            "stage": None,
            "payload": {"count": 1},
            "created_at": "2026-01-01T00:00:00+00:00",
        }

        event = WorkflowEvent.from_dict(payload)
        payload["payload"]["count"] = 2

        self.assertEqual(event.payload["count"], 1)


class StageCheckpointTests(unittest.TestCase):
    def test_direct_construction_copies_and_freezes_hash_mapping(self) -> None:
        from src.literature_review.models import StageCheckpoint, WorkflowStage

        source_hashes = {"review_report": "sha256:def"}
        checkpoint = StageCheckpoint(
            run_id="run_example",
            stage=WorkflowStage.REVIEWING,
            input_fingerprint="abc123",
            output_artifact_hashes=source_hashes,
            status="ready",
            created_at="2026-01-01T00:00:00+00:00",
        )

        source_hashes["review_report"] = "changed"

        self.assertEqual(
            checkpoint.output_artifact_hashes["review_report"],
            "sha256:def",
        )
        self.assertIsInstance(checkpoint.output_artifact_hashes, MappingProxyType)

        with self.assertRaises(TypeError):
            checkpoint.output_artifact_hashes["review_report"] = "mutated"

    def test_round_trip_dict_serialization_is_json_safe(self) -> None:
        from src.literature_review.models import StageCheckpoint, WorkflowStage

        checkpoint = StageCheckpoint(
            run_id="run_example",
            stage=WorkflowStage.REVIEWING,
            input_fingerprint="abc123",
            output_artifact_hashes={
                "review_report": "sha256:def",
                "summary": "sha256:ghi",
            },
            status="ready",
            created_at="2026-01-01T00:00:00+00:00",
        )

        serialized = checkpoint.to_dict()

        self.assertEqual(serialized["stage"], "reviewing")
        self.assertEqual(json.loads(json.dumps(serialized)), serialized)
        self.assertEqual(StageCheckpoint.from_dict(serialized), checkpoint)

    def test_from_dict_copies_hash_mapping(self) -> None:
        from src.literature_review.models import StageCheckpoint

        payload = {
            "run_id": "run_example",
            "stage": "reviewing",
            "input_fingerprint": "abc123",
            "output_artifact_hashes": {"review_report": "sha256:def"},
            "status": "ready",
            "created_at": "2026-01-01T00:00:00+00:00",
        }

        checkpoint = StageCheckpoint.from_dict(payload)
        payload["output_artifact_hashes"]["review_report"] = "changed"

        self.assertEqual(
            checkpoint.output_artifact_hashes["review_report"],
            "sha256:def",
        )


if __name__ == "__main__":
    unittest.main()
