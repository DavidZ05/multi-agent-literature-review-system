from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from src.literature_review.activity import ActivityCoordinator
from src.literature_review.documents.acquisition import (
    DocumentAcquirer,
    document_relative_path,
)
from src.literature_review.documents.index import EvidenceIndexer
from src.literature_review.documents.models import DocumentRecord
from src.literature_review.documents.parser import PDFParser
from src.literature_review.models import RunStatus, WorkflowStage
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
        self.activity = ActivityCoordinator.for_artifact_root(artifact_store.root)

    def import_pdf(
        self,
        run_id: str,
        citation_key: str,
        source_path: Path,
    ) -> DocumentRecord:
        with self.activity.resume_execution(run_id):
            return self._import_pdf(run_id, citation_key, source_path)

    def _import_pdf(
        self,
        run_id: str,
        citation_key: str,
        source_path: Path,
    ) -> DocumentRecord:
        run = self.store.get_run(run_id)
        if (
            run.status != RunStatus.WAITING
            or run.current_stage != WorkflowStage.AWAITING_EVIDENCE_REVIEW
        ):
            raise ValueError("PDF import is not available at this workflow stage")
        source_path = Path(source_path).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        existing = self.store.get_document(run_id, citation_key)
        if existing is None:
            raise ValueError("citation_key is not present in this run's document manifest")
        with source_path.open("rb") as source:
            content = source.read(self.acquirer.max_pdf_bytes + 1)
        staging_path = f"documents/.staging/{uuid4().hex}.pdf"
        final_path = document_relative_path(citation_key)
        old_content = self._current_pdf_content(run_id, existing)
        try:
            acquired = self.acquirer.import_pdf(
                run_id,
                citation_key,
                content,
                self.artifact_store,
                source_label=existing.source_url,
                relative_path=staging_path,
            )
            staged = self.parser.parse(
                acquired,
                self.artifact_store.path_for(run_id, staging_path),
            )
            parsed = replace(
                staged,
                document=replace(staged.document, relative_path=final_path),
            )
            chunks = self.indexer.build(parsed)
            self._archive_existing_document(run_id, existing)
            self.artifact_store.write_bytes(run_id, final_path, content)
            try:
                self.store.replace_document_with_chunks(parsed.document, chunks)
            except BaseException:
                self._restore_current_pdf(run_id, final_path, old_content)
                raise
        finally:
            self.artifact_store.path_for(run_id, staging_path).unlink(missing_ok=True)
        self.artifact_store.write_json(
            run_id,
            f"evidence/parsed/{citation_key}.json",
            parsed.to_dict(),
        )
        self._refresh_manifests(run_id, parsed.quality_warnings)
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

    def _current_pdf_content(
        self,
        run_id: str,
        document: DocumentRecord,
    ) -> bytes | None:
        if document.relative_path and self.artifact_store.exists(
            run_id,
            document.relative_path,
        ):
            return self.artifact_store.read_bytes(run_id, document.relative_path)
        return None

    def _restore_current_pdf(
        self,
        run_id: str,
        relative_path: str,
        old_content: bytes | None,
    ) -> None:
        if old_content is None:
            self.artifact_store.path_for(run_id, relative_path).unlink(missing_ok=True)
            return
        self.artifact_store.write_bytes(run_id, relative_path, old_content)

    def _archive_existing_document(
        self,
        run_id: str,
        document: DocumentRecord,
    ) -> None:
        chunks = tuple(
            chunk
            for chunk in self.store.list_evidence_chunks(
                run_id,
                citation_key=document.citation_key,
            )
            if chunk.document_id == document.document_id
        )
        archived_pdf_path: str | None = None
        if (
            document.relative_path
            and self.artifact_store.exists(run_id, document.relative_path)
        ):
            archived_pdf_path = (
                f"documents/history/{document.document_id}.pdf"
            )
            self.artifact_store.write_bytes(
                run_id,
                archived_pdf_path,
                self.artifact_store.read_bytes(
                    run_id,
                    document.relative_path,
                ),
            )
        if archived_pdf_path is None and not chunks:
            return
        self.artifact_store.write_json(
            run_id,
            f"evidence/history/documents/{document.document_id}.json",
            {
                "document": document.to_dict(),
                "archived_pdf_path": archived_pdf_path,
                "chunks": [chunk.to_dict() for chunk in chunks],
            },
        )

    def _refresh_manifests(
        self,
        run_id: str,
        imported_quality_warnings: tuple[str, ...],
    ) -> None:
        documents = self.store.list_documents(run_id)
        chunks = self.store.list_evidence_chunks(run_id)
        chunk_counts: dict[str, int] = {}
        for chunk in chunks:
            chunk_counts[chunk.document_id] = (
                chunk_counts.get(chunk.document_id, 0) + 1
            )
        summaries = []
        for document in documents:
            summary = {
                **document.to_dict(),
                "chunk_count": chunk_counts.get(document.document_id, 0),
            }
            if document.access_method == "imported":
                summary["quality_warnings"] = list(imported_quality_warnings)
            summaries.append(summary)
        self.artifact_store.write_json(
            run_id,
            "evidence/document_manifest.json",
            {
                "document_count": len(documents),
                "acquired_count": sum(
                    document.status.value in {"acquired", "parsed", "low_quality"}
                    for document in documents
                ),
                "documents": [document.to_dict() for document in documents],
            },
        )
        self.artifact_store.write_json(
            run_id,
            "evidence/index_manifest.json",
            {
                "document_count": len(documents),
                "chunk_count": len(chunks),
                "documents": summaries,
                "chunks": [chunk.to_dict() for chunk in chunks],
            },
        )


__all__ = ["DocumentImportService"]
