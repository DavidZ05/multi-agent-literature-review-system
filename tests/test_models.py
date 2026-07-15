import json
import unittest
from datetime import datetime, timezone
from types import MappingProxyType

VALID_RUN_ID = "run_0123456789abcdef0123456789abcdef"


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

        self.assertEqual(created_at.tzinfo, timezone.utc)
        self.assertEqual(updated_at.tzinfo, timezone.utc)

    def test_direct_construction_rejects_blank_topic(self) -> None:
        from src.literature_review.models import ResearchRun, RunStatus, WorkflowStage

        with self.assertRaisesRegex(ValueError, "topic"):
            ResearchRun(
                run_id=VALID_RUN_ID,
                topic="   ",
                status=RunStatus.ACTIVE,
                current_stage=WorkflowStage.CREATED,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                corpus_version=1,
                revision_count=0,
            )

    def test_direct_construction_rejects_negative_corpus_version(self) -> None:
        from src.literature_review.models import ResearchRun, RunStatus, WorkflowStage

        with self.assertRaisesRegex(ValueError, "corpus_version"):
            ResearchRun(
                run_id=VALID_RUN_ID,
                topic="Agent memory evaluation",
                status=RunStatus.ACTIVE,
                current_stage=WorkflowStage.CREATED,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                corpus_version=-1,
                revision_count=0,
            )

    def test_direct_construction_rejects_negative_revision_count(self) -> None:
        from src.literature_review.models import ResearchRun, RunStatus, WorkflowStage

        with self.assertRaisesRegex(ValueError, "revision_count"):
            ResearchRun(
                run_id=VALID_RUN_ID,
                topic="Agent memory evaluation",
                status=RunStatus.ACTIVE,
                current_stage=WorkflowStage.CREATED,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                corpus_version=1,
                revision_count=-1,
            )

    def test_direct_construction_rejects_non_enum_status(self) -> None:
        from src.literature_review.models import ResearchRun, WorkflowStage

        with self.assertRaisesRegex(TypeError, "status"):
            ResearchRun(
                run_id=VALID_RUN_ID,
                topic="Agent memory evaluation",
                status="active",
                current_stage=WorkflowStage.CREATED,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                corpus_version=1,
                revision_count=0,
            )

    def test_direct_construction_rejects_non_enum_current_stage(self) -> None:
        from src.literature_review.models import ResearchRun, RunStatus

        with self.assertRaisesRegex(TypeError, "current_stage"):
            ResearchRun(
                run_id=VALID_RUN_ID,
                topic="Agent memory evaluation",
                status=RunStatus.ACTIVE,
                current_stage="created",
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                corpus_version=1,
                revision_count=0,
            )

    def test_round_trip_dict_serialization_preserves_value_equality(self) -> None:
        from src.literature_review.models import ResearchRun

        run = ResearchRun.create("Agent memory evaluation")

        self.assertEqual(ResearchRun.from_dict(run.to_dict()), run)

    def test_from_dict_rejects_invalid_enum_strings(self) -> None:
        from src.literature_review.models import ResearchRun

        payload = {
            "run_id": VALID_RUN_ID,
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

    def test_direct_construction_rejects_malformed_run_id(self) -> None:
        from src.literature_review.models import ResearchRun, RunStatus, WorkflowStage

        with self.assertRaisesRegex(ValueError, "run_id"):
            ResearchRun(
                run_id="run_deadbeef",
                topic="Agent memory evaluation",
                status=RunStatus.ACTIVE,
                current_stage=WorkflowStage.CREATED,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                corpus_version=1,
                revision_count=0,
            )

    def test_direct_construction_rejects_non_iso_created_at(self) -> None:
        from src.literature_review.models import ResearchRun, RunStatus, WorkflowStage

        with self.assertRaisesRegex(ValueError, "created_at"):
            ResearchRun(
                run_id=VALID_RUN_ID,
                topic="Agent memory evaluation",
                status=RunStatus.ACTIVE,
                current_stage=WorkflowStage.CREATED,
                created_at="not-an-iso-timestamp",
                updated_at="2026-01-01T00:00:00+00:00",
                corpus_version=1,
                revision_count=0,
            )

    def test_direct_construction_rejects_naive_updated_at(self) -> None:
        from src.literature_review.models import ResearchRun, RunStatus, WorkflowStage

        with self.assertRaisesRegex(ValueError, "updated_at"):
            ResearchRun(
                run_id=VALID_RUN_ID,
                topic="Agent memory evaluation",
                status=RunStatus.ACTIVE,
                current_stage=WorkflowStage.CREATED,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00",
                corpus_version=1,
                revision_count=0,
            )

    def test_direct_construction_rejects_non_utc_created_at(self) -> None:
        from src.literature_review.models import ResearchRun, RunStatus, WorkflowStage

        with self.assertRaisesRegex(ValueError, "created_at"):
            ResearchRun(
                run_id=VALID_RUN_ID,
                topic="Agent memory evaluation",
                status=RunStatus.ACTIVE,
                current_stage=WorkflowStage.CREATED,
                created_at="2026-01-01T08:00:00+08:00",
                updated_at="2026-01-01T00:00:00+00:00",
                corpus_version=1,
                revision_count=0,
            )

    def test_direct_construction_rejects_updated_before_created(self) -> None:
        from src.literature_review.models import ResearchRun, RunStatus, WorkflowStage

        with self.assertRaisesRegex(ValueError, "updated_at"):
            ResearchRun(
                run_id=VALID_RUN_ID,
                topic="Agent memory evaluation",
                status=RunStatus.ACTIVE,
                current_stage=WorkflowStage.CREATED,
                created_at="2026-01-01T00:00:01+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                corpus_version=1,
                revision_count=0,
            )

    def test_from_dict_rejects_malformed_run_id(self) -> None:
        from src.literature_review.models import ResearchRun

        payload = {
            "run_id": "run_deadbeef",
            "topic": "Agent memory evaluation",
            "status": "active",
            "current_stage": "created",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "corpus_version": 1,
            "revision_count": 0,
        }

        with self.assertRaisesRegex(ValueError, "run_id"):
            ResearchRun.from_dict(payload)


class WorkflowEventTests(unittest.TestCase):
    def test_direct_construction_copies_and_freezes_payload_mapping(self) -> None:
        from src.literature_review.models import WorkflowEvent

        source_payload = {"count": 1}
        event = WorkflowEvent(
            event_id=1,
            run_id=VALID_RUN_ID,
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
            run_id=VALID_RUN_ID,
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
            "run_id": VALID_RUN_ID,
            "event_type": "stage_entered",
            "stage": None,
            "payload": {"count": 1},
            "created_at": "2026-01-01T00:00:00+00:00",
        }

        event = WorkflowEvent.from_dict(payload)
        payload["payload"]["count"] = 2

        self.assertEqual(event.payload["count"], 1)

    def test_direct_construction_rejects_non_enum_stage(self) -> None:
        from src.literature_review.models import WorkflowEvent

        with self.assertRaisesRegex(TypeError, "stage"):
            WorkflowEvent(
                event_id=1,
                run_id=VALID_RUN_ID,
                event_type="stage_entered",
                stage="planning",
                payload={"count": 1},
                created_at="2026-01-01T00:00:00+00:00",
            )

    def test_direct_construction_rejects_malformed_run_id(self) -> None:
        from src.literature_review.models import WorkflowEvent

        with self.assertRaisesRegex(ValueError, "run_id"):
            WorkflowEvent(
                event_id=1,
                run_id="run_deadbeef",
                event_type="stage_entered",
                stage=None,
                payload={"count": 1},
                created_at="2026-01-01T00:00:00+00:00",
            )

    def test_direct_construction_rejects_negative_event_id(self) -> None:
        from src.literature_review.models import WorkflowEvent

        with self.assertRaisesRegex(ValueError, "event_id"):
            WorkflowEvent(
                event_id=-1,
                run_id=VALID_RUN_ID,
                event_type="stage_entered",
                stage=None,
                payload={"count": 1},
                created_at="2026-01-01T00:00:00+00:00",
            )

    def test_direct_construction_rejects_bool_event_id(self) -> None:
        from src.literature_review.models import WorkflowEvent

        with self.assertRaisesRegex(TypeError, "event_id"):
            WorkflowEvent(
                event_id=True,
                run_id=VALID_RUN_ID,
                event_type="stage_entered",
                stage=None,
                payload={"count": 1},
                created_at="2026-01-01T00:00:00+00:00",
            )

    def test_direct_construction_rejects_blank_event_type(self) -> None:
        from src.literature_review.models import WorkflowEvent

        with self.assertRaisesRegex(ValueError, "event_type"):
            WorkflowEvent(
                event_id=1,
                run_id=VALID_RUN_ID,
                event_type="   ",
                stage=None,
                payload={"count": 1},
                created_at="2026-01-01T00:00:00+00:00",
            )

    def test_direct_construction_rejects_non_iso_created_at(self) -> None:
        from src.literature_review.models import WorkflowEvent

        with self.assertRaisesRegex(ValueError, "created_at"):
            WorkflowEvent(
                event_id=1,
                run_id=VALID_RUN_ID,
                event_type="stage_entered",
                stage=None,
                payload={"count": 1},
                created_at="bad-timestamp",
            )

    def test_direct_construction_rejects_naive_created_at(self) -> None:
        from src.literature_review.models import WorkflowEvent

        with self.assertRaisesRegex(ValueError, "created_at"):
            WorkflowEvent(
                event_id=1,
                run_id=VALID_RUN_ID,
                event_type="stage_entered",
                stage=None,
                payload={"count": 1},
                created_at="2026-01-01T00:00:00",
            )

    def test_direct_construction_rejects_non_utc_created_at(self) -> None:
        from src.literature_review.models import WorkflowEvent

        with self.assertRaisesRegex(ValueError, "created_at"):
            WorkflowEvent(
                event_id=1,
                run_id=VALID_RUN_ID,
                event_type="stage_entered",
                stage=None,
                payload={"count": 1},
                created_at="2026-01-01T08:00:00+08:00",
            )


class StageCheckpointTests(unittest.TestCase):
    def test_direct_construction_copies_and_freezes_hash_mapping(self) -> None:
        from src.literature_review.models import StageCheckpoint, WorkflowStage

        source_hashes = {"review_report": "sha256:def"}
        checkpoint = StageCheckpoint(
            run_id=VALID_RUN_ID,
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
            run_id=VALID_RUN_ID,
            stage=WorkflowStage.REVIEWING,
            input_fingerprint="abc123",
            output_artifact_hashes={
                "review_report": "sha256:def",
                "summary": "sha256:ghi",
            },
            status="ready",
            created_at="2026-01-01T00:00:00+00:00",
            next_stage=WorkflowStage.REVISING,
        )

        serialized = checkpoint.to_dict()

        self.assertEqual(serialized["stage"], "reviewing")
        self.assertEqual(serialized["next_stage"], "revising")
        self.assertEqual(json.loads(json.dumps(serialized)), serialized)
        self.assertEqual(StageCheckpoint.from_dict(serialized), checkpoint)

    def test_from_dict_copies_hash_mapping(self) -> None:
        from src.literature_review.models import StageCheckpoint

        payload = {
            "run_id": VALID_RUN_ID,
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

    def test_direct_construction_rejects_non_enum_stage(self) -> None:
        from src.literature_review.models import StageCheckpoint

        with self.assertRaisesRegex(TypeError, "stage"):
            StageCheckpoint(
                run_id=VALID_RUN_ID,
                stage="reviewing",
                input_fingerprint="abc123",
                output_artifact_hashes={"review_report": "sha256:def"},
                status="ready",
                created_at="2026-01-01T00:00:00+00:00",
            )

    def test_direct_construction_rejects_malformed_run_id(self) -> None:
        from src.literature_review.models import StageCheckpoint, WorkflowStage

        with self.assertRaisesRegex(ValueError, "run_id"):
            StageCheckpoint(
                run_id="run_deadbeef",
                stage=WorkflowStage.REVIEWING,
                input_fingerprint="abc123",
                output_artifact_hashes={"review_report": "sha256:def"},
                status="ready",
                created_at="2026-01-01T00:00:00+00:00",
            )

    def test_direct_construction_rejects_non_iso_created_at(self) -> None:
        from src.literature_review.models import StageCheckpoint, WorkflowStage

        with self.assertRaisesRegex(ValueError, "created_at"):
            StageCheckpoint(
                run_id=VALID_RUN_ID,
                stage=WorkflowStage.REVIEWING,
                input_fingerprint="abc123",
                output_artifact_hashes={"review_report": "sha256:def"},
                status="ready",
                created_at="bad-timestamp",
            )

    def test_direct_construction_rejects_non_utc_created_at(self) -> None:
        from src.literature_review.models import StageCheckpoint, WorkflowStage

        with self.assertRaisesRegex(ValueError, "created_at"):
            StageCheckpoint(
                run_id=VALID_RUN_ID,
                stage=WorkflowStage.REVIEWING,
                input_fingerprint="abc123",
                output_artifact_hashes={"review_report": "sha256:def"},
                status="ready",
                created_at="2026-01-01T08:00:00+08:00",
            )


class DiscoveryAttemptTests(unittest.TestCase):
    def test_from_dict_rejects_non_integer_funnel_count(self) -> None:
        from src.literature_review.models import DiscoveryAttempt

        payload = DiscoveryAttempt.create(
            VALID_RUN_ID,
            ("arxiv",),
            ("agent memory",),
            5,
        ).to_dict()
        payload["raw_result_count"] = "4"

        with self.assertRaisesRegex(ValueError, "nonnegative integers"):
            DiscoveryAttempt.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
