from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import time
from typing import Callable, Iterator

from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    CorpusDecision,
    DiscoveryAttempt,
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    SearchQuery,
    StageCheckpoint,
    WorkflowEvent,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.documents.models import DocumentRecord, EvidenceChunk
from src.literature_review.verification.models import (
    AtomicClaim,
    ClaimVerification,
    EvidenceReviewDecision,
)
from src.literature_review.storage.jobs import SQLiteJobRepositoryMixin


class WorkflowStoreError(RuntimeError):
    pass


class RunAlreadyExistsError(WorkflowStoreError):
    pass


class RunNotFoundError(WorkflowStoreError):
    pass


class RunStatusMismatchError(WorkflowStoreError):
    def __init__(
        self,
        run_id: str,
        expected_status: RunStatus,
        actual_status: RunStatus,
    ) -> None:
        self.run_id = run_id
        self.expected_status = expected_status
        self.actual_status = actual_status
        super().__init__(
            f"run {run_id} has status {actual_status.value}, "
            f"expected {expected_status.value}"
        )


class UnsupportedSchemaVersionError(WorkflowStoreError):
    pass


class CandidateNotFoundError(WorkflowStoreError):
    pass


class CandidateDecisionNotAllowedError(WorkflowStoreError):
    def __init__(self, run_id: str, candidate_id: str, reason: str) -> None:
        self.run_id = run_id
        self.candidate_id = candidate_id
        self.reason = reason
        super().__init__(reason)


