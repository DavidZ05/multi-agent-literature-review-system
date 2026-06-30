from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_enum(value: Any, enum_type: type[Enum], field_name: str) -> None:
    if not isinstance(value, enum_type):
        raise TypeError(f"{field_name} must be a {enum_type.__name__}")


def _validate_run_id(run_id: str) -> None:
    if not re.fullmatch(r"run_[0-9a-f]{32}", run_id):
        raise ValueError("run_id must match run_ + 32 lowercase hex characters")


def _parse_utc_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO 8601 timestamp") from exc

    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{field_name} must be timezone-aware UTC")

    return parsed


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

    def __post_init__(self) -> None:
        _validate_run_id(self.run_id)
        normalized_topic = self.topic.strip()
        if not normalized_topic:
            raise ValueError("topic must be nonblank")
        if self.corpus_version < 0:
            raise ValueError("corpus_version must be nonnegative")
        if self.revision_count < 0:
            raise ValueError("revision_count must be nonnegative")

        _require_enum(self.status, RunStatus, "status")
        _require_enum(self.current_stage, WorkflowStage, "current_stage")
        created_at = _parse_utc_timestamp(self.created_at, "created_at")
        updated_at = _parse_utc_timestamp(self.updated_at, "updated_at")
        if updated_at < created_at:
            raise ValueError("updated_at must be greater than or equal to created_at")

        object.__setattr__(self, "topic", normalized_topic)

    @classmethod
    def create(cls, topic: str) -> ResearchRun:
        timestamp = utc_now_iso()
        return cls(
            run_id=f"run_{uuid4().hex}",
            topic=topic,
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
    payload: Mapping[str, Any]
    created_at: str

    def __post_init__(self) -> None:
        _validate_run_id(self.run_id)
        if self.event_id is not None:
            if isinstance(self.event_id, bool) or not isinstance(self.event_id, int):
                raise TypeError("event_id must be a nonnegative int or None")
            if self.event_id < 0:
                raise ValueError("event_id must be nonnegative")
        normalized_event_type = self.event_type.strip()
        if not normalized_event_type:
            raise ValueError("event_type must be nonblank")
        if self.stage is not None:
            _require_enum(self.stage, WorkflowStage, "stage")
        _parse_utc_timestamp(self.created_at, "created_at")
        object.__setattr__(self, "event_type", normalized_event_type)
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "stage": None if self.stage is None else self.stage.value,
            "payload": dict(self.payload),
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
            payload=dict(data["payload"]),
            created_at=data["created_at"],
        )


@dataclass(frozen=True)
class StageCheckpoint:
    run_id: str
    stage: WorkflowStage
    input_fingerprint: str
    output_artifact_hashes: Mapping[str, str]
    status: str
    created_at: str

    def __post_init__(self) -> None:
        _validate_run_id(self.run_id)
        _require_enum(self.stage, WorkflowStage, "stage")
        _parse_utc_timestamp(self.created_at, "created_at")
        object.__setattr__(
            self,
            "output_artifact_hashes",
            MappingProxyType(dict(self.output_artifact_hashes)),
        )

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
