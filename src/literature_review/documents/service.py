from __future__ import annotations

from pathlib import Path

from src.literature_review.documents.acquisition import DocumentAcquirer
from src.literature_review.documents.index import EvidenceIndexer
from src.literature_review.documents.models import DocumentRecord
from src.literature_review.documents.parser import PDFParser
from src.literature_review.models import WorkflowStage
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.verification.verifier import ClaimVerifier


class DocumentImportService:
    def __init__(
        self,
        store: SQLiteWorkflowStore,
        artifact_store: LocalArtifactStore,
        *,
        acquirer: DocumentAcquirer | None = None,
        parser: PDFParser | None = None,
        indexer: EvidenceIndexer | None = None,
        verifier: ClaimVerifier | None = None,
    ) -> None:
        self.store = store
        self.artifact_store = artifact_store
        self.acquirer = acquirer or DocumentAcquirer()
        self.parser = parser or PDFParser()
        self.indexer = indexer or EvidenceIndexer()
        self.verifier = verifier or ClaimVerifier()

    def import_pdf(
        self,
        run_id: str,
        citation_key: str,
        source_path: Path,
    ) -> DocumentRecord:
        run = self.store.get_run(run_id)
        if run.current_stage not in {
            WorkflowStage.ACQUIRING_DOCUMENTS,
            WorkflowStage.INDEXING_EVIDENCE,
            WorkflowStage.AWAITING_EVIDENCE_REVIEW,
        }:
            raise ValueError("PDF import is not available at this workflow stage")
        source_path = Path(source_path).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        existing = self.store.get_document(run_id, citation_key)
        if existing is None:
            raise ValueError("citation_key is not present in this run's document manifest")
        with source_path.open("rb") as source:
            content = source.read(self.acquirer.max_pdf_bytes + 1)
        acquired = self.acquirer.import_pdf(
            run_id,
            citation_key,
            content,
            self.artifact_store,
            source_label=existing.source_url,
        )
        parsed = self.parser.parse(
            acquired,
            self.artifact_store.path_for(run_id, acquired.relative_path or ""),
        )
        chunks = self.indexer.build(parsed)
        self.store.put_document(parsed.document)
        self.store.replace_evidence_chunks(run_id, parsed.document.document_id, chunks)
        self.artifact_store.write_json(
            run_id,
            f"evidence/parsed/{citation_key}.json",
            parsed.to_dict(),
        )
        claims = self.store.list_claims(run_id)
        latest_version = max(
            (claim.draft_version for claim in claims),
            default=0,
        )
        latest_claims = tuple(
            claim for claim in claims if claim.draft_version == latest_version
        )
        blocking_count = 0
        if latest_claims:
            verifications = self.verifier.verify(
                latest_claims,
                self.store.list_documents(run_id),
                self.store.list_evidence_chunks(run_id),
            )
            self.store.replace_claim_verifications(
                run_id,
                tuple(claim.claim_id for claim in latest_claims),
                verifications,
            )
            report = self.verifier.report(latest_claims, verifications)
            feedback = self.verifier.feedback(latest_claims, verifications)
            blocking_count = int(report["blocking_count"])
            self.artifact_store.write_json(
                run_id,
                "evidence/claim_verification.json",
                report,
            )
            self.artifact_store.write_json(
                run_id,
                "evidence/latest_feedback.json",
                feedback,
            )
        self.store.append_event(
            run_id,
            "document_imported",
            {
                "citation_key": citation_key,
                "sha256": parsed.document.sha256 or "",
                "page_count": parsed.document.page_count,
                "chunk_count": len(chunks),
                "blocking_claim_count": blocking_count,
            },
            run.current_stage,
        )
        return parsed.document


__all__ = ["DocumentImportService"]
