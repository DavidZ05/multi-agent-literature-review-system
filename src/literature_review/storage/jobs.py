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
        values["request_json"] = self._optional_json(values.pop("request"))
        with self._connection() as connection, connection:
            connection.execute(
                """INSERT INTO workflow_jobs
                (job_id,kind,status,equivalent_command,run_id,result_json,
                 error_json,request_json,recovery_count,created_at,updated_at)
                VALUES (:job_id,:kind,:status,:equivalent_command,:run_id,
                        :result_json,:error_json,:request_json,:recovery_count,
                        :created_at,:updated_at)
                ON CONFLICT(job_id) DO UPDATE SET
                kind=excluded.kind,status=excluded.status,
                equivalent_command=excluded.equivalent_command,
                run_id=excluded.run_id,result_json=excluded.result_json,
                error_json=excluded.error_json,request_json=excluded.request_json,
                recovery_count=excluded.recovery_count,
                updated_at=excluded.updated_at""",
                values,
            )
            connection.execute(
                """INSERT INTO workbench_events
                (event_type,resource_id,payload_json,created_at)
                VALUES ('job.updated',?,?,?)""",
                (
                    job.job_id,
                    json.dumps(
                        {
                            "job_id": job.job_id,
                            "kind": job.kind,
                            "run_id": job.run_id,
                            "status": job.status,
                            "recovery_count": job.recovery_count,
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                    job.updated_at,
                ),
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
            active = connection.execute(
                """SELECT job_id,kind,run_id FROM workflow_jobs
                WHERE status IN ('queued','running')"""
            ).fetchall()
            updated_at = utc_now_iso()
            cursor = connection.execute(
                """UPDATE workflow_jobs
                SET status='interrupted',error_json=?,updated_at=?
                WHERE status IN ('queued','running')""",
                (error_json, updated_at),
            )
            for row in active:
                connection.execute(
                    """INSERT INTO workbench_events
                    (event_type,resource_id,payload_json,created_at)
                    VALUES ('job.updated',?,?,?)""",
                    (
                        row["job_id"],
                        json.dumps(
                            {
                                "job_id": row["job_id"],
                                "kind": row["kind"],
                                "run_id": row["run_id"],
                                "status": "interrupted",
                            },
                            ensure_ascii=True,
                            sort_keys=True,
                        ),
                        updated_at,
                    ),
                )
            return cursor.rowcount

    def list_workbench_events(
        self: _SQLiteConnectionProvider,
        *,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        if isinstance(after_id, bool) or after_id < 0:
            raise ValueError("after_id must be a nonnegative integer")
        if isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT event_id,event_type,resource_id,payload_json,created_at
                FROM workbench_events WHERE event_id>? ORDER BY event_id ASC
                LIMIT ?""",
                (after_id, limit),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "resource_id": row["resource_id"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def latest_workbench_event_id(self: _SQLiteConnectionProvider) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(event_id), 0) AS event_id FROM workbench_events"
            ).fetchone()
        return int(row["event_id"])

    def prune_workbench_events(
        self: _SQLiteConnectionProvider,
        *,
        keep: int = 20_000,
    ) -> int:
        if isinstance(keep, bool) or keep < 1:
            raise ValueError("keep must be a positive integer")
        with self._connection() as connection, connection:
            cursor = connection.execute(
                """DELETE FROM workbench_events WHERE event_id < COALESCE(
                    (SELECT event_id FROM workbench_events
                     ORDER BY event_id DESC LIMIT 1 OFFSET ?),
                    0
                )""",
                (keep - 1,),
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
                "request": (
                    None if row["request_json"] is None
                    else json.loads(row["request_json"])
                ),
                "recovery_count": row["recovery_count"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )


__all__ = ["SQLiteJobRepositoryMixin"]
