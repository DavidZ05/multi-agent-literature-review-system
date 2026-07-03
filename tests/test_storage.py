import sqlite3
import unittest
from contextlib import closing
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
from src.literature_review.storage.artifacts import (
    ArtifactPathError,
    LocalArtifactStore,
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
        self.assertEqual(version, 3)

    def test_version_one_database_migrates_without_losing_data(self) -> None:
        legacy_path = Path(self.tmp.name) / "legacy.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript(
                """
                CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_stage TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    corpus_version INTEGER NOT NULL,
                    revision_count INTEGER NOT NULL
                );
                CREATE TABLE workflow_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    stage TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE checkpoints (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    output_hashes_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, stage)
                );
                PRAGMA user_version = 1;
                """
            )
        legacy = SQLiteWorkflowStore(legacy_path)
        legacy.initialize()
        legacy.create_run(self.run)
        checkpoint = StageCheckpoint(
            self.run.run_id,
            WorkflowStage.PLANNING,
            "a" * 64,
            {},
            "completed",
            utc_now_iso(),
            WorkflowStage.DRAFTING,
        )
        legacy.put_checkpoint(checkpoint)

        self.assertEqual(
            legacy.get_checkpoint(self.run.run_id, WorkflowStage.PLANNING),
            checkpoint,
        )
        with sqlite3.connect(legacy_path) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)

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

    def test_delete_run_cascades_run_data_and_preserves_other_data(self) -> None:
        other_run = ResearchRun.create("Other run")
        self.store.create_run(self.run)
        self.store.create_run(other_run)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            for run in (self.run, other_run):
                connection.execute(
                    """INSERT INTO workflow_events
                    (run_id,event_type,stage,payload_json,created_at)
                    VALUES (?,?,?,?,?)""",
                    (run.run_id, "created", None, "{}", utc_now_iso()),
                )
                connection.execute(
                    """INSERT INTO checkpoints
                    (run_id,stage,input_fingerprint,output_hashes_json,status,
                     created_at,next_stage)
                    VALUES (?,?,?,?,?,?,?)""",
                    (
                        run.run_id,
                        WorkflowStage.PLANNING.value,
                        "a" * 64,
                        "{}",
                        "completed",
                        utc_now_iso(),
                        WorkflowStage.DRAFTING.value,
                    ),
                )
                connection.execute(
                    """INSERT INTO search_queries
                    (run_id,query_id,payload_json) VALUES (?,?,?)""",
                    (run.run_id, f"query-{run.run_id}", "{}"),
                )
                connection.execute(
                    """INSERT INTO candidate_papers
                    (run_id,candidate_id,status,recommendation,payload_json)
                    VALUES (?,?,?,?,?)""",
                    (
                        run.run_id,
                        f"candidate-{run.run_id}",
                        "included",
                        "include",
                        "{}",
                    ),
                )
                connection.execute(
                    """INSERT INTO corpus_decisions
                    (decision_id,run_id,candidate_id,status,reason,actor,
                     created_at,details_json)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        f"decision-{run.run_id}",
                        run.run_id,
                        f"candidate-{run.run_id}",
                        "included",
                        "relevant",
                        "reviewer",
                        utc_now_iso(),
                        "{}",
                    ),
                )
            connection.execute(
                """INSERT INTO provider_response_cache
                (cache_key,value,expires_at) VALUES (?,?,?)""",
                ("shared-cache", b"response", 1_000_000_000_000),
            )

        self.store.delete_run(self.run.run_id)

        with closing(sqlite3.connect(self.path)) as connection, connection:
            self.assertEqual(
                connection.execute(
                    "SELECT run_id FROM runs ORDER BY run_id"
                ).fetchall(),
                [(other_run.run_id,)],
            )
            for table in (
                "workflow_events",
                "checkpoints",
                "search_queries",
                "candidate_papers",
                "corpus_decisions",
            ):
                with self.subTest(table=table):
                    self.assertEqual(
                        connection.execute(
                            f"SELECT run_id FROM {table} ORDER BY run_id"
                        ).fetchall(),
                        [(other_run.run_id,)],
                    )
            self.assertEqual(
                connection.execute(
                    """SELECT cache_key,value FROM provider_response_cache"""
                ).fetchall(),
                [("shared-cache", b"response")],
            )

    def test_delete_unknown_run_raises_domain_error(self) -> None:
        with self.assertRaises(RunNotFoundError):
            self.store.delete_run("missing-run")

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
            WorkflowStage.DRAFTING,
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
            connection.execute("PRAGMA user_version = 4")
        with self.assertRaises(UnsupportedSchemaVersionError):
            SQLiteWorkflowStore(future).initialize()
        with sqlite3.connect(future) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)


class LocalArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.store = LocalArtifactStore(Path(self.tmp.name) / "artifacts")
        self.run_id = ResearchRun.create("Artifacts").run_id

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_text_write_is_readable_and_hashed(self) -> None:
        record = self.store.write_text(
            self.run_id, "inputs/request.json", '{"topic":"memory"}'
        )
        self.assertEqual(record.relative_path, "inputs/request.json")
        self.assertEqual(
            self.store.read_text(self.run_id, record.relative_path),
            '{"topic":"memory"}',
        )
        self.assertEqual(record.size_bytes, len('{"topic":"memory"}'))
        self.assertEqual(len(record.sha256), 64)
        self.assertTrue(record.absolute_path.is_file())

    def test_json_round_trip_and_overwrite(self) -> None:
        self.store.write_json(self.run_id, "state/run.json", {"value": 1})
        self.store.write_json(self.run_id, "state/run.json", {"value": 2})
        self.assertEqual(
            self.store.read_json(self.run_id, "state/run.json"), {"value": 2}
        )

    def test_paths_cannot_escape_run_directory(self) -> None:
        for path in ("../secret", "/tmp/secret", "nested/../../secret"):
            with self.subTest(path=path):
                with self.assertRaises(ArtifactPathError):
                    self.store.write_text(self.run_id, path, "bad")

    def test_serialization_failure_leaves_no_target(self) -> None:
        with self.assertRaises(TypeError):
            self.store.write_json(self.run_id, "state/bad.json", {"bad": object()})
        self.assertFalse(self.store.exists(self.run_id, "state/bad.json"))


if __name__ == "__main__":
    unittest.main()
