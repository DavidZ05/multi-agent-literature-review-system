from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.literature_review.documents import (
    DocumentRecord,
    DocumentStatus,
    EvidenceChunk,
)
from src.literature_review.models import ResearchRun
from src.literature_review.storage import SQLiteWorkflowStore
from src.literature_review.verification import (
    AtomicClaim,
    ClaimType,
    ClaimVerification,
    EvidenceReviewDecision,
    VerificationStatus,
    active_evidence_decisions,
)


class EvidenceModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run = ResearchRun.create("Agent memory")
        self.document = DocumentRecord.acquired(
            self.run.run_id,
            "paper2026",
            "https://example.test/paper.pdf",
            relative_path="documents/paper2026.pdf",
            sha256="a" * 64,
            byte_size=128,
            access_method="downloaded",
        )

    def test_document_round_trip_and_path_containment(self) -> None:
        self.assertEqual(DocumentRecord.from_dict(self.document.to_dict()), self.document)
        with self.assertRaisesRegex(ValueError, "documents"):
            DocumentRecord.acquired(
                self.run.run_id,
                "paper2026",
                "https://example.test/paper.pdf",
                relative_path="../paper.pdf",
                sha256="a" * 64,
                byte_size=128,
                access_method="downloaded",
            )

    def test_evidence_and_claim_ids_are_stable(self) -> None:
        kwargs = {
            "run_id": self.run.run_id,
            "document_id": self.document.document_id,
            "document_sha256": self.document.sha256,
            "citation_key": "paper2026",
            "section": "Results",
            "page_start": 2,
            "page_end": 2,
            "text": "Memory improved accuracy in the reported evaluation.",
            "char_start": 0,
            "char_end": 52,
            "settings_fingerprint": "chunk-v1",
        }
        first = EvidenceChunk.create(**kwargs)
        second = EvidenceChunk.create(**kwargs)
        self.assertEqual(first, second)

        claim_kwargs = {
            "run_id": self.run.run_id,
            "draft_version": 1,
            "text": "Memory improved evaluation accuracy.",
            "claim_type": ClaimType.FACTUAL,
            "citation_keys": ("paper2026",),
            "section": "Results",
            "paragraph_index": 1,
            "sentence_index": 0,
            "requires_citation": True,
        }
        self.assertEqual(
            AtomicClaim.create(**claim_kwargs),
            AtomicClaim.create(**claim_kwargs),
        )

    def test_evidence_records_round_trip_through_sqlite(self) -> None:
        with TemporaryDirectory() as temporary:
            store = SQLiteWorkflowStore(Path(temporary) / "workflow.db")
            store.initialize()
            store.create_run(self.run)
            store.put_document(self.document)
            chunk = EvidenceChunk.create(
                run_id=self.run.run_id,
                document_id=self.document.document_id,
                document_sha256=self.document.sha256 or "",
                citation_key="paper2026",
                section="Results",
                page_start=2,
                page_end=2,
                text="Memory improved accuracy in evaluation.",
                char_start=0,
                char_end=39,
                settings_fingerprint="chunk-v1",
            )
            store.replace_evidence_chunks(
                self.run.run_id,
                self.document.document_id,
                (chunk,),
            )
            claim = AtomicClaim.create(
                run_id=self.run.run_id,
                draft_version=1,
                text="Memory improved accuracy.",
                claim_type=ClaimType.FACTUAL,
                citation_keys=("paper2026",),
                section="Results",
                paragraph_index=1,
                sentence_index=0,
                requires_citation=True,
            )
            store.replace_claims(self.run.run_id, 1, (claim,))
            verification = ClaimVerification.create(
                run_id=self.run.run_id,
                claim_id=claim.claim_id,
                citation_key="paper2026",
                status=VerificationStatus.SUPPORTED,
                evidence_chunk_ids=(chunk.chunk_id,),
                evidence_pages=(2,),
                reason="The result is directly reported.",
                confidence=0.9,
                verifier="deterministic",
                blocking=False,
                fingerprint="b" * 64,
            )
            store.put_claim_verifications((verification,))
            decision = EvidenceReviewDecision.create(
                self.run.run_id,
                claim.claim_id,
                "accept_risk",
                "Human checked the source.",
                "tester",
                verification_fingerprints=(verification.fingerprint,),
            )
            store.put_evidence_review_decision(decision)

            self.assertEqual(store.list_documents(self.run.run_id), [self.document])
            self.assertEqual(store.list_evidence_chunks(self.run.run_id), [chunk])
            self.assertEqual(store.list_claims(self.run.run_id), [claim])
            self.assertEqual(
                store.list_claim_verifications(self.run.run_id),
                [verification],
            )
            replacement = ClaimVerification.create(
                run_id=self.run.run_id,
                claim_id=claim.claim_id,
                citation_key="paper2026",
                status=VerificationStatus.NOT_FOUND,
                evidence_chunk_ids=(),
                evidence_pages=(),
                reason="The refreshed document no longer supports the claim.",
                confidence=0.8,
                verifier="deterministic",
                blocking=True,
                fingerprint="c" * 64,
            )
            store.replace_claim_verifications(
                self.run.run_id,
                (claim.claim_id,),
                (replacement,),
            )
            self.assertEqual(
                store.list_claim_verifications(self.run.run_id),
                [replacement],
            )
            self.assertEqual(
                store.list_evidence_review_decisions(self.run.run_id),
                [decision],
            )

    def test_unavailable_document_requires_no_local_file(self) -> None:
        unavailable = DocumentRecord.unavailable(
            self.run.run_id,
            "paper2026",
            "https://example.test/paper.pdf",
            "http_404",
        )
        self.assertEqual(unavailable.status, DocumentStatus.UNAVAILABLE)
        self.assertIsNone(unavailable.relative_path)

    def test_legacy_decision_without_fingerprints_is_audit_only(self) -> None:
        claim = AtomicClaim.create(
            run_id=self.run.run_id,
            draft_version=1,
            text="Memory improved accuracy.",
            claim_type=ClaimType.FACTUAL,
            citation_keys=("paper2026",),
            section="Results",
            paragraph_index=1,
            sentence_index=0,
            requires_citation=True,
        )
        verification = ClaimVerification.create(
            run_id=self.run.run_id,
            claim_id=claim.claim_id,
            citation_key="paper2026",
            status=VerificationStatus.NOT_FOUND,
            evidence_chunk_ids=(),
            evidence_pages=(),
            reason="No passage supports the claim.",
            confidence=0.8,
            verifier="deterministic",
            blocking=True,
            fingerprint="c" * 64,
        )
        legacy = EvidenceReviewDecision.from_dict(
            {
                "decision_id": "evidence_decision_" + "d" * 32,
                "run_id": self.run.run_id,
                "claim_id": claim.claim_id,
                "action": "require_revision",
                "reason": "Legacy review.",
                "actor": "tester",
                "created_at": self.run.created_at,
            }
        )

        self.assertEqual(
            active_evidence_decisions((verification,), (legacy,)),
            {},
        )


if __name__ == "__main__":
    unittest.main()
