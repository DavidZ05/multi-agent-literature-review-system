import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from src.literature_review.models import (
    ResearchRun,
    RunStatus,
    StageCheckpoint,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.storage.sqlite import (
    RunAlreadyExistsError,
    RunNotFoundError,
    SQLiteWorkflowStore,
    UnsupportedSchemaVersionError,
)


class SQLiteWorkflowStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nested" / "workflow.db"
        self.store = SQLiteWorkflowStore(self.path)
        self.store.initialize()
        self.run = ResearchRun.create("Memory agents")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_initialize_is_idempotent_and_sets_version(self) -> None:
        self.store.initialize()
        with sqlite3.connect(self.path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 1)

    def test_create_get_list_and_update_run(self) -> None:
        self.store.create_run(self.run)
        self.assertEqual(self.store.get_run(self.run.run_id), self.run)
        updated = replace(
            self.run,
            status=RunStatus.COMPLETED,
            current_stage=WorkflowStage.COMPLETED,
            updated_at=utc_now_iso(),
        )
        self.store.update_run(updated)
        self.assertEqual(self.store.get_run(self.run.run_id), updated)
        self.assertEqual(self.store.list_runs(), [updated])

    def test_list_runs_orders_newest_first(self) -> None:
        older = self.run
        newer = replace(
            ResearchRun.create("Newer"),
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        self.store.create_run(older)
        self.store.create_run(newer)
        self.assertEqual(
            [run.run_id for run in self.store.list_runs()],
            [newer.run_id, older.run_id],
        )

    def test_duplicate_and_unknown_runs_raise_domain_errors(self) -> None:
        self.store.create_run(self.run)
        with self.assertRaises(RunAlreadyExistsError):
            self.store.create_run(self.run)
        missing = ResearchRun.create("Missing")
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(missing.run_id)
        with self.assertRaises(RunNotFoundError):
            self.store.update_run(missing)

    def test_events_are_ordered_and_survive_new_store_instance(self) -> None:
        self.store.create_run(self.run)
        first = self.store.append_event(
            self.run.run_id,
            "run_created",
            {"topic": self.run.topic},
            WorkflowStage.CREATED,
        )
        second = self.store.append_event(
            self.run.run_id,
            "planning_started",
            {"attempt": 1},
            WorkflowStage.PLANNING,
        )
        reopened = SQLiteWorkflowStore(self.path)
        reopened.initialize()
        self.assertEqual(reopened.list_events(self.run.run_id), [first, second])
        self.assertLess(first.event_id, second.event_id)

    def test_checkpoint_upsert_and_foreign_keys(self) -> None:
        self.store.create_run(self.run)
        first = StageCheckpoint(
            self.run.run_id,
            WorkflowStage.PLANNING,
            "a" * 64,
            {"request": "b" * 64},
            "completed",
            utc_now_iso(),
        )
        second = replace(first, input_fingerprint="c" * 64)
        self.store.put_checkpoint(first)
        self.store.put_checkpoint(second)
        reopened = SQLiteWorkflowStore(self.path)
        reopened.initialize()
        self.assertEqual(
            reopened.get_checkpoint(self.run.run_id, WorkflowStage.PLANNING),
            second,
        )
        missing = ResearchRun.create("Missing")
        with self.assertRaises(RunNotFoundError):
            self.store.append_event(missing.run_id, "bad", {})
        with self.assertRaises(RunNotFoundError):
            self.store.put_checkpoint(replace(first, run_id=missing.run_id))

    def test_future_schema_is_rejected_without_change(self) -> None:
        future = Path(self.tmp.name) / "future.db"
        with sqlite3.connect(future) as connection:
            connection.execute("PRAGMA user_version = 2")
        with self.assertRaises(UnsupportedSchemaVersionError):
            SQLiteWorkflowStore(future).initialize()
        with sqlite3.connect(future) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
