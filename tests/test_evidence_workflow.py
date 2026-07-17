from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.literature_review.documents import (
    AcquisitionResult,
    DocumentRecord,
    DocumentStatus,
    EvidenceIndexer,
    ParsedDocument,
    ParsedPage,
)
from src.literature_review.models import ResearchRun, WorkflowStage, utc_now_iso
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.verification import (
    ClaimVerification,
    EvidenceReviewDecision,
    VerificationStatus,
)
from src.literature_review.workflow import (
    ClaimVerificationHandler,
    DocumentAcquisitionHandler,
    DraftingHandler,
    EvidenceIndexingHandler,
    EvidenceReviewGateHandler,
    PersistentWorkflowEngine,
    PlanningHandler,
    StageContext,
    StageWaitingError,
)


def paper_record() -> dict[str, object]:
    return {
        "citation_key": "memorypaper",
        "title": "Reflective Memory",
        "authors": ["A Researcher"],
        "year": 2025,
        "venue": "Test venue",
        "url": "https://example.test/memory.pdf",
        "category": "memory mechanism",
        "contribution": "Evaluates reflective memory.",
        "evidence": "Test fixture.",
        "tags": ["memory"],
    }


class FixtureAcquirer:
    def acquire(self, run_id, paper, artifact_store) -> AcquisitionResult:
        artifact = artifact_store.write_bytes(
            run_id,
            "documents/memorypaper.pdf",
            b"%PDF-1.7\nfixture",
        )
        document = DocumentRecord.acquired(
            run_id,
            "memorypaper",
            str(paper["url"]),
            relative_path=artifact.relative_path,
            sha256=artifact.sha256,
            byte_size=artifact.size_bytes,
            access_method="downloaded",
        )
        return AcquisitionResult(document, True)


class FixtureParser:
    def parse(self, document, path) -> ParsedDocument:
        text = (
            "Results\nThe reflective memory method improved evaluation accuracy and "
            "reduced repeated errors across later agent trials. "
        ) * 12
        parsed = replace(
            document,
            status=DocumentStatus.PARSED,
            parser="fixture",
            parser_version="1",
            parse_quality=1.0,
            page_count=1,
            parsed_at=utc_now_iso(),
        )
        return ParsedDocument(
            parsed,
            (ParsedPage(1, text, 0, len(text)),),
            (),
        )


