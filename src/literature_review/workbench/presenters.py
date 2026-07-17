from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from src.literature_review.models import CandidatePaper, CandidateStatus
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.verification import active_evidence_decisions


def serialize_candidate_counts(
    counts: Mapping[CandidateStatus, int],
) -> dict[str, int]:
    return {status.value: counts.get(status, 0) for status in CandidateStatus}


def candidate_counts(candidates: Iterable[CandidatePaper]) -> dict[str, int]:
    counts = {status: 0 for status in CandidateStatus}
    for candidate in candidates:
        counts[candidate.status] += 1
    return serialize_candidate_counts(counts)


class EvidencePresenter:
    def __init__(self, store: SQLiteWorkflowStore) -> None:
        self.store = store

    def detail(self, run_id: str) -> dict[str, object]:
        documents = self.store.list_documents(run_id)
        all_claims = self.store.list_claims(run_id)
        latest_version = max(
            (claim.draft_version for claim in all_claims),
            default=0,
        )
        claims = [
            claim for claim in all_claims if claim.draft_version == latest_version
        ]
        verifications = self.store.list_claim_verifications(run_id)
        decisions = self.store.list_evidence_review_decisions(run_id)
        chunks_by_id = {
            chunk.chunk_id: chunk
            for chunk in self.store.list_evidence_chunks(run_id)
        }
        verifications_by_claim: dict[str, list[dict[str, object]]] = {}
        for verification in verifications:
            serialized = verification.to_dict()
            serialized["evidence"] = [
                {
                    **chunks_by_id[chunk_id].to_dict(),
                    "text": chunks_by_id[chunk_id].text[:1200],
                }
                for chunk_id in verification.evidence_chunk_ids
                if chunk_id in chunks_by_id
            ]
            verifications_by_claim.setdefault(verification.claim_id, []).append(
                serialized
            )
        active_decisions = active_evidence_decisions(verifications, decisions)
        decisions_by_claim = {
            claim_id: decision.to_dict()
            for claim_id, decision in active_decisions.items()
        }
        decision_history_by_claim: dict[str, list[dict[str, object]]] = {}
        for decision in decisions:
            decision_history_by_claim.setdefault(decision.claim_id, []).append(
                decision.to_dict()
            )
        claim_rows: list[dict[str, object]] = []
        for claim in claims:
            results = verifications_by_claim.get(claim.claim_id, [])
            claim_rows.append(
                {
                    **claim.to_dict(),
                    "verifications": results,
                    "blocking": any(bool(item["blocking"]) for item in results),
                    "decision": decisions_by_claim.get(claim.claim_id),
                    "decision_history": decision_history_by_claim.get(
                        claim.claim_id,
                        [],
                    ),
                }
            )
        return {
            "enabled": bool(documents or claims),
            "document_count": len(documents),
            "parsed_document_count": sum(
                item.status.value in {"parsed", "low_quality"} for item in documents
            ),
            "claim_count": len(claims),
            "draft_version": latest_version,
            "blocking_claim_count": sum(
                bool(row["blocking"]) for row in claim_rows
            ),
            "documents": [item.to_dict() for item in documents],
            "claims": claim_rows,
        }


class OutputPresenter:
    def __init__(self, artifact_root: Path) -> None:
        self.artifacts = LocalArtifactStore(artifact_root)

    def detail(self, run_id: str) -> dict[str, object]:
        survey_path = "final/survey.md"
        available = self.artifacts.exists(run_id, survey_path)
        survey = self.artifacts.read_text(run_id, survey_path) if available else ""
        return {
            "survey_available": available,
            "survey_markdown": survey,
        }


__all__ = [
    "EvidencePresenter",
    "OutputPresenter",
    "candidate_counts",
    "serialize_candidate_counts",
]
