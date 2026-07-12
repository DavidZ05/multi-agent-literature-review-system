from __future__ import annotations

from contextlib import AbstractContextManager
import json
import sqlite3
from typing import Protocol

from src.literature_review.job_state import WorkflowJob
from src.literature_review.models import utc_now_iso


class _SQLiteConnectionProvider(Protocol):
    def _connection(self) -> AbstractContextManager[sqlite3.Connection]: ...


class SQLiteJobRepositoryMixin:
    def put_job(self: _SQLiteConnectionProvider, job: WorkflowJob) -> None:
        values = job.to_dict()
        values["result_json"] = self._optional_json(values.pop("result"))
        values["error_json"] = self._optional_json(values.pop("error"))
        with self._connection() as connection, connection:
            connection.execute(
                """INSERT INTO workflow_jobs
                (job_id,kind,status,equivalent_command,run_id,result_json,
                 error_json,created_at,updated_at)
                VALUES (:job_id,:kind,:status,:equivalent_command,:run_id,
                        :result_json,:error_json,:created_at,:updated_at)
                ON CONFLICT(job_id) DO UPDATE SET
                kind=excluded.kind,status=excluded.status,
                equivalent_command=excluded.equivalent_command,
                run_id=excluded.run_id,result_json=excluded.result_json,
                error_json=excluded.error_json,updated_at=excluded.updated_at""",
                values,
            )

    def get_job(
        self: _SQLiteConnectionProvider,
        job_id: str,
    ) -> WorkflowJob | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return None if row is None else self._job_from_row(row)

    def list_jobs(self: _SQLiteConnectionProvider) -> list[WorkflowJob]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_jobs ORDER BY created_at ASC, job_id ASC"
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def delete_job(self: _SQLiteConnectionProvider, job_id: str) -> None:
        with self._connection() as connection, connection:
            connection.execute("DELETE FROM workflow_jobs WHERE job_id=?", (job_id,))

    def interrupt_active_jobs(self: _SQLiteConnectionProvider) -> int:
        error_json = json.dumps(
            {
                "type": "backend_restarted",
                "message": "The Workbench backend stopped before this Job finished.",
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        with self._connection() as connection, connection:
            cursor = connection.execute(
                """UPDATE workflow_jobs
                SET status='interrupted',error_json=?,updated_at=?
                WHERE status IN ('queued','running')""",
                (error_json, utc_now_iso()),
            )
            return cursor.rowcount

    @staticmethod
    def _optional_json(value: object) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=True, sort_keys=True)

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> WorkflowJob:
        return WorkflowJob.from_dict(
            {
                "job_id": row["job_id"],
                "kind": row["kind"],
                "status": row["status"],
                "equivalent_command": row["equivalent_command"],
                "run_id": row["run_id"],
                "result": (
                    None if row["result_json"] is None
                    else json.loads(row["result_json"])
                ),
                "error": (
                    None if row["error_json"] is None
                    else json.loads(row["error_json"])
                ),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )


__all__ = ["SQLiteJobRepositoryMixin"]
