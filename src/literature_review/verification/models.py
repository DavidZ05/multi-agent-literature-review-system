from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Mapping
from uuid import uuid4

from src.literature_review.citations import validate_citation_key
from src.literature_review.models import utc_now_iso


_RUN_ID = re.compile(r"run_[0-9a-f]{32}")
_CLAIM_ID = re.compile(r"claim_[0-9a-f]{32}")
_VERIFICATION_ID = re.compile(r"verification_[0-9a-f]{32}")
_CHUNK_ID = re.compile(r"chunk_[0-9a-f]{32}")
_DECISION_ID = re.compile(r"evidence_decision_[0-9a-f]{32}")


def _validate_utc_timestamp(value: str, field_name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


class ClaimType(str, Enum):
    FACTUAL = "factual"
    SYNTHESIS = "synthesis"
    OPINION = "opinion"
    TRANSITION = "transition"
    SCOPE = "scope"


class VerificationStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    NOT_FOUND = "not_found"
    FULL_TEXT_UNAVAILABLE = "full_text_unavailable"
    MISSING_CITATION = "missing_citation"


@dataclass(frozen=True)
class AtomicClaim:
    claim_id: str
    run_id: str
    draft_version: int
    text: str
    claim_type: ClaimType
    citation_keys: tuple[str, ...]
    section: str
    paragraph_index: int
    sentence_index: int
    requires_citation: bool

    def __post_init__(self) -> None:
        if not _CLAIM_ID.fullmatch(self.claim_id) or not _RUN_ID.fullmatch(self.run_id):
            raise ValueError("invalid claim_id or run_id")
        if not isinstance(self.draft_version, int) or isinstance(self.draft_version, bool) or self.draft_version < 1:
            raise ValueError("draft_version must be positive")
        if not self.text.strip() or not self.section.strip():
            raise ValueError("claim text and section must be nonblank")
        if not isinstance(self.claim_type, ClaimType):
            raise TypeError("claim_type must be a ClaimType")
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in (self.paragraph_index, self.sentence_index)
        ) or self.paragraph_index < 0 or self.sentence_index < 0:
            raise ValueError("claim positions must be nonnegative")
        if not isinstance(self.requires_citation, bool):
            raise TypeError("requires_citation must be a bool")
        for key in self.citation_keys:
            validate_citation_key(key)
        object.__setattr__(self, "citation_keys", tuple(dict.fromkeys(self.citation_keys)))

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        draft_version: int,
        text: str,
        claim_type: ClaimType,
        citation_keys: tuple[str, ...],
        section: str,
        paragraph_index: int,
        sentence_index: int,
        requires_citation: bool,
    ) -> AtomicClaim:
        identity = "\0".join(
            (
                run_id,
                str(draft_version),
                section,
                str(paragraph_index),
                str(sentence_index),
                text.strip(),
                "|".join(citation_keys),
            )
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        return cls(
            claim_id=f"claim_{digest}",
            run_id=run_id,
            draft_version=draft_version,
            text=text.strip(),
            claim_type=claim_type,
            citation_keys=citation_keys,
            section=section,
            paragraph_index=paragraph_index,
            sentence_index=sentence_index,
            requires_citation=requires_citation,
        )

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["claim_type"] = self.claim_type.value
        data["citation_keys"] = list(self.citation_keys)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AtomicClaim:
        values = dict(data)
        values["claim_type"] = ClaimType(values["claim_type"])
        values["citation_keys"] = tuple(values["citation_keys"])
        return cls(**values)


@dataclass(frozen=True)
class ClaimVerification:
    verification_id: str
    run_id: str
    claim_id: str
    citation_key: str | None
    status: VerificationStatus
    evidence_chunk_ids: tuple[str, ...]
    evidence_pages: tuple[int, ...]
    reason: str
    confidence: float
    verifier: str
    blocking: bool
    fingerprint: str
    created_at: str

    def __post_init__(self) -> None:
        if not _VERIFICATION_ID.fullmatch(self.verification_id):
            raise ValueError("invalid verification_id")
        if not _RUN_ID.fullmatch(self.run_id) or not _CLAIM_ID.fullmatch(self.claim_id):
            raise ValueError("invalid run_id or claim_id")
        if not isinstance(self.status, VerificationStatus):
            raise TypeError("status must be a VerificationStatus")
        if any(not _CHUNK_ID.fullmatch(chunk_id) for chunk_id in self.evidence_chunk_ids):
            raise ValueError("invalid evidence chunk id")
        if any(page < 1 for page in self.evidence_pages):
            raise ValueError("evidence pages must be positive")
        if not self.reason.strip() or not self.verifier.strip():
            raise ValueError("verification reason and verifier must be nonblank")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not re.fullmatch(r"[0-9a-f]{64}", self.fingerprint):
            raise ValueError("fingerprint must contain 64 lowercase hex characters")
        if not isinstance(self.blocking, bool):
            raise TypeError("blocking must be a bool")
        _validate_utc_timestamp(self.created_at, "created_at")
        object.__setattr__(self, "evidence_chunk_ids", tuple(self.evidence_chunk_ids))
        object.__setattr__(self, "evidence_pages", tuple(self.evidence_pages))

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        claim_id: str,
        citation_key: str | None,
        status: VerificationStatus,
        evidence_chunk_ids: tuple[str, ...],
        evidence_pages: tuple[int, ...],
        reason: str,
        confidence: float,
        verifier: str,
        blocking: bool,
        fingerprint: str,
    ) -> ClaimVerification:
        identity = "\0".join((claim_id, citation_key or "", fingerprint))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        return cls(
            verification_id=f"verification_{digest}",
            run_id=run_id,
            claim_id=claim_id,
            citation_key=citation_key,
            status=status,
            evidence_chunk_ids=evidence_chunk_ids,
            evidence_pages=evidence_pages,
            reason=reason,
            confidence=confidence,
            verifier=verifier,
            blocking=blocking,
            fingerprint=fingerprint,
            created_at=utc_now_iso(),
        )

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["status"] = self.status.value
        data["evidence_chunk_ids"] = list(self.evidence_chunk_ids)
        data["evidence_pages"] = list(self.evidence_pages)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ClaimVerification:
        values = dict(data)
        values["status"] = VerificationStatus(values["status"])
        values["evidence_chunk_ids"] = tuple(values["evidence_chunk_ids"])
        values["evidence_pages"] = tuple(values["evidence_pages"])
        return cls(**values)


