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
    PAUSED = "paused"
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
    ACQUIRING_DOCUMENTS = "acquiring_documents"
    INDEXING_EVIDENCE = "indexing_evidence"
    DRAFTING = "drafting"
    REVIEWING = "reviewing"
    REVISING = "revising"
    POLISHING = "polishing"
    FINAL_VERIFICATION = "final_verification"
    CLAIM_VERIFICATION = "claim_verification"
    AWAITING_EVIDENCE_REVIEW = "awaiting_evidence_review"
    COMPLETED = "completed"


class CandidateStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ScreeningRecommendation(str, Enum):
    INCLUDE = "include"
    REVIEW = "review"
    EXCLUDE = "exclude"


_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _validate_provider(provider: str) -> None:
    if not isinstance(provider, str) or not _PROVIDER_ID.fullmatch(provider):
        raise ValueError(f"invalid provider id: {provider}")


def _validate_paper_fields(
    title: str,
    authors: tuple[str, ...],
    year: int | None,
) -> None:
    if not title.strip():
        raise ValueError("title must be nonblank")
    if not authors or any(not author.strip() for author in authors):
        raise ValueError("authors must contain nonblank names")
    if year is not None and (year < 1000 or year > 9999):
        raise ValueError("year must be a four-digit year or None")


@dataclass(frozen=True)
class SearchQuery:
    query_id: str
    text: str
    provider: str
    max_results: int
    year_from: int | None
    year_to: int | None
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        _validate_provider(self.provider)
        if not self.query_id.strip() or not self.text.strip():
            raise ValueError("query_id and text must be nonblank")
        if self.attempt_id is not None and not re.fullmatch(
            r"attempt_[0-9a-f]{32}", self.attempt_id
        ):
            raise ValueError("attempt_id must match attempt_ + 32 lowercase hex characters")
        if self.max_results < 1:
            raise ValueError("max_results must be positive")
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must not exceed year_to")

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "text": self.text,
            "provider": self.provider,
            "max_results": self.max_results,
            "year_from": self.year_from,
            "year_to": self.year_to,
            "attempt_id": self.attempt_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SearchQuery:
        return cls(**dict(data))


