from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class RunStatus(str, Enum):
    ACTIVE = "active"
    WAITING = "waiting"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStage(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    DISCOVERING = "discovering"
    SCREENING = "screening"
    AWAITING_CORPUS_APPROVAL = "awaiting_corpus_approval"
    DRAFTING = "drafting"
    REVIEWING = "reviewing"
    REVISING = "revising"
    POLISHING = "polishing"
    FINAL_VERIFICATION = "final_verification"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ResearchRun:
    run_id: str
    topic: str
    status: RunStatus
    current_stage: WorkflowStage
    created_at: str
    updated_at: str
    corpus_version: int
    revision_count: int

    @classmethod
    def create(cls, topic: str) -> ResearchRun:
        normalized_topic = topic.strip()
        if not normalized_topic:
            raise ValueError("topic must be nonblank")

        timestamp = utc_now_iso()
        return cls(
            run_id=f"run_{uuid4().hex}",
            topic=normalized_topic,
            status=RunStatus.ACTIVE,
            current_stage=WorkflowStage.CREATED,
            created_at=timestamp,
            updated_at=timestamp,
            corpus_version=1,
            revision_count=0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "topic": self.topic,
            "status": self.status.value,
            "current_stage": self.current_stage.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "corpus_version": self.corpus_version,
            "revision_count": self.revision_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchRun:
        return cls(
            run_id=data["run_id"],
            topic=data["topic"],
            status=RunStatus(data["status"]),
            current_stage=WorkflowStage(data["current_stage"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            corpus_version=data["corpus_version"],
            revision_count=data["revision_count"],
        )


@dataclass(frozen=True)
class WorkflowEvent:
    event_id: int | None
    run_id: str
    event_type: str
    stage: WorkflowStage | None
    payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "stage": None if self.stage is None else self.stage.value,
            "payload": deepcopy(self.payload),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowEvent:
        stage_value = data["stage"]
        return cls(
            event_id=data["event_id"],
            run_id=data["run_id"],
            event_type=data["event_type"],
            stage=None if stage_value is None else WorkflowStage(stage_value),
            payload=deepcopy(dict(data["payload"])),
            created_at=data["created_at"],
        )


@dataclass(frozen=True)
class StageCheckpoint:
    run_id: str
    stage: WorkflowStage
    input_fingerprint: str
    output_artifact_hashes: dict[str, str]
    status: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "stage": self.stage.value,
            "input_fingerprint": self.input_fingerprint,
            "output_artifact_hashes": dict(self.output_artifact_hashes),
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageCheckpoint:
        return cls(
            run_id=data["run_id"],
            stage=WorkflowStage(data["stage"]),
            input_fingerprint=data["input_fingerprint"],
            output_artifact_hashes=dict(data["output_artifact_hashes"]),
            status=data["status"],
            created_at=data["created_at"],
        )


__all__ = [
    "ResearchRun",
    "RunStatus",
    "StageCheckpoint",
    "WorkflowEvent",
    "WorkflowStage",
    "utc_now_iso",
]