class FeedbackAwareOrchestrator:
    feedback: list[dict[str, object] | None] = []

    def __init__(self, output_dir: Path, initial_review_feedback=None, **kwargs) -> None:
        self.output_dir = output_dir
        self.initial_review_feedback = initial_review_feedback
        self.__class__.feedback.append(initial_review_feedback)

    def run(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        revised = isinstance(self.initial_review_feedback, dict)
        claim = (
            "Reflective memory improved evaluation accuracy and reduced repeated errors "
            "across later agent trials [memorypaper]."
            if revised
            else "The system achieved ninety percent legal accuracy [memorypaper]."
        )
        (self.output_dir / "survey.md").write_text(
            f"# Review\n\n## Results\n{claim}\n",
            encoding="utf-8",
        )
        for name in (
            "review_report.json",
            "final_verification.json",
            "evaluation_report.json",
            "revision_log.json",
        ):
            (self.output_dir / name).write_text(
                json.dumps({"status": "accepted"}),
                encoding="utf-8",
            )
        (self.output_dir / "reflection_log.md").write_text(
            "Accepted.\n",
            encoding="utf-8",
        )
        return {"status": "accepted"}


class EvidenceWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.corpus = root / "papers.json"
        self.corpus.write_text(json.dumps([paper_record()]), encoding="utf-8")
        self.store = SQLiteWorkflowStore(root / "workflow.db")
        self.artifacts = LocalArtifactStore(root / "artifacts")
        FeedbackAwareOrchestrator.feedback = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def engine(self) -> PersistentWorkflowEngine:
        drafting = DraftingHandler(
            orchestrator_factory=FeedbackAwareOrchestrator,
        ).enable_claim_verification()
        return PersistentWorkflowEngine(
            self.store,
            self.artifacts,
            {
                WorkflowStage.PLANNING: PlanningHandler(full_text_enabled=True),
                WorkflowStage.ACQUIRING_DOCUMENTS: DocumentAcquisitionHandler(
                    FixtureAcquirer()
                ),
                WorkflowStage.INDEXING_EVIDENCE: EvidenceIndexingHandler(
                    FixtureParser(),
                    EvidenceIndexer(),
                ),
                WorkflowStage.DRAFTING: drafting,
                WorkflowStage.CLAIM_VERIFICATION: ClaimVerificationHandler(),
                WorkflowStage.AWAITING_EVIDENCE_REVIEW: EvidenceReviewGateHandler(),
            },
            runtime_config={"full_text_enabled": True},
        )

    def test_evidence_feedback_reaches_writer_and_forces_new_draft(self) -> None:
        engine = self.engine()
        waiting = engine.start("Agent memory", self.corpus)

        self.assertEqual(waiting.current_stage, WorkflowStage.AWAITING_EVIDENCE_REVIEW)
        self.assertEqual(len(FeedbackAwareOrchestrator.feedback), 1)
        blocking_results = [
            item
            for item in self.store.list_claim_verifications(waiting.run_id)
            if item.blocking
        ]
        blocking_claim_ids = {item.claim_id for item in blocking_results}
        self.assertTrue(blocking_claim_ids)
        for claim_id in blocking_claim_ids:
            self.store.put_evidence_review_decision(
                EvidenceReviewDecision.create(
                    waiting.run_id,
                    claim_id,
                    "require_revision",
                    "The cited PDF does not support this claim.",
                    "test",
                    verification_fingerprints=tuple(
                        item.fingerprint
                        for item in blocking_results
                        if item.claim_id == claim_id
                    ),
                )
            )

        completed = engine.resume(waiting.run_id)

        self.assertEqual(completed.current_stage, WorkflowStage.COMPLETED)
        self.assertEqual(len(FeedbackAwareOrchestrator.feedback), 2)
        feedback = FeedbackAwareOrchestrator.feedback[1]
        self.assertIsInstance(feedback, dict)
        assert isinstance(feedback, dict)
        self.assertTrue(feedback["revision_request_ids"])
        versions = {claim.draft_version for claim in self.store.list_claims(waiting.run_id)}
        self.assertEqual(versions, {1, 2})
        latest = self.store.list_claims(waiting.run_id, draft_version=2)
        latest_ids = {claim.claim_id for claim in latest}
        latest_results = [
            item
            for item in self.store.list_claim_verifications(waiting.run_id)
            if item.claim_id in latest_ids
        ]
        self.assertTrue(latest_results)
        self.assertTrue(all(not item.blocking for item in latest_results))

    def test_refreshed_document_results_can_complete_without_a_risk_decision(self) -> None:
        engine = self.engine()
        waiting = engine.start("Agent memory", self.corpus)
        claims = self.store.list_claims(waiting.run_id, draft_version=1)
        old_results = self.store.list_claim_verifications(waiting.run_id)
        chunk = self.artifacts.read_json(
            waiting.run_id,
            "evidence/index_manifest.json",
        )["chunks"][0]
        supported = tuple(
            ClaimVerification.create(
                run_id=waiting.run_id,
                claim_id=result.claim_id,
                citation_key=result.citation_key,
                status=VerificationStatus.SUPPORTED,
                evidence_chunk_ids=(chunk["chunk_id"],),
                evidence_pages=(chunk["page_start"],),
                reason="The refreshed PDF supports the claim.",
                confidence=0.9,
                verifier="deterministic",
                blocking=False,
                fingerprint=(f"{index + 1:064x}"[-64:]),
            )
            for index, result in enumerate(old_results)
        )
        self.store.replace_claim_verifications(
            waiting.run_id,
            tuple(claim.claim_id for claim in claims),
            supported,
        )

        completed = engine.resume(waiting.run_id)

        self.assertEqual(completed.current_stage, WorkflowStage.COMPLETED)
        final_review = self.artifacts.read_json(
            waiting.run_id,
            "evidence/final_review.json",
        )
        self.assertEqual(
            final_review["status"],
            "accepted_after_document_refresh",
        )

    def test_claim_verification_replay_reuses_the_same_draft_version(self) -> None:
        engine = self.engine()
        waiting = engine.start("Agent memory", self.corpus)
        handler = ClaimVerificationHandler()
        context = StageContext(
            run=waiting,
            artifact_store=self.artifacts,
            workflow_store=self.store,
            corpus_path=self.corpus,
            runtime_config={"full_text_enabled": True},
            _cancellation_check=lambda: False,
        )

        handler(context)

        versions = {
            claim.draft_version
            for claim in self.store.list_claims(waiting.run_id)
        }
        self.assertEqual(versions, {1})

    def test_stale_risk_decision_returns_to_human_review(self) -> None:
        engine = self.engine()
        waiting = engine.start("Agent memory", self.corpus)
        old_result = next(
            item
            for item in self.store.list_claim_verifications(waiting.run_id)
            if item.blocking
        )
        self.store.put_evidence_review_decision(
            EvidenceReviewDecision.create(
                waiting.run_id,
                old_result.claim_id,
                "accept_risk",
                "The previous evidence state was unavailable.",
                "test",
                verification_fingerprints=(old_result.fingerprint,),
            )
        )
        refreshed = ClaimVerification.create(
            run_id=waiting.run_id,
            claim_id=old_result.claim_id,
            citation_key=old_result.citation_key,
            status=VerificationStatus.NOT_FOUND,
            evidence_chunk_ids=(),
            evidence_pages=(),
            reason="The refreshed PDF does not support the claim.",
            confidence=0.8,
            verifier="deterministic",
            blocking=True,
            fingerprint="f" * 64,
        )
        self.store.replace_claim_verifications(
            waiting.run_id,
            (old_result.claim_id,),
            (refreshed,),
        )
        context = StageContext(
            run=waiting,
            artifact_store=self.artifacts,
            workflow_store=self.store,
            corpus_path=self.corpus,
            runtime_config={"full_text_enabled": True},
            _cancellation_check=lambda: False,
        )

        with self.assertRaises(StageWaitingError):
            EvidenceReviewGateHandler()(context)


if __name__ == "__main__":
    unittest.main()
