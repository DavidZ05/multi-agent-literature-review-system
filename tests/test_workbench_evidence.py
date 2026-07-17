from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.literature_review.documents import DocumentRecord
from src.literature_review.models import (
    ResearchRun,
    RunStatus,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.storage import SQLiteWorkflowStore
from src.literature_review.verification import (
    AtomicClaim,
    ClaimType,
    ClaimVerification,
    VerificationStatus,
)
from src.literature_review.workbench import WorkbenchService


class WorkbenchEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = SQLiteWorkflowStore(root / "workflow.db")
        self.store.initialize()
        self.artifact_root = root / "artifacts"
        self.run = replace(
            ResearchRun.create("Agent memory"),
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_EVIDENCE_REVIEW,
            updated_at=utc_now_iso(),
        )
        self.store.create_run(self.run)
        self.document = DocumentRecord.unavailable(
            self.run.run_id,
            "memorypaper",
            "https://example.test/memory.pdf",
            "http_404",
        )
        self.store.put_document(self.document)
        self.claim = AtomicClaim.create(
            run_id=self.run.run_id,
            draft_version=1,
            text="Reflective memory improves evaluation accuracy.",
            claim_type=ClaimType.FACTUAL,
            citation_keys=("memorypaper",),
            section="Results",
            paragraph_index=1,
            sentence_index=0,
            requires_citation=True,
        )
        self.store.replace_claims(self.run.run_id, 1, (self.claim,))
        self.unavailable = ClaimVerification.create(
            run_id=self.run.run_id,
            claim_id=self.claim.claim_id,
            citation_key="memorypaper",
            status=VerificationStatus.FULL_TEXT_UNAVAILABLE,
            evidence_chunk_ids=(),
            evidence_pages=(),
            reason="The cited PDF is unavailable.",
            confidence=1.0,
            verifier="deterministic",
            blocking=True,
            fingerprint="a" * 64,
        )
        self.store.put_claim_verifications((self.unavailable,))
        self.service = WorkbenchService(
            self.store,
            artifact_root=self.artifact_root,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_detail_exposes_latest_blocking_claim_and_risk_decision(self) -> None:
        detail = self.service.get_run_detail(self.run.run_id)

        self.assertEqual(detail["evidence"]["draft_version"], 1)
        self.assertEqual(detail["evidence"]["blocking_claim_count"], 1)
        self.assertEqual(
            detail["evidence"]["claims"][0]["verifications"][0]["status"],
            "full_text_unavailable",
        )

        result = self.service.decide_evidence(
            self.run.run_id,
            self.claim.claim_id,
            "accept_risk",
            "The source is inaccessible and the limitation will be disclosed.",
        )

        self.assertEqual(result["decision"]["action"], "accept_risk")
        self.assertIn("evidence-decide", result["equivalent_command"])
        self.assertIsNotNone(result["evidence"]["claims"][0]["decision"])

    def test_accept_risk_rejects_a_content_mismatch(self) -> None:
        mismatch = ClaimVerification.create(
            run_id=self.run.run_id,
            claim_id=self.claim.claim_id,
            citation_key="memorypaper",
            status=VerificationStatus.NOT_FOUND,
            evidence_chunk_ids=(),
            evidence_pages=(),
            reason="No passage supports the claim.",
            confidence=0.8,
            verifier="deterministic",
            blocking=True,
            fingerprint="b" * 64,
        )
        self.store.put_claim_verifications((mismatch,))

        with self.assertRaisesRegex(ValueError, "unavailable full text"):
            self.service.decide_evidence(
                self.run.run_id,
                self.claim.claim_id,
                "accept_risk",
                "Accept anyway.",
            )

    def test_refreshed_verification_supersedes_the_previous_decision(self) -> None:
        self.service.decide_evidence(
            self.run.run_id,
            self.claim.claim_id,
            "accept_risk",
            "The PDF is currently unavailable.",
        )
        mismatch = ClaimVerification.create(
            run_id=self.run.run_id,
            claim_id=self.claim.claim_id,
            citation_key="memorypaper",
            status=VerificationStatus.NOT_FOUND,
            evidence_chunk_ids=(),
            evidence_pages=(),
            reason="The imported PDF does not support the claim.",
            confidence=0.8,
            verifier="deterministic",
            blocking=True,
            fingerprint="b" * 64,
        )
        self.store.replace_claim_verifications(
            self.run.run_id,
            (self.claim.claim_id,),
            (mismatch,),
        )

        detail = self.service.get_run_detail(self.run.run_id)
        claim = detail["evidence"]["claims"][0]

        self.assertIsNone(claim["decision"])
        self.assertEqual(len(claim["decision_history"]), 1)

    def test_evidence_decision_requires_a_waiting_run(self) -> None:
        self.store.update_run(
            replace(
                self.run,
                status=RunStatus.ACTIVE,
                updated_at=utc_now_iso(),
            )
        )

        with self.assertRaisesRegex(ValueError, "review gate"):
            self.service.decide_evidence(
                self.run.run_id,
                self.claim.claim_id,
                "accept_risk",
                "Concurrent decision.",
            )

    def test_evidence_decision_is_rejected_outside_the_review_gate(self) -> None:
        self.store.update_run(
            replace(
                self.run,
                status=RunStatus.COMPLETED,
                current_stage=WorkflowStage.COMPLETED,
                updated_at=utc_now_iso(),
            )
        )

        with self.assertRaisesRegex(ValueError, "review gate"):
            self.service.decide_evidence(
                self.run.run_id,
                self.claim.claim_id,
                "require_revision",
                "Revise this claim.",
            )


if __name__ == "__main__":
    unittest.main()