@dataclass(frozen=True)
class DiscoveryAttempt:
    attempt_id: str
    run_id: str
    status: str
    providers: tuple[str, ...]
    query_texts: tuple[str, ...]
    max_results: int
    raw_result_count: int
    normalized_count: int
    deduplicated_count: int
    screened_count: int
    new_candidate_count: int
    failed_providers: tuple[str, ...]
    created_at: str
    completed_at: str | None = None

    _STATUSES = frozenset(
        {"running", "succeeded", "partial", "failed", "cancelled", "interrupted"}
    )

    def __post_init__(self) -> None:
        if not re.fullmatch(r"attempt_[0-9a-f]{32}", self.attempt_id):
            raise ValueError("attempt_id must match attempt_ + 32 lowercase hex characters")
        _validate_run_id(self.run_id)
        if self.status not in self._STATUSES:
            raise ValueError("invalid discovery attempt status")
        if not self.providers:
            raise ValueError("discovery attempt providers must be nonempty")
        for provider in self.providers:
            _validate_provider(provider)
        if any(not query.strip() for query in self.query_texts):
            raise ValueError("discovery attempt query_texts must be nonblank")
        if not 1 <= self.max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")
        counts = (
            self.raw_result_count,
            self.normalized_count,
            self.deduplicated_count,
            self.screened_count,
            self.new_candidate_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts
        ):
            raise ValueError("discovery attempt counts must be nonnegative integers")
        for provider in self.failed_providers:
            _validate_provider(provider)
        _parse_utc_timestamp(self.created_at, "created_at")
        if self.completed_at is not None:
            _parse_utc_timestamp(self.completed_at, "completed_at")
        object.__setattr__(self, "providers", tuple(self.providers))
        object.__setattr__(self, "query_texts", tuple(self.query_texts))
        object.__setattr__(self, "failed_providers", tuple(self.failed_providers))

    @classmethod
    def create(
        cls,
        run_id: str,
        providers: tuple[str, ...],
        query_texts: tuple[str, ...],
        max_results: int,
    ) -> DiscoveryAttempt:
        return cls(
            attempt_id=f"attempt_{uuid4().hex}",
            run_id=run_id,
            status="running",
            providers=providers,
            query_texts=query_texts,
            max_results=max_results,
            raw_result_count=0,
            normalized_count=0,
            deduplicated_count=0,
            screened_count=0,
            new_candidate_count=0,
            failed_providers=(),
            created_at=utc_now_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "status": self.status,
            "providers": list(self.providers),
            "query_texts": list(self.query_texts),
            "max_results": self.max_results,
            "raw_result_count": self.raw_result_count,
            "normalized_count": self.normalized_count,
            "deduplicated_count": self.deduplicated_count,
            "screened_count": self.screened_count,
            "new_candidate_count": self.new_candidate_count,
            "failed_providers": list(self.failed_providers),
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DiscoveryAttempt:
        values = dict(data)
        values["providers"] = tuple(values["providers"])
        values["query_texts"] = tuple(values.get("query_texts", ()))
        values["failed_providers"] = tuple(values.get("failed_providers", ()))
        return cls(**values)


@dataclass(frozen=True)
class ProviderPaper:
    provider: str
    provider_id: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    venue: str | None
    abstract: str | None
    doi: str | None
    arxiv_id: str | None
    semantic_scholar_id: str | None
    source_url: str
    open_access_pdf_url: str | None

    def __post_init__(self) -> None:
        _validate_provider(self.provider)
        _validate_paper_fields(self.title, self.authors, self.year)
        if not self.provider_id.strip() or not self.source_url.strip():
            raise ValueError("provider_id and source_url must be nonblank")

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["authors"] = list(self.authors)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProviderPaper:
        values = dict(data)
        values["authors"] = tuple(values["authors"])
        return cls(**values)


@dataclass(frozen=True)
class ProviderSearchResult:
    provider: str
    query_id: str
    request_url: str
    papers: tuple[ProviderPaper, ...]
    raw_body: bytes
    response_headers: Mapping[str, str]

    def __post_init__(self) -> None:
        _validate_provider(self.provider)
        object.__setattr__(self, "papers", tuple(self.papers))
        object.__setattr__(
            self,
            "response_headers",
            MappingProxyType(dict(self.response_headers)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "query_id": self.query_id,
            "request_url": self.request_url,
            "papers": [paper.to_dict() for paper in self.papers],
            "response_headers": dict(self.response_headers),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProviderSearchResult:
        return cls(
            provider=data["provider"],
            query_id=data["query_id"],
            request_url=data["request_url"],
            papers=tuple(ProviderPaper.from_dict(paper) for paper in data["papers"]),
            raw_body=b"",
            response_headers=dict(data["response_headers"]),
        )


@dataclass(frozen=True)
class CandidatePaper:
    candidate_id: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    venue: str | None
    abstract: str | None
    doi: str | None
    arxiv_id: str | None
    semantic_scholar_id: str | None
    source_urls: tuple[str, ...]
    open_access_pdf_url: str | None
    provenance: tuple[str, ...]
    recommendation: ScreeningRecommendation
    relevance_score: float
    status: CandidateStatus

    def __post_init__(self) -> None:
        _validate_paper_fields(self.title, self.authors, self.year)
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must be nonblank")
        if not any((self.doi, self.arxiv_id, self.semantic_scholar_id)):
            raise ValueError("candidate requires a stable identifier")
        if not 0.0 <= self.relevance_score <= 1.0:
            raise ValueError("relevance_score must be between 0 and 1")
        _require_enum(
            self.recommendation,
            ScreeningRecommendation,
            "recommendation",
        )
        _require_enum(self.status, CandidateStatus, "status")
        object.__setattr__(self, "authors", tuple(self.authors))
        object.__setattr__(self, "source_urls", tuple(self.source_urls))
        object.__setattr__(self, "provenance", tuple(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "venue": self.venue,
            "abstract": self.abstract,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "semantic_scholar_id": self.semantic_scholar_id,
            "source_urls": list(self.source_urls),
            "open_access_pdf_url": self.open_access_pdf_url,
            "provenance": list(self.provenance),
            "recommendation": self.recommendation.value,
            "relevance_score": self.relevance_score,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CandidatePaper:
        values = dict(data)
        values["authors"] = tuple(values["authors"])
        values["source_urls"] = tuple(values["source_urls"])
        values["provenance"] = tuple(values["provenance"])
        values["recommendation"] = ScreeningRecommendation(values["recommendation"])
        values["status"] = CandidateStatus(values["status"])
        return cls(**values)


@dataclass(frozen=True)
class CorpusDecision:
    decision_id: str
    run_id: str
    candidate_id: str
    status: CandidateStatus
    reason: str
    actor: str
    created_at: str

    def __post_init__(self) -> None:
        _validate_run_id(self.run_id)
        _require_enum(self.status, CandidateStatus, "status")
        if self.status == CandidateStatus.PENDING:
            raise ValueError("a decision cannot set pending status")
        if not all(
            value.strip()
            for value in (
                self.decision_id,
                self.candidate_id,
                self.reason,
                self.actor,
            )
        ):
            raise ValueError("decision fields must be nonblank")
        _parse_utc_timestamp(self.created_at, "created_at")

    @classmethod
    def create(
        cls,
        run_id: str,
        candidate_id: str,
        status: CandidateStatus,
        reason: str,
        actor: str,
    ) -> CorpusDecision:
        return cls(
            decision_id=f"decision_{uuid4().hex}",
            run_id=run_id,
            candidate_id=candidate_id,
            status=status,
            reason=reason,
            actor=actor,
            created_at=utc_now_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CorpusDecision:
        values = dict(data)
        values["status"] = CandidateStatus(values["status"])
        return cls(**values)


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
    next_stage: WorkflowStage | None = None

    def __post_init__(self) -> None:
        _validate_run_id(self.run_id)
        _require_enum(self.stage, WorkflowStage, "stage")
        if self.next_stage is not None:
            _require_enum(self.next_stage, WorkflowStage, "next_stage")
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
            "next_stage": (None if self.next_stage is None else self.next_stage.value),
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
            next_stage=(
                None
                if data.get("next_stage") is None
                else WorkflowStage(data["next_stage"])
            ),
        )


__all__ = [
    "CandidatePaper",
    "CandidateStatus",
    "CorpusDecision",
    "ProviderPaper",
    "ProviderSearchResult",
    "ResearchRun",
    "RunStatus",
    "ScreeningRecommendation",
    "SearchQuery",
    "StageCheckpoint",
    "WorkflowEvent",
    "WorkflowStage",
    "utc_now_iso",
]
