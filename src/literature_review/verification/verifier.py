from __future__ import annotations

from collections import Counter
import hashlib
import json
import re

from src.literature_review.documents import DocumentRecord, DocumentStatus, EvidenceChunk
from src.literature_review.verification.models import (
    AtomicClaim,
    ClaimVerification,
    VerificationStatus,
)
from src.literature_review.verification.retrieval import CitationScopedRetriever


class ClaimVerifier:
    VERSION = "deterministic-v1"

    def __init__(
        self,
        retriever: CitationScopedRetriever | None = None,
        *,
        supported_coverage: float = 0.58,
        partial_coverage: float = 0.30,
    ) -> None:
        if not 0.0 < partial_coverage < supported_coverage <= 1.0:
            raise ValueError("verification coverage thresholds are invalid")
        self.retriever = retriever or CitationScopedRetriever()
        self.supported_coverage = supported_coverage
        self.partial_coverage = partial_coverage

    def verify(
        self,
        claims: tuple[AtomicClaim, ...] | list[AtomicClaim],
        documents: tuple[DocumentRecord, ...] | list[DocumentRecord],
        chunks: tuple[EvidenceChunk, ...] | list[EvidenceChunk],
    ) -> tuple[ClaimVerification, ...]:
        documents_by_key = {document.citation_key: document for document in documents}
        results: list[ClaimVerification] = []
        for claim in claims:
            if not claim.requires_citation:
                continue
            if not claim.citation_keys:
                results.append(
                    self._result(
                        claim,
                        None,
                        VerificationStatus.MISSING_CITATION,
                        (),
                        "This factual claim has no citation key.",
                        1.0,
                        True,
                        None,
                    )
                )
                continue
            for citation_key in claim.citation_keys:
                document = documents_by_key.get(citation_key)
                if document is None or document.status in {
                    DocumentStatus.LOW_QUALITY,
                    DocumentStatus.UNAVAILABLE,
                    DocumentStatus.FAILED,
                }:
                    results.append(
                        self._result(
                            claim,
                            citation_key,
                            VerificationStatus.FULL_TEXT_UNAVAILABLE,
                            (),
                            "The cited source has no parsed full text available.",
                            1.0,
                            True,
                            document,
                        )
                    )
                    continue
                hits = self.retriever.retrieve(claim.text, citation_key, chunks)
                if not hits:
                    results.append(
                        self._result(
                            claim,
                            citation_key,
                            VerificationStatus.NOT_FOUND,
                            (),
                            "No citation-scoped evidence passage matched the claim.",
                            0.9,
                            True,
                            document,
                        )
                    )
                    continue
                best = hits[0]
                status, reason, confidence = self._assess(claim.text, best.chunk.text, best.claim_coverage)
                selected = tuple(hit.chunk for hit in hits[:3])
                results.append(
                    self._result(
                        claim,
                        citation_key,
                        status,
                        selected,
                        reason,
                        confidence,
                        status != VerificationStatus.SUPPORTED,
                        document,
                    )
                )
        return tuple(results)

    def report(
        self,
        claims: tuple[AtomicClaim, ...] | list[AtomicClaim],
        verifications: tuple[ClaimVerification, ...] | list[ClaimVerification],
    ) -> dict[str, object]:
        counts = Counter(item.status.value for item in verifications)
        blocking = [item for item in verifications if item.blocking]
        return {
            "verifier": self.VERSION,
            "claim_count": len(claims),
            "citation_required_claim_count": sum(claim.requires_citation for claim in claims),
            "verification_count": len(verifications),
            "status_counts": dict(sorted(counts.items())),
            "blocking_count": len(blocking),
            "accepted": not blocking,
            "blocking_claim_ids": sorted({item.claim_id for item in blocking}),
            "claims": [claim.to_dict() for claim in claims],
            "verifications": [item.to_dict() for item in verifications],
        }

    def feedback(
        self,
        claims: tuple[AtomicClaim, ...] | list[AtomicClaim],
        verifications: tuple[ClaimVerification, ...] | list[ClaimVerification],
    ) -> dict[str, object]:
        claims_by_id = {claim.claim_id: claim for claim in claims}
        issues = []
        for item in verifications:
            if not item.blocking:
                continue
            claim = claims_by_id[item.claim_id]
            issues.append(
                {
                    "claim_id": item.claim_id,
                    "claim": claim.text,
                    "section": claim.section,
                    "citation_key": item.citation_key,
                    "status": item.status.value,
                    "reason": item.reason,
                    "required_action": _required_action(item.status),
                }
            )
        return {
            "accepted": not issues,
            "issues": issues,
            "instruction": (
                "Revise or remove every blocking claim. Do not substitute a different citation "
                "unless that source directly supports the revised text."
            ),
        }

    def _assess(
        self,
        claim_text: str,
        evidence_text: str,
        coverage: float,
    ) -> tuple[VerificationStatus, str, float]:
        if _possible_contradiction(claim_text, evidence_text) and coverage >= self.partial_coverage:
            return (
                VerificationStatus.CONTRADICTED,
                "The closest passage has overlapping concepts but opposite polarity; human review is required.",
                min(0.95, 0.55 + coverage / 2),
            )
        if coverage >= self.supported_coverage:
            return (
                VerificationStatus.SUPPORTED,
                "A citation-scoped passage contains the material terms of the claim.",
                min(0.95, 0.55 + coverage / 2),
            )
        if coverage >= self.partial_coverage:
            return (
                VerificationStatus.PARTIALLY_SUPPORTED,
                "The source passage overlaps with the claim but does not cover all material terms.",
                min(0.85, 0.45 + coverage / 2),
            )
        return (
            VerificationStatus.NOT_FOUND,
            "The closest citation-scoped passage has insufficient material-term coverage.",
            min(0.9, 0.6 + (1 - coverage) / 4),
        )

    def _result(
        self,
        claim: AtomicClaim,
        citation_key: str | None,
        status: VerificationStatus,
        evidence: tuple[EvidenceChunk, ...],
        reason: str,
        confidence: float,
        blocking: bool,
        document: DocumentRecord | None,
    ) -> ClaimVerification:
        fingerprint_payload = {
            "version": self.VERSION,
            "claim": claim.text,
            "citation_key": citation_key,
            "document_sha256": document.sha256 if document else None,
            "document_parser": document.parser_version if document else None,
            "evidence_chunk_ids": [chunk.chunk_id for chunk in evidence],
            "supported_coverage": self.supported_coverage,
            "partial_coverage": self.partial_coverage,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ClaimVerification.create(
            run_id=claim.run_id,
            claim_id=claim.claim_id,
            citation_key=citation_key,
            status=status,
            evidence_chunk_ids=tuple(chunk.chunk_id for chunk in evidence),
            evidence_pages=tuple(sorted({page for chunk in evidence for page in range(chunk.page_start, chunk.page_end + 1)})),
            reason=reason,
            confidence=round(confidence, 4),
            verifier=self.VERSION,
            blocking=blocking,
            fingerprint=fingerprint,
        )


def _possible_contradiction(claim: str, evidence: str) -> bool:
    negative = re.compile(r"\b(?:not|no|never|without|failed to|did not|does not)\b", re.IGNORECASE)
    return bool(negative.search(claim)) != bool(negative.search(evidence))


def _required_action(status: VerificationStatus) -> str:
    if status == VerificationStatus.MISSING_CITATION:
        return "Add a verified citation or remove the factual claim."
    if status == VerificationStatus.FULL_TEXT_UNAVAILABLE:
        return "Import an accessible PDF, replace the source, or request a documented risk acceptance."
    if status == VerificationStatus.CONTRADICTED:
        return "Inspect the cited passage and correct or remove the claim."
    return "Narrow, rewrite, or remove the claim using the cited source passage."


__all__ = ["ClaimVerifier"]