class SQLiteWorkflowStore(SQLiteJobRepositoryMixin):
    SCHEMA_VERSION = 7

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > self.SCHEMA_VERSION:
                raise UnsupportedSchemaVersionError(
                    f"database schema {version} is newer than supported {self.SCHEMA_VERSION}"
                )
            if version == 0:
                with connection:
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
                        next_stage TEXT,
                        PRIMARY KEY (run_id, stage)
                    );
                    CREATE TABLE search_queries (
                        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                        query_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        PRIMARY KEY (run_id, query_id)
                    );
                    CREATE TABLE candidate_papers (
                        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                        candidate_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        recommendation TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        PRIMARY KEY (run_id, candidate_id)
                    );
                    CREATE TABLE corpus_decisions (
                        decision_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                        candidate_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        actor TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        details_json TEXT NOT NULL,
                        FOREIGN KEY (run_id, candidate_id)
                            REFERENCES candidate_papers(run_id, candidate_id)
                    );
                    CREATE TABLE provider_response_cache (
                        cache_key TEXT PRIMARY KEY,
                        value BLOB NOT NULL,
                        expires_at REAL NOT NULL
                    );
                    CREATE TABLE workflow_jobs (
                        job_id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        status TEXT NOT NULL,
                        equivalent_command TEXT NOT NULL,
                        run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                        result_json TEXT,
                        error_json TEXT,
                        request_json TEXT,
                        recovery_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX workflow_jobs_status_created_idx
                        ON workflow_jobs(status, created_at);
                    CREATE TABLE workbench_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        resource_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX workbench_events_created_idx
                        ON workbench_events(created_at, event_id);
                    CREATE TABLE discovery_attempts (
                        attempt_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX discovery_attempts_run_created_idx
                        ON discovery_attempts(run_id, created_at);
                    CREATE TABLE documents (
                        document_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                        citation_key TEXT NOT NULL,
                        status TEXT NOT NULL,
                        sha256 TEXT,
                        payload_json TEXT NOT NULL,
                        UNIQUE(run_id, citation_key)
                    );
                    CREATE INDEX documents_run_status_idx
                        ON documents(run_id, status);
                    CREATE TABLE evidence_chunks (
                        chunk_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                        document_id TEXT NOT NULL REFERENCES documents(document_id)
                            ON DELETE CASCADE,
                        citation_key TEXT NOT NULL,
                        page_start INTEGER NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX evidence_chunks_run_citation_idx
                        ON evidence_chunks(run_id, citation_key, page_start);
                    CREATE TABLE atomic_claims (
                        claim_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                        draft_version INTEGER NOT NULL,
                        claim_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX atomic_claims_run_version_idx
                        ON atomic_claims(run_id, draft_version);
                    CREATE TABLE claim_verifications (
                        verification_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                        claim_id TEXT NOT NULL REFERENCES atomic_claims(claim_id)
                            ON DELETE CASCADE,
                        citation_key TEXT,
                        status TEXT NOT NULL,
                        blocking INTEGER NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX claim_verifications_run_claim_idx
                        ON claim_verifications(run_id, claim_id);
                    CREATE TABLE evidence_review_decisions (
                        decision_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                        claim_id TEXT NOT NULL REFERENCES atomic_claims(claim_id)
                            ON DELETE CASCADE,
                        action TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    );
                    CREATE INDEX evidence_decisions_run_claim_idx
                        ON evidence_review_decisions(run_id, claim_id, created_at);
                    PRAGMA user_version = 7;
                    """
                    )
                return
            if version == 1:
                with connection:
                    connection.execute(
                        "ALTER TABLE checkpoints ADD COLUMN next_stage TEXT"
                    )
                    connection.execute("PRAGMA user_version = 2")
                version = 2
            if version == 2:
                with connection:
                    connection.executescript(
                        """
                        CREATE TABLE search_queries (
                            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                            query_id TEXT NOT NULL,
                            payload_json TEXT NOT NULL,
                            PRIMARY KEY (run_id, query_id)
                        );
                        CREATE TABLE candidate_papers (
                            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                            candidate_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            recommendation TEXT NOT NULL,
                            payload_json TEXT NOT NULL,
                            PRIMARY KEY (run_id, candidate_id)
                        );
                        CREATE TABLE corpus_decisions (
                            decision_id TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                            candidate_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            reason TEXT NOT NULL,
                            actor TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            details_json TEXT NOT NULL,
                            FOREIGN KEY (run_id, candidate_id)
                                REFERENCES candidate_papers(run_id, candidate_id)
                        );
                        CREATE TABLE provider_response_cache (
                            cache_key TEXT PRIMARY KEY,
                            value BLOB NOT NULL,
                            expires_at REAL NOT NULL
                        );
                        PRAGMA user_version = 3;
                        """
                    )
                version = 3
            if version == 3:
                with connection:
                    connection.executescript(
                        """
                        CREATE TABLE workflow_jobs (
                            job_id TEXT PRIMARY KEY,
                            kind TEXT NOT NULL,
                            status TEXT NOT NULL,
                            equivalent_command TEXT NOT NULL,
                            run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                            result_json TEXT,
                            error_json TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        );
                        CREATE INDEX workflow_jobs_status_created_idx
                            ON workflow_jobs(status, created_at);
                        PRAGMA user_version = 4;
                        """
                    )
                version = 4
            if version == 4:
                with connection:
                    connection.executescript(
                        """
                        CREATE TABLE discovery_attempts (
                            attempt_id TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                            status TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            payload_json TEXT NOT NULL
                        );
                        CREATE INDEX discovery_attempts_run_created_idx
                            ON discovery_attempts(run_id, created_at);
                        PRAGMA user_version = 5;
                        """
                    )
                version = 5
            if version == 5:
                with connection:
                    connection.executescript(
                        """
                        CREATE TABLE documents (
                            document_id TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                            citation_key TEXT NOT NULL,
                            status TEXT NOT NULL,
                            sha256 TEXT,
                            payload_json TEXT NOT NULL,
                            UNIQUE(run_id, citation_key)
                        );
                        CREATE INDEX documents_run_status_idx
                            ON documents(run_id, status);
                        CREATE TABLE evidence_chunks (
                            chunk_id TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                            document_id TEXT NOT NULL REFERENCES documents(document_id)
                                ON DELETE CASCADE,
                            citation_key TEXT NOT NULL,
                            page_start INTEGER NOT NULL,
                            payload_json TEXT NOT NULL
                        );
                        CREATE INDEX evidence_chunks_run_citation_idx
                            ON evidence_chunks(run_id, citation_key, page_start);
                        CREATE TABLE atomic_claims (
                            claim_id TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                            draft_version INTEGER NOT NULL,
                            claim_type TEXT NOT NULL,
                            payload_json TEXT NOT NULL
                        );
                        CREATE INDEX atomic_claims_run_version_idx
                            ON atomic_claims(run_id, draft_version);
                        CREATE TABLE claim_verifications (
                            verification_id TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                            claim_id TEXT NOT NULL REFERENCES atomic_claims(claim_id)
                                ON DELETE CASCADE,
                            citation_key TEXT,
                            status TEXT NOT NULL,
                            blocking INTEGER NOT NULL,
                            payload_json TEXT NOT NULL
                        );
                        CREATE INDEX claim_verifications_run_claim_idx
                            ON claim_verifications(run_id, claim_id);
                        CREATE TABLE evidence_review_decisions (
                            decision_id TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                            claim_id TEXT NOT NULL REFERENCES atomic_claims(claim_id)
                                ON DELETE CASCADE,
                            action TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            payload_json TEXT NOT NULL
                        );
                        CREATE INDEX evidence_decisions_run_claim_idx
                            ON evidence_review_decisions(run_id, claim_id, created_at);
                        PRAGMA user_version = 6;
                        """
                    )
                version = 6
            if version == 6:
                with connection:
                    job_columns = {
                        row[1]
                        for row in connection.execute(
                            "PRAGMA table_info(workflow_jobs)"
                        ).fetchall()
                    }
                    if not job_columns:
                        connection.executescript(
                            """
                            CREATE TABLE workflow_jobs (
                                job_id TEXT PRIMARY KEY,
                                kind TEXT NOT NULL,
                                status TEXT NOT NULL,
                                equivalent_command TEXT NOT NULL,
                                run_id TEXT REFERENCES runs(run_id)
                                    ON DELETE SET NULL,
                                result_json TEXT,
                                error_json TEXT,
                                request_json TEXT,
                                recovery_count INTEGER NOT NULL DEFAULT 0,
                                created_at TEXT NOT NULL,
                                updated_at TEXT NOT NULL
                            );
                            CREATE INDEX workflow_jobs_status_created_idx
                                ON workflow_jobs(status, created_at);
                            """
                        )
                    else:
                        connection.execute(
                            "ALTER TABLE workflow_jobs ADD COLUMN request_json TEXT"
                        )
                        connection.execute(
                            """ALTER TABLE workflow_jobs
                            ADD COLUMN recovery_count INTEGER NOT NULL DEFAULT 0"""
                        )
                    connection.executescript(
                        """
                        CREATE TABLE IF NOT EXISTS workbench_events (
                            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            event_type TEXT NOT NULL,
                            resource_id TEXT NOT NULL,
                            payload_json TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        );
                        CREATE INDEX IF NOT EXISTS workbench_events_created_idx
                            ON workbench_events(created_at, event_id);
                        PRAGMA user_version = 7;
                        """
                    )

    def create_run(self, run: ResearchRun) -> None:
        values = run.to_dict()
        try:
            with self._connection() as connection, connection:
                connection.execute(
                    """INSERT INTO runs VALUES
                    (:run_id,:topic,:status,:current_stage,:created_at,:updated_at,
                     :corpus_version,:revision_count)""",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            raise RunAlreadyExistsError(run.run_id) from exc

    def get_run(self, run_id: str) -> ResearchRun:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise RunNotFoundError(run_id)
        return ResearchRun.from_dict(dict(row))

    def list_runs(self) -> list[ResearchRun]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC, run_id DESC"
            ).fetchall()
        return [ResearchRun.from_dict(dict(row)) for row in rows]

    def update_run(self, run: ResearchRun) -> None:
        values = run.to_dict()
        with self._connection() as connection, connection:
            cursor = connection.execute(
                """UPDATE runs SET topic=:topic,status=:status,
                current_stage=:current_stage,created_at=:created_at,
                updated_at=:updated_at,corpus_version=:corpus_version,
                revision_count=:revision_count WHERE run_id=:run_id""",
                values,
            )
        if cursor.rowcount == 0:
            raise RunNotFoundError(run.run_id)

    def compare_and_update_run(
        self,
        run: ResearchRun,
        *,
        expected_status: RunStatus,
        expected_stage: WorkflowStage,
    ) -> bool:
        values = {
            **run.to_dict(),
            "expected_status": expected_status.value,
            "expected_stage": expected_stage.value,
        }
        with self._connection() as connection, connection:
            cursor = connection.execute(
                """UPDATE runs SET topic=:topic,status=:status,
                current_stage=:current_stage,created_at=:created_at,
                updated_at=:updated_at,corpus_version=:corpus_version,
                revision_count=:revision_count
                WHERE run_id=:run_id AND status=:expected_status
                AND current_stage=:expected_stage""",
                values,
            )
            if cursor.rowcount:
                return True
            row = connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?",
                (run.run_id,),
            ).fetchone()
            if row is None:
                raise RunNotFoundError(run.run_id)
            return False

    def delete_run(
        self,
        run_id: str,
        *,
        expected_status: RunStatus | None = None,
    ) -> None:
        with self._connection() as connection, connection:
            if expected_status is None:
                cursor = connection.execute(
                    "DELETE FROM runs WHERE run_id = ?",
                    (run_id,),
                )
            else:
                cursor = connection.execute(
                    "DELETE FROM runs WHERE run_id = ? AND status = ?",
                    (run_id, expected_status.value),
                )
            if cursor.rowcount == 0:
                row = connection.execute(
                    "SELECT status FROM runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                if row is None:
                    raise RunNotFoundError(run_id)
                assert expected_status is not None
                raise RunStatusMismatchError(
                    run_id,
                    expected_status,
                    RunStatus(row["status"]),
                )

    def _require_run(self, run_id: str) -> None:
        self.get_run(run_id)

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        stage: WorkflowStage | None = None,
    ) -> WorkflowEvent:
        self._require_run(run_id)
        created_at = utc_now_iso()
        with self._connection() as connection, connection:
            cursor = connection.execute(
                """INSERT INTO workflow_events
                (run_id,event_type,stage,payload_json,created_at)
                VALUES (?,?,?,?,?)""",
                (
                    run_id,
                    event_type,
                    None if stage is None else stage.value,
                    json.dumps(payload, ensure_ascii=True, sort_keys=True),
                    created_at,
                ),
            )
            event_id = cursor.lastrowid
            connection.execute(
                """INSERT INTO workbench_events
                (event_type,resource_id,payload_json,created_at)
                VALUES ('run.event',?,?,?)""",
                (
                    run_id,
                    json.dumps(
                        {
                            "run_id": run_id,
                            "workflow_event_id": event_id,
                            "workflow_event_type": event_type,
                            "stage": None if stage is None else stage.value,
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                    created_at,
                ),
            )
        return WorkflowEvent(event_id, run_id, event_type, stage, payload, created_at)

    def list_events(self, run_id: str) -> list[WorkflowEvent]:
        self._require_run(run_id)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_events WHERE run_id=? ORDER BY event_id ASC",
                (run_id,),
            ).fetchall()
        return [
            WorkflowEvent.from_dict(
                {
                    "event_id": row["event_id"],
                    "run_id": row["run_id"],
                    "event_type": row["event_type"],
                    "stage": row["stage"],
                    "payload": json.loads(row["payload_json"]),
                    "created_at": row["created_at"],
                }
            )
            for row in rows
        ]

    def put_checkpoint(self, checkpoint: StageCheckpoint) -> None:
        self._require_run(checkpoint.run_id)
        with self._connection() as connection, connection:
            connection.execute(
                """INSERT INTO checkpoints
                (run_id,stage,input_fingerprint,output_hashes_json,status,
                 created_at,next_stage)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(run_id,stage) DO UPDATE SET
                input_fingerprint=excluded.input_fingerprint,
                output_hashes_json=excluded.output_hashes_json,
                status=excluded.status,created_at=excluded.created_at,
                next_stage=excluded.next_stage""",
                (
                    checkpoint.run_id,
                    checkpoint.stage.value,
                    checkpoint.input_fingerprint,
                    json.dumps(
                        dict(checkpoint.output_artifact_hashes),
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                    checkpoint.status,
                    checkpoint.created_at,
                    (
                        None
                        if checkpoint.next_stage is None
                        else checkpoint.next_stage.value
                    ),
                ),
            )

    def get_checkpoint(
        self, run_id: str, stage: WorkflowStage
    ) -> StageCheckpoint | None:
        self._require_run(run_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM checkpoints WHERE run_id=? AND stage=?",
                (run_id, stage.value),
            ).fetchone()
        if row is None:
            return None
        return StageCheckpoint.from_dict(
            {
                "run_id": row["run_id"],
                "stage": row["stage"],
                "input_fingerprint": row["input_fingerprint"],
                "output_artifact_hashes": json.loads(row["output_hashes_json"]),
                "status": row["status"],
                "created_at": row["created_at"],
                "next_stage": row["next_stage"],
            }
        )

    def save_search_query(self, run_id: str, query: SearchQuery) -> None:
        self._require_run(run_id)
        with self._connection() as connection, connection:
            connection.execute(
                """INSERT INTO search_queries (run_id,query_id,payload_json)
                VALUES (?,?,?)
                ON CONFLICT(run_id,query_id) DO UPDATE SET
                payload_json=excluded.payload_json""",
                (
                    run_id,
                    query.query_id,
                    json.dumps(query.to_dict(), sort_keys=True),
                ),
            )

    def list_search_queries(self, run_id: str) -> list[SearchQuery]:
        self._require_run(run_id)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM search_queries
                WHERE run_id=? ORDER BY query_id""",
                (run_id,),
            ).fetchall()
        return [SearchQuery.from_dict(json.loads(row[0])) for row in rows]

    def put_discovery_attempt(self, attempt: DiscoveryAttempt) -> None:
        self._require_run(attempt.run_id)
        with self._connection() as connection, connection:
            connection.execute(
                """INSERT INTO discovery_attempts
                (attempt_id,run_id,status,created_at,payload_json)
                VALUES (?,?,?,?,?)
                ON CONFLICT(attempt_id) DO UPDATE SET
                status=excluded.status,
                payload_json=excluded.payload_json""",
                (
                    attempt.attempt_id,
                    attempt.run_id,
                    attempt.status,
                    attempt.created_at,
                    json.dumps(attempt.to_dict(), sort_keys=True),
                ),
            )

    def get_discovery_attempt(self, attempt_id: str) -> DiscoveryAttempt:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM discovery_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        return DiscoveryAttempt.from_dict(json.loads(row[0]))

    def list_discovery_attempts(self, run_id: str) -> list[DiscoveryAttempt]:
        self._require_run(run_id)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM discovery_attempts
                WHERE run_id=? ORDER BY created_at,attempt_id""",
                (run_id,),
            ).fetchall()
        return [DiscoveryAttempt.from_dict(json.loads(row[0])) for row in rows]

    def interrupt_active_discovery_attempts(self) -> int:
        return self._finish_active_discovery_attempts("interrupted")

    def fail_active_discovery_attempts(self, run_id: str) -> int:
        self._require_run(run_id)
        return self._finish_active_discovery_attempts("failed", run_id=run_id)

    def _finish_active_discovery_attempts(
        self,
        status: str,
        *,
        run_id: str | None = None,
    ) -> int:
        query = "SELECT payload_json FROM discovery_attempts WHERE status='running'"
        parameters: tuple[str, ...] = ()
        if run_id is not None:
            query += " AND run_id=?"
            parameters = (run_id,)
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        finished = 0
        for row in rows:
            attempt = DiscoveryAttempt.from_dict(json.loads(row[0]))
            self.put_discovery_attempt(
                replace(
                    attempt,
                    status=status,
                    completed_at=utc_now_iso(),
                )
            )
            finished += 1
        return finished

    def put_document(self, document: DocumentRecord) -> None:
        self._require_run(document.run_id)
        with self._connection() as connection, connection:
            connection.execute(
                """DELETE FROM documents
                WHERE run_id=? AND citation_key=? AND document_id<>?""",
                (document.run_id, document.citation_key, document.document_id),
            )
            connection.execute(
                """INSERT INTO documents
                (document_id,run_id,citation_key,status,sha256,payload_json)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(document_id) DO UPDATE SET
                status=excluded.status,sha256=excluded.sha256,
                payload_json=excluded.payload_json""",
                (
                    document.document_id,
                    document.run_id,
                    document.citation_key,
                    document.status.value,
                    document.sha256,
                    json.dumps(document.to_dict(), sort_keys=True),
                ),
            )

    def get_document(self, run_id: str, citation_key: str) -> DocumentRecord | None:
        self._require_run(run_id)
        with self._connection() as connection:
            row = connection.execute(
                """SELECT payload_json FROM documents
                WHERE run_id=? AND citation_key=?""",
                (run_id, citation_key),
            ).fetchone()
        if row is None:
            return None
        return DocumentRecord.from_dict(json.loads(row[0]))

    def list_documents(self, run_id: str) -> list[DocumentRecord]:
        self._require_run(run_id)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM documents
                WHERE run_id=? ORDER BY citation_key,document_id""",
                (run_id,),
            ).fetchall()
        return [DocumentRecord.from_dict(json.loads(row[0])) for row in rows]

    def replace_evidence_chunks(
        self,
        run_id: str,
        document_id: str,
        chunks: list[EvidenceChunk] | tuple[EvidenceChunk, ...],
    ) -> None:
        self._require_run(run_id)
        if any(
            chunk.run_id != run_id or chunk.document_id != document_id
            for chunk in chunks
        ):
            raise ValueError("evidence chunks must match run_id and document_id")
        with self._connection() as connection, connection:
            document = connection.execute(
                "SELECT 1 FROM documents WHERE document_id=? AND run_id=?",
                (document_id, run_id),
            ).fetchone()
            if document is None:
                raise KeyError(document_id)
            connection.execute(
                "DELETE FROM evidence_chunks WHERE document_id=?",
                (document_id,),
            )
            connection.executemany(
                """INSERT INTO evidence_chunks
                (chunk_id,run_id,document_id,citation_key,page_start,payload_json)
                VALUES (?,?,?,?,?,?)""",
                [
                    (
                        chunk.chunk_id,
                        chunk.run_id,
                        chunk.document_id,
                        chunk.citation_key,
                        chunk.page_start,
                        json.dumps(chunk.to_dict(), sort_keys=True),
                    )
                    for chunk in chunks
                ],
            )

    def replace_document_with_chunks(
        self,
        document: DocumentRecord,
        chunks: list[EvidenceChunk] | tuple[EvidenceChunk, ...],
    ) -> None:
        """Atomically replace one citation's document record and evidence index."""
        self._require_run(document.run_id)
        if any(
            chunk.run_id != document.run_id
            or chunk.document_id != document.document_id
            or chunk.citation_key != document.citation_key
            for chunk in chunks
        ):
            raise ValueError("evidence chunks must match the replacement document")
        with self._connection() as connection, connection:
            connection.execute(
                """DELETE FROM documents
                WHERE run_id=? AND citation_key=? AND document_id<>?""",
                (document.run_id, document.citation_key, document.document_id),
            )
            connection.execute(
                """INSERT INTO documents
                (document_id,run_id,citation_key,status,sha256,payload_json)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(document_id) DO UPDATE SET
                status=excluded.status,sha256=excluded.sha256,
                payload_json=excluded.payload_json""",
                (
                    document.document_id,
                    document.run_id,
                    document.citation_key,
                    document.status.value,
                    document.sha256,
                    json.dumps(document.to_dict(), sort_keys=True),
                ),
            )
            connection.execute(
                "DELETE FROM evidence_chunks WHERE document_id=?",
                (document.document_id,),
            )
            connection.executemany(
                """INSERT INTO evidence_chunks
                (chunk_id,run_id,document_id,citation_key,page_start,payload_json)
                VALUES (?,?,?,?,?,?)""",
                [
                    (
                        chunk.chunk_id,
                        chunk.run_id,
                        chunk.document_id,
                        chunk.citation_key,
                        chunk.page_start,
                        json.dumps(chunk.to_dict(), sort_keys=True),
                    )
                    for chunk in chunks
                ],
            )

    def list_evidence_chunks(
        self,
        run_id: str,
        *,
        citation_key: str | None = None,
    ) -> list[EvidenceChunk]:
        self._require_run(run_id)
        query = "SELECT payload_json FROM evidence_chunks WHERE run_id=?"
        parameters: tuple[str, ...] = (run_id,)
        if citation_key is not None:
            query += " AND citation_key=?"
            parameters += (citation_key,)
        query += " ORDER BY citation_key,page_start,chunk_id"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [EvidenceChunk.from_dict(json.loads(row[0])) for row in rows]

    def replace_claims(
        self,
        run_id: str,
        draft_version: int,
        claims: list[AtomicClaim] | tuple[AtomicClaim, ...],
    ) -> None:
        self._require_run(run_id)
        if any(
            claim.run_id != run_id or claim.draft_version != draft_version
            for claim in claims
        ):
            raise ValueError("claims must match run_id and draft_version")
        with self._connection() as connection, connection:
            connection.execute(
                "DELETE FROM atomic_claims WHERE run_id=? AND draft_version=?",
                (run_id, draft_version),
            )
            connection.executemany(
                """INSERT INTO atomic_claims
                (claim_id,run_id,draft_version,claim_type,payload_json)
                VALUES (?,?,?,?,?)""",
                [
                    (
                        claim.claim_id,
                        claim.run_id,
                        claim.draft_version,
                        claim.claim_type.value,
                        json.dumps(claim.to_dict(), sort_keys=True),
                    )
                    for claim in claims
                ],
            )

    def list_claims(
        self,
        run_id: str,
        *,
        draft_version: int | None = None,
    ) -> list[AtomicClaim]:
        self._require_run(run_id)
        query = "SELECT payload_json FROM atomic_claims WHERE run_id=?"
        parameters: tuple[object, ...] = (run_id,)
        if draft_version is not None:
            query += " AND draft_version=?"
            parameters += (draft_version,)
        query += " ORDER BY draft_version,claim_id"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [AtomicClaim.from_dict(json.loads(row[0])) for row in rows]

    def put_claim_verifications(
        self,
        verifications: list[ClaimVerification] | tuple[ClaimVerification, ...],
    ) -> None:
        if not verifications:
            return
        run_id = verifications[0].run_id
        self._require_run(run_id)
        if any(item.run_id != run_id for item in verifications):
            raise ValueError("claim verifications must belong to one run")
        with self._connection() as connection, connection:
            connection.executemany(
                """INSERT INTO claim_verifications
                (verification_id,run_id,claim_id,citation_key,status,blocking,payload_json)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(verification_id) DO UPDATE SET
                status=excluded.status,blocking=excluded.blocking,
                payload_json=excluded.payload_json""",
                [
                    (
                        item.verification_id,
                        item.run_id,
                        item.claim_id,
                        item.citation_key,
                        item.status.value,
                        int(item.blocking),
                        json.dumps(item.to_dict(), sort_keys=True),
                    )
                    for item in verifications
                ],
            )

    def replace_claim_verifications(
        self,
        run_id: str,
        claim_ids: list[str] | tuple[str, ...],
        verifications: list[ClaimVerification] | tuple[ClaimVerification, ...],
    ) -> None:
        self._require_run(run_id)
        unique_claim_ids = tuple(dict.fromkeys(claim_ids))
        if any(
            item.run_id != run_id or item.claim_id not in unique_claim_ids
            for item in verifications
        ):
            raise ValueError(
                "claim verifications must match the supplied run and claims"
            )
        if not unique_claim_ids:
            if verifications:
                raise ValueError("claim_ids cannot be empty when results are supplied")
            return
        placeholders = ",".join("?" for _ in unique_claim_ids)
        with self._connection() as connection, connection:
            rows = connection.execute(
                f"""SELECT claim_id FROM atomic_claims
                WHERE run_id=? AND claim_id IN ({placeholders})""",
                (run_id, *unique_claim_ids),
            ).fetchall()
            if {row["claim_id"] for row in rows} != set(unique_claim_ids):
                raise ValueError("every claim_id must belong to the supplied run")
            connection.execute(
                f"""DELETE FROM claim_verifications
                WHERE run_id=? AND claim_id IN ({placeholders})""",
                (run_id, *unique_claim_ids),
            )
            connection.executemany(
                """INSERT INTO claim_verifications
                (verification_id,run_id,claim_id,citation_key,status,blocking,payload_json)
                VALUES (?,?,?,?,?,?,?)""",
                [
                    (
                        item.verification_id,
                        item.run_id,
                        item.claim_id,
                        item.citation_key,
                        item.status.value,
                        int(item.blocking),
                        json.dumps(item.to_dict(), sort_keys=True),
                    )
                    for item in verifications
                ],
            )

    def list_claim_verifications(
        self,
        run_id: str,
        *,
        claim_id: str | None = None,
        blocking_only: bool = False,
    ) -> list[ClaimVerification]:
        self._require_run(run_id)
        query = "SELECT payload_json FROM claim_verifications WHERE run_id=?"
        parameters: tuple[object, ...] = (run_id,)
        if claim_id is not None:
            query += " AND claim_id=?"
            parameters += (claim_id,)
        if blocking_only:
            query += " AND blocking=1"
        query += " ORDER BY claim_id,citation_key,verification_id"
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [ClaimVerification.from_dict(json.loads(row[0])) for row in rows]

    def put_evidence_review_decision(self, decision: EvidenceReviewDecision) -> None:
        self._require_run(decision.run_id)
        with self._connection() as connection, connection:
            connection.execute(
                """INSERT INTO evidence_review_decisions
                (decision_id,run_id,claim_id,action,created_at,payload_json)
                VALUES (?,?,?,?,?,?)""",
                (
                    decision.decision_id,
                    decision.run_id,
                    decision.claim_id,
                    decision.action,
                    decision.created_at,
                    json.dumps(decision.to_dict(), sort_keys=True),
                ),
            )

    def list_evidence_review_decisions(
        self,
        run_id: str,
    ) -> list[EvidenceReviewDecision]:
        self._require_run(run_id)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM evidence_review_decisions
                WHERE run_id=? ORDER BY created_at,decision_id""",
                (run_id,),
            ).fetchall()
        return [EvidenceReviewDecision.from_dict(json.loads(row[0])) for row in rows]

    def upsert_candidate(
        self,
        run_id: str,
        candidate: CandidatePaper,
    ) -> None:
        self._require_run(run_id)
        try:
            existing = self.get_candidate(run_id, candidate.candidate_id)
        except CandidateNotFoundError:
            merged = candidate
        else:
            merged = replace(
                candidate,
                year=(
                    candidate.year if candidate.year is not None else existing.year
                ),
                venue=candidate.venue or existing.venue,
                abstract=candidate.abstract or existing.abstract,
                doi=candidate.doi or existing.doi,
                arxiv_id=candidate.arxiv_id or existing.arxiv_id,
                semantic_scholar_id=(
                    candidate.semantic_scholar_id or existing.semantic_scholar_id
                ),
                source_urls=tuple(
                    sorted(set(existing.source_urls) | set(candidate.source_urls))
                ),
                open_access_pdf_url=(
                    candidate.open_access_pdf_url or existing.open_access_pdf_url
                ),
                provenance=tuple(
                    sorted(set(existing.provenance) | set(candidate.provenance))
                ),
                status=CandidateStatus.PENDING,
            )
            merged = replace(
                merged,
                status=(
                    existing.status
                    if existing.approval_fingerprint()
                    == merged.approval_fingerprint()
                    else CandidateStatus.PENDING
                ),
            )
        payload = merged.to_dict()
        with self._connection() as connection, connection:
            connection.execute(
                """INSERT INTO candidate_papers
                (run_id,candidate_id,status,recommendation,payload_json)
                VALUES (?,?,?,?,?)
                ON CONFLICT(run_id,candidate_id) DO UPDATE SET
                status=excluded.status,
                recommendation=excluded.recommendation,
                payload_json=excluded.payload_json""",
                (
                    run_id,
                    merged.candidate_id,
                    merged.status.value,
                    merged.recommendation.value,
                    json.dumps(payload, sort_keys=True),
                ),
            )

    def get_candidate(
        self,
        run_id: str,
        candidate_id: str,
    ) -> CandidatePaper:
        self._require_run(run_id)
        with self._connection() as connection:
            row = connection.execute(
                """SELECT payload_json,status FROM candidate_papers
                WHERE run_id=? AND candidate_id=?""",
                (run_id, candidate_id),
            ).fetchone()
        if row is None:
            raise CandidateNotFoundError(candidate_id)
        payload = json.loads(row["payload_json"])
        payload["status"] = row["status"]
        return CandidatePaper.from_dict(payload)

    def list_candidates(
        self,
        run_id: str,
        *,
        status: CandidateStatus | None = None,
        recommendation: ScreeningRecommendation | None = None,
    ) -> list[CandidatePaper]:
        self._require_run(run_id)
        clauses = ["run_id=?"]
        values: list[object] = [run_id]
        if status is not None:
            clauses.append("status=?")
            values.append(status.value)
        if recommendation is not None:
            clauses.append("recommendation=?")
            values.append(recommendation.value)
        with self._connection() as connection:
            rows = connection.execute(
                f"""SELECT candidate_id FROM candidate_papers
                WHERE {" AND ".join(clauses)} ORDER BY candidate_id""",
                values,
            ).fetchall()
        return [self.get_candidate(run_id, row["candidate_id"]) for row in rows]

    def list_candidate_counts_by_run(
        self,
    ) -> dict[str, dict[CandidateStatus, int]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT run_id,status,COUNT(*) AS candidate_count
                FROM candidate_papers GROUP BY run_id,status"""
            ).fetchall()
        counts: dict[str, dict[CandidateStatus, int]] = {}
        for row in rows:
            counts.setdefault(row["run_id"], {})[
                CandidateStatus(row["status"])
            ] = row["candidate_count"]
        return counts

    def append_corpus_decision(
        self,
        decision: CorpusDecision,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        details = dict(details or {})
        with self._connection() as connection, connection:
            run_row = connection.execute(
                "SELECT status,current_stage FROM runs WHERE run_id=?",
                (decision.run_id,),
            ).fetchone()
            if run_row is None:
                raise RunNotFoundError(decision.run_id)
            if (
                run_row["status"] != RunStatus.WAITING.value
                or run_row["current_stage"]
                != WorkflowStage.AWAITING_CORPUS_APPROVAL.value
            ):
                raise CandidateDecisionNotAllowedError(
                    decision.run_id,
                    decision.candidate_id,
                    "candidate decisions require a run waiting for corpus approval",
                )

            candidate_row = connection.execute(
                """SELECT status,payload_json FROM candidate_papers
                WHERE run_id=? AND candidate_id=?""",
                (decision.run_id, decision.candidate_id),
            ).fetchone()
            if candidate_row is None:
                raise CandidateNotFoundError(decision.candidate_id)
            if candidate_row["status"] != CandidateStatus.PENDING.value:
                raise CandidateDecisionNotAllowedError(
                    decision.run_id,
                    decision.candidate_id,
                    "candidate decision is already final",
                )

            candidate_payload = json.loads(candidate_row["payload_json"])
            candidate_payload["status"] = candidate_row["status"]
            candidate = CandidatePaper.from_dict(candidate_payload)
            updated = replace(candidate, status=decision.status)
            payload = updated.to_dict()
            connection.execute(
                """INSERT INTO corpus_decisions VALUES (?,?,?,?,?,?,?,?)""",
                (
                    decision.decision_id,
                    decision.run_id,
                    decision.candidate_id,
                    decision.status.value,
                    decision.reason,
                    decision.actor,
                    decision.created_at,
                    json.dumps(details, sort_keys=True),
                ),
            )
            connection.execute(
                """UPDATE candidate_papers SET status=?,payload_json=?
                WHERE run_id=? AND candidate_id=?""",
                (
                    decision.status.value,
                    json.dumps(payload, sort_keys=True),
                    decision.run_id,
                    decision.candidate_id,
                ),
            )

    def list_corpus_decisions(
        self,
        run_id: str,
    ) -> list[tuple[CorpusDecision, dict[str, object]]]:
        self._require_run(run_id)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT * FROM corpus_decisions
                WHERE run_id=? ORDER BY created_at,decision_id""",
                (run_id,),
            ).fetchall()
        return [
            (
                CorpusDecision(
                    row["decision_id"],
                    row["run_id"],
                    row["candidate_id"],
                    CandidateStatus(row["status"]),
                    row["reason"],
                    row["actor"],
                    row["created_at"],
                ),
                json.loads(row["details_json"]),
            )
            for row in rows
        ]


class SQLiteResponseCache:
    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        self.clock = clock
        SQLiteWorkflowStore(self.path).initialize()

    def get(self, key: str) -> bytes | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """SELECT value,expires_at FROM provider_response_cache
                WHERE cache_key=?""",
                (key,),
            ).fetchone()
            if row is None:
                return None
            if row[1] <= self.clock():
                with connection:
                    connection.execute(
                        "DELETE FROM provider_response_cache WHERE cache_key=?",
                        (key,),
                    )
                return None
            return bytes(row[0])

    def put(self, key: str, value: bytes, ttl_seconds: int) -> None:
        with sqlite3.connect(self.path) as connection, connection:
            connection.execute(
                "DELETE FROM provider_response_cache WHERE expires_at<=?",
                (self.clock(),),
            )
            connection.execute(
                """INSERT INTO provider_response_cache
                (cache_key,value,expires_at) VALUES (?,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET
                value=excluded.value,expires_at=excluded.expires_at""",
                (key, value, self.clock() + ttl_seconds),
            )

    def prune_expired(self) -> int:
        with sqlite3.connect(self.path) as connection, connection:
            cursor = connection.execute(
                "DELETE FROM provider_response_cache WHERE expires_at<=?",
                (self.clock(),),
            )
            return cursor.rowcount


__all__ = [
    "CandidateDecisionNotAllowedError",
    "CandidateNotFoundError",
    "RunAlreadyExistsError",
    "RunNotFoundError",
    "SQLiteWorkflowStore",
    "SQLiteResponseCache",
    "UnsupportedSchemaVersionError",
    "WorkflowStoreError",
]
