from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from src.literature_review.models import utc_now_iso


ACTIVE_JOB_STATUSES = frozenset({"queued", "running"})
TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "interrupted"})
JOB_STATUSES = ACTIVE_JOB_STATUSES | TERMINAL_JOB_STATUSES


@dataclass(frozen=True)
class WorkflowJob:
    job_id: str
    kind: str
    status: str
    equivalent_command: str
    run_id: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.status not in JOB_STATUSES:
            raise ValueError(f"unsupported job status: {self.status}")
        if not self.created_at or not self.updated_at:
            now = utc_now_iso()
            object.__setattr__(self, "created_at", self.created_at or now)
            object.__setattr__(self, "updated_at", self.updated_at or now)

    def evolve(self, **changes: object) -> WorkflowJob:
        return replace(self, updated_at=utc_now_iso(), **changes)

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "run_id": self.run_id,
            "equivalent_command": self.equivalent_command,
            "result": None if self.result is None else dict(self.result),
            "error": None if self.error is None else dict(self.error),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkflowJob:
        result = value.get("result")
        error = value.get("error")
        return cls(
            job_id=str(value["job_id"]),
            kind=str(value["kind"]),
            status=str(value["status"]),
            run_id=None if value.get("run_id") is None else str(value["run_id"]),
            equivalent_command=str(value["equivalent_command"]),
            result=None if result is None else dict(result),
            error=None if error is None else dict(error),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
        )


__all__ = [
    "ACTIVE_JOB_STATUSES",
    "JOB_STATUSES",
    "TERMINAL_JOB_STATUSES",
    "WorkflowJob",
]