@dataclass(frozen=True)
class EvidenceReviewDecision:
    decision_id: str
    run_id: str
    claim_id: str
    action: str
    reason: str
    actor: str
    created_at: str
    verification_fingerprints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _DECISION_ID.fullmatch(self.decision_id):
            raise ValueError("invalid evidence decision id")
        if not _RUN_ID.fullmatch(self.run_id) or not _CLAIM_ID.fullmatch(self.claim_id):
            raise ValueError("invalid run_id or claim_id")
        if self.action not in {"accept_risk", "require_revision"}:
            raise ValueError("invalid evidence review action")
        if not self.reason.strip() or not self.actor.strip():
            raise ValueError("decision reason and actor must be nonblank")
        if any(
            not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
            for fingerprint in self.verification_fingerprints
        ):
            raise ValueError(
                "verification_fingerprints must contain lowercase SHA-256 values"
            )
        _validate_utc_timestamp(self.created_at, "created_at")
        object.__setattr__(
            self,
            "verification_fingerprints",
            tuple(sorted(set(self.verification_fingerprints))),
        )

    @classmethod
    def create(
        cls,
        run_id: str,
        claim_id: str,
        action: str,
        reason: str,
        actor: str,
        *,
        verification_fingerprints: tuple[str, ...],
    ) -> EvidenceReviewDecision:
        if not verification_fingerprints:
            raise ValueError("evidence decisions require verification fingerprints")
        return cls(
            decision_id=f"evidence_decision_{uuid4().hex}",
            run_id=run_id,
            claim_id=claim_id,
            action=action,
            reason=reason,
            actor=actor,
            created_at=utc_now_iso(),
            verification_fingerprints=verification_fingerprints,
        )

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["verification_fingerprints"] = list(self.verification_fingerprints)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvidenceReviewDecision:
        values = dict(data)
        values["verification_fingerprints"] = tuple(
            values.get("verification_fingerprints", ())
        )
        return cls(**values)

    def applies_to(self, verification_fingerprints: tuple[str, ...]) -> bool:
        return bool(self.verification_fingerprints) and (
            self.verification_fingerprints
            == tuple(sorted(set(verification_fingerprints)))
        )


def active_evidence_decisions(
    verifications: list[ClaimVerification] | tuple[ClaimVerification, ...],
    decisions: list[EvidenceReviewDecision] | tuple[EvidenceReviewDecision, ...],
) -> dict[str, EvidenceReviewDecision]:
    blocking_fingerprints: dict[str, list[str]] = {}
    for verification in verifications:
        if verification.blocking:
            blocking_fingerprints.setdefault(verification.claim_id, []).append(
                verification.fingerprint
            )
    active: dict[str, EvidenceReviewDecision] = {}
    for decision in decisions:
        fingerprints = tuple(blocking_fingerprints.get(decision.claim_id, ()))
        if decision.applies_to(fingerprints):
            active[decision.claim_id] = decision
    return active


__all__ = [
    "AtomicClaim",
    "ClaimType",
    "ClaimVerification",
    "EvidenceReviewDecision",
    "VerificationStatus",
    "active_evidence_decisions",
]
