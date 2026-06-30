from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from src.literature_review.models import (
    ResearchRun,
    StageCheckpoint,
    WorkflowEvent,
    WorkflowStage,
    utc_now_iso,
)


class WorkflowStoreError(RuntimeError):
    pass


class RunAlreadyExistsError(WorkflowStoreError):
    pass


class RunNotFoundError(WorkflowStoreError):
    pass


class UnsupportedSchemaVersionError(WorkflowStoreError):
    pass


class SQLiteWorkflowStore:
    SCHEMA_VERSION = 1

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
            if version == self.SCHEMA_VERSION:
                return
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
                        PRIMARY KEY (run_id, stage)
                    );
                    PRAGMA user_version = 1;
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
                (run_id,stage,input_fingerprint,output_hashes_json,status,created_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(run_id,stage) DO UPDATE SET
                input_fingerprint=excluded.input_fingerprint,
                output_hashes_json=excluded.output_hashes_json,
                status=excluded.status,created_at=excluded.created_at""",
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
            }
        )


__all__ = [
    "RunAlreadyExistsError",
    "RunNotFoundError",
    "SQLiteWorkflowStore",
    "UnsupportedSchemaVersionError",
    "WorkflowStoreError",
]
