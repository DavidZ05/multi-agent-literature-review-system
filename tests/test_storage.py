import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from src.literature_review.models import (
    DiscoveryAttempt,
    ResearchRun,
    RunStatus,
    StageCheckpoint,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.documents import DocumentRecord, EvidenceChunk
from src.literature_review.job_state import WorkflowJob
from src.literature_review.storage.sqlite import (
    RunAlreadyExistsError,
    RunNotFoundError,
    RunStatusMismatchError,
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
        self.assertEqual(version, 6)

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
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 6)

    def test_version_three_database_adds_durable_jobs(self) -> None:
        legacy_path = Path(self.tmp.name) / "version-three.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute("PRAGMA user_version = 3")

        legacy = SQLiteWorkflowStore(legacy_path)
        legacy.initialize()

        with sqlite3.connect(legacy_path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE name='workflow_jobs'"
            ).fetchone()
        self.assertEqual(version, 6)
        self.assertEqual(table, ("workflow_jobs",))

    def test_version_four_database_adds_discovery_attempts(self) -> None:
        legacy_path = Path(self.tmp.name) / "version-four.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute("PRAGMA user_version = 4")

        legacy = SQLiteWorkflowStore(legacy_path)
        legacy.initialize()

        with sqlite3.connect(legacy_path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE name='discovery_attempts'"
            ).fetchone()
        self.assertEqual(version, 6)
        self.assertEqual(table, ("discovery_attempts",))

    def test_version_five_database_adds_evidence_audit_tables(self) -> None:
        legacy_path = Path(self.tmp.name) / "version-five.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute("PRAGMA user_version = 5")

        legacy = SQLiteWorkflowStore(legacy_path)
        legacy.initialize()

        expected = {
            "documents",
            "evidence_chunks",
            "atomic_claims",
            "claim_verifications",
            "evidence_review_decisions",
        }
        with sqlite3.connect(legacy_path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertEqual(version, 6)
        self.assertTrue(expected <= tables)

    def test_discovery_attempts_round_trip_in_creation_order(self) -> None:
        self.store.create_run(self.run)
        first = DiscoveryAttempt.create(
            self.run.run_id,
            ("arxiv",),
            ("agent memory",),
            10,
        )
        second = replace(
            DiscoveryAttempt.create(
                self.run.run_id,
                ("semantic_scholar",),
                ("memory benchmark",),
                5,
            ),
            created_at=first.created_at,
        )
        self.store.put_discovery_attempt(first)
        self.store.put_discovery_attempt(second)

        self.assertEqual(self.store.get_discovery_attempt(first.attempt_id), first)
        self.assertEqual(
            self.store.list_discovery_attempts(self.run.run_id),
            sorted((first, second), key=lambda item: (item.created_at, item.attempt_id)),
        )

    def test_active_discovery_attempt_can_be_failed_for_one_run(self) -> None:
        self.store.create_run(self.run)
        other = ResearchRun.create("Other topic")
        self.store.create_run(other)
        current = DiscoveryAttempt.create(self.run.run_id, ("arxiv",), ("memory",), 2)
        untouched = DiscoveryAttempt.create(other.run_id, ("arxiv",), ("agents",), 2)
        self.store.put_discovery_attempt(current)
        self.store.put_discovery_attempt(untouched)

        self.assertEqual(self.store.fail_active_discovery_attempts(self.run.run_id), 1)
        self.assertEqual(self.store.get_discovery_attempt(current.attempt_id).status, "failed")
        self.assertEqual(self.store.get_discovery_attempt(untouched.attempt_id).status, "running")

    def test_jobs_round_trip_and_active_jobs_are_interrupted(self) -> None:
        queued = WorkflowJob(
            job_id="job_queued",
            kind="start",
            status="queued",
            equivalent_command="literature-review start",
        )
        completed = WorkflowJob(
            job_id="job_completed",
            kind="resume",
            status="succeeded",
            equivalent_command="literature-review resume run_1",
            result={"status": "completed"},
        )
        self.store.put_job(queued)
        self.store.put_job(completed)

        self.assertEqual(self.store.get_job(queued.job_id), queued)
        self.assertEqual(self.store.interrupt_active_jobs(), 1)

        interrupted = self.store.get_job(queued.job_id)
        assert interrupted is not None
        self.assertEqual(interrupted.status, "interrupted")
        self.assertEqual(interrupted.error["type"], "backend_restarted")
        self.assertEqual(self.store.get_job(completed.job_id), completed)

        self.store.delete_job(queued.job_id)
        self.assertIsNone(self.store.get_job(queued.job_id))

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

    def test_same_pdf_can_be_indexed_in_multiple_runs(self) -> None:
        first = self.run
        second = ResearchRun.create("Other memory agents")
        self.store.create_run(first)
        self.store.create_run(second)
        chunks = []
        for run in (first, second):
            document = DocumentRecord.acquired(
                run.run_id,
                "sharedpaper",
                "https://example.test/shared.pdf",
                relative_path="documents/sharedpaper.pdf",
                sha256="a" * 64,
                byte_size=100,
                access_method="downloaded",
            )
            self.store.put_document(document)
            chunk = EvidenceChunk.create(
                run_id=run.run_id,
                document_id=document.document_id,
                document_sha256="a" * 64,
                citation_key="sharedpaper",
                section="Results",
                page_start=1,
                page_end=1,
                text="Shared evidence text.",
                char_start=0,
                char_end=21,
                settings_fingerprint="b" * 64,
            )
            self.store.replace_evidence_chunks(
                run.run_id,
                document.document_id,
                (chunk,),
            )
            chunks.append(chunk)

        self.assertNotEqual(chunks[0].chunk_id, chunks[1].chunk_id)
        self.assertEqual(len(self.store.list_evidence_chunks(first.run_id)), 1)
        self.assertEqual(len(self.store.list_evidence_chunks(second.run_id)), 1)

    def test_document_and_chunk_replacement_rolls_back_as_one_transaction(self) -> None:
        self.store.create_run(self.run)
        old_document = DocumentRecord.acquired(
            self.run.run_id,
            "paper",
            "https://example.test/old.pdf",
            relative_path="documents/paper.pdf",
            sha256="a" * 64,
            byte_size=100,
            access_method="downloaded",
        )
        self.store.put_document(old_document)
        old_chunk = EvidenceChunk.create(
            run_id=self.run.run_id,
            document_id=old_document.document_id,
            document_sha256="a" * 64,
            citation_key="paper",
            section="Results",
            page_start=1,
            page_end=1,
            text="Old evidence.",
            char_start=0,
            char_end=13,
            settings_fingerprint="old",
        )
        self.store.replace_evidence_chunks(
            self.run.run_id,
            old_document.document_id,
            (old_chunk,),
        )
        new_document = DocumentRecord.acquired(
            self.run.run_id,
            "paper",
            "https://example.test/new.pdf",
            relative_path="documents/paper.pdf",
            sha256="b" * 64,
            byte_size=120,
            access_method="imported",
        )
        duplicate_chunk = EvidenceChunk.create(
            run_id=self.run.run_id,
            document_id=new_document.document_id,
            document_sha256="b" * 64,
            citation_key="paper",
            section="Results",
            page_start=1,
            page_end=1,
            text="New evidence.",
            char_start=0,
            char_end=13,
            settings_fingerprint="new",
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.replace_document_with_chunks(
                new_document,
                (duplicate_chunk, duplicate_chunk),
            )

        self.assertEqual(
            self.store.get_document(self.run.run_id, "paper"),
            old_document,
        )
        self.assertEqual(
            self.store.list_evidence_chunks(self.run.run_id),
            [old_chunk],
        )

    def test_compare_and_update_run_requires_matching_status_and_stage(
        self,
    ) -> None:
        self.store.create_run(self.run)
        advanced = replace(
            self.run,
            current_stage=WorkflowStage.PLANNING,
            updated_at=utc_now_iso(),
        )

        lost = self.store.compare_and_update_run(
            advanced,
            expected_status=RunStatus.PAUSED,
            expected_stage=WorkflowStage.CREATED,
        )

        self.assertFalse(lost)
        self.assertEqual(self.store.get_run(self.run.run_id), self.run)

        updated = self.store.compare_and_update_run(
            advanced,
            expected_status=RunStatus.ACTIVE,
            expected_stage=WorkflowStage.CREATED,
        )

        self.assertTrue(updated)
        self.assertEqual(self.store.get_run(self.run.run_id), advanced)

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
                    """INSERT INTO discovery_attempts
                    (attempt_id,run_id,status,created_at,payload_json)
                    VALUES (?,?,?,?,?)""",
                    (
                        f"attempt-{run.run_id}",
                        run.run_id,
                        "succeeded",
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
                "discovery_attempts",
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

    def test_delete_run_with_expected_status_is_atomic(self) -> None:
        completed = replace(self.run, status=RunStatus.COMPLETED)
        self.store.create_run(completed)

        self.store.delete_run(
            completed.run_id,
            expected_status=RunStatus.COMPLETED,
        )

        with self.assertRaises(RunNotFoundError):
            self.store.get_run(completed.run_id)

    def test_delete_run_distinguishes_status_mismatch_from_missing_run(
        self,
    ) -> None:
        self.store.create_run(self.run)

        with self.assertRaises(RunStatusMismatchError) as raised:
            self.store.delete_run(
                self.run.run_id,
                expected_status=RunStatus.COMPLETED,
            )

        self.assertEqual(raised.exception.run_id, self.run.run_id)
        self.assertEqual(
            raised.exception.expected_status,
            RunStatus.COMPLETED,
        )
        self.assertEqual(raised.exception.actual_status, RunStatus.ACTIVE)
        self.assertEqual(self.store.get_run(self.run.run_id), self.run)

        with self.assertRaises(RunNotFoundError):
            self.store.delete_run(
                ResearchRun.create("Missing").run_id,
                expected_status=RunStatus.COMPLETED,
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
            connection.execute("PRAGMA user_version = 7")
        with self.assertRaises(UnsupportedSchemaVersionError):
            SQLiteWorkflowStore(future).initialize()
        with sqlite3.connect(future) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 7)


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

    def test_binary_round_trip_uses_the_same_path_guards(self) -> None:
        content = b"%PDF-1.7\n\x00binary"
        record = self.store.write_bytes(
            self.run_id,
            "documents/paper.pdf",
            content,
        )

        self.assertEqual(self.store.read_bytes(self.run_id, record.relative_path), content)
        self.assertEqual(
            self.store.path_for(self.run_id, record.relative_path),
            record.absolute_path,
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
