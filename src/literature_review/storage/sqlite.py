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
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    SearchQuery,
    StageCheckpoint,
    WorkflowEvent,
    WorkflowStage,
    utc_now_iso,
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
    SCHEMA_VERSION = 4

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
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX workflow_jobs_status_created_idx
                        ON workflow_jobs(status, created_at);
                    PRAGMA user_version = 4;
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
                source_urls=tuple(
                    sorted(set(existing.source_urls) | set(candidate.source_urls))
                ),
                provenance=tuple(
                    sorted(set(existing.provenance) | set(candidate.provenance))
                ),
                status=existing.status,
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
