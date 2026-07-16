from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.literature_review.documents import (
    DocumentAcquirer,
    DocumentRecord,
    DocumentStatus,
    EvidenceIndexer,
    PDFParser,
    resolve_pdf_url,
)
from src.literature_review.documents.service import DocumentImportService
from src.literature_review.models import (
    ResearchRun,
    RunStatus,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.providers import HttpResponse
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.verification import (
    AtomicClaim,
    ClaimType,
    ClaimVerification,
    VerificationStatus,
)


class FakeTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, headers) -> HttpResponse:
        self.requests.append((url, dict(headers)))
        return self.response


class FakePDF:
    def __init__(self, pages: list[str]) -> None:
        self.pages = [SimpleNamespace(extract_text=lambda value=value: value) for value in pages]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class DocumentPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.run = ResearchRun.create("Agent memory")
        self.artifacts = LocalArtifactStore(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_arxiv_abstract_url_resolves_to_pdf(self) -> None:
        self.assertEqual(
            resolve_pdf_url({"url": "https://arxiv.org/abs/2304.03442"}),
            "https://arxiv.org/pdf/2304.03442.pdf",
        )

    def test_resolver_rejects_loopback_and_private_ip_urls(self) -> None:
        for url in (
            "https://localhost/paper.pdf",
            "https://127.0.0.1/paper.pdf",
            "https://10.0.0.8/paper.pdf",
            "https://[::1]/paper.pdf",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(
                RuntimeError,
                "localhost|non-public",
            ):
                resolve_pdf_url({"url": url})

    def test_acquirer_rejects_redirect_to_private_address(self) -> None:
        transport = FakeTransport(
            HttpResponse(
                200,
                b"%PDF-1.7\nplaceholder",
                {"Content-Type": "application/pdf"},
                final_url="https://127.0.0.1/private.pdf",
            )
        )

        result = DocumentAcquirer(transport).acquire(
            self.run.run_id,
            {"citation_key": "paper", "url": "https://example.test/paper"},
            self.artifacts,
        )

        self.assertEqual(result.document.status, DocumentStatus.UNAVAILABLE)
        self.assertEqual(result.document.error_code, "unsafe_url")
        self.assertFalse(result.downloaded)

    def test_acquirer_rejects_non_pdf_response_without_writing_file(self) -> None:
        transport = FakeTransport(
            HttpResponse(200, b"<html>not a paper</html>", {"Content-Type": "text/html"})
        )
        result = DocumentAcquirer(transport).acquire(
            self.run.run_id,
            {"citation_key": "paper", "url": "https://example.test/paper"},
            self.artifacts,
        )

        self.assertEqual(result.document.status, DocumentStatus.UNAVAILABLE)
        self.assertEqual(result.document.error_code, "not_pdf")
        self.assertFalse(result.downloaded)
        self.assertFalse(
            self.artifacts.exists(self.run.run_id, "documents/paper.pdf")
        )

    def test_parse_and_index_preserve_pages_and_stable_chunk_ids(self) -> None:
        body = b"%PDF-1.7\nplaceholder"
        transport = FakeTransport(
            HttpResponse(200, body, {"Content-Type": "application/pdf"})
        )
        acquired = DocumentAcquirer(transport).acquire(
            self.run.run_id,
            {"citation_key": "paper", "url": "https://example.test/paper.pdf"},
            self.artifacts,
        ).document
        page_one = "Results\n" + " ".join(f"memory{i}" for i in range(260))
        page_two = "Evaluation\n" + " ".join(f"score{i}" for i in range(260))
        fake_pdfplumber = SimpleNamespace(
            open=lambda path: FakePDF([page_one, page_two])
        )
        with patch.dict("sys.modules", {"pdfplumber": fake_pdfplumber}):
            parsed = PDFParser().parse(
                acquired,
                self.artifacts.path_for(self.run.run_id, "documents/paper.pdf"),
            )

        self.assertEqual(parsed.document.status, DocumentStatus.PARSED)
        self.assertEqual(parsed.document.page_count, 2)
        chunks = EvidenceIndexer().build(parsed)
        repeated = EvidenceIndexer().build(parsed)
        self.assertEqual(chunks, repeated)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].page_start, 1)
        self.assertEqual(chunks[-1].page_end, 2)

    def test_import_rejects_a_non_pdf(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not a PDF"):
            DocumentAcquirer().import_pdf(
                self.run.run_id,
                "paper",
                b"plain text",
                self.artifacts,
            )


class DocumentImportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = SQLiteWorkflowStore(root / "workflow.db")
        self.store.initialize()
        self.artifacts = LocalArtifactStore(root / "artifacts")
        self.run = replace(
            ResearchRun.create("Agent memory"),
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_EVIDENCE_REVIEW,
            updated_at=utc_now_iso(),
        )
        self.store.create_run(self.run)
        self.store.put_document(
            DocumentRecord.unavailable(
                self.run.run_id,
                "memorypaper",
                "https://example.test/memory.pdf",
                "http_404",
            )
        )
        self.claim = AtomicClaim.create(
            run_id=self.run.run_id,
            draft_version=1,
            text="Reflective memory improves retrieval accuracy.",
            claim_type=ClaimType.FACTUAL,
            citation_keys=("memorypaper",),
            section="Results",
            paragraph_index=1,
            sentence_index=0,
            requires_citation=True,
        )
        self.store.replace_claims(self.run.run_id, 1, (self.claim,))
        unavailable = ClaimVerification.create(
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
        self.store.put_claim_verifications((unavailable,))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_import_reverifies_latest_claims_and_replaces_stale_results(self) -> None:
        source = Path(self.temporary.name) / "memory.pdf"
        source.write_bytes(b"%PDF-1.7\nplaceholder")
        passage = (
            "Results\nReflective memory improves retrieval accuracy in the agent "
            "evaluation. "
            + "Supporting evaluation context and experimental detail. " * 16
        )
        fake_pdfplumber = SimpleNamespace(open=lambda path: FakePDF([passage]))

        with patch.dict("sys.modules", {"pdfplumber": fake_pdfplumber}):
            document = DocumentImportService(
                self.store,
                self.artifacts,
            ).import_pdf(self.run.run_id, "memorypaper", source)

        results = self.store.list_claim_verifications(
            self.run.run_id,
            claim_id=self.claim.claim_id,
        )
        self.assertEqual(document.status, DocumentStatus.PARSED)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, VerificationStatus.SUPPORTED)
        self.assertFalse(results[0].blocking)
        self.assertTrue(
            self.artifacts.read_json(
                self.run.run_id,
                "evidence/latest_feedback.json",
            )["accepted"]
        )
        imported_event = self.store.list_events(self.run.run_id)[-1]
        self.assertEqual(imported_event.event_type, "document_imported")
        self.assertEqual(imported_event.payload["blocking_claim_count"], 0)

    def test_import_reads_at_most_the_configured_pdf_limit(self) -> None:
        source = Path(self.temporary.name) / "large.pdf"
        source.write_bytes(b"%PDF-")
        service = DocumentImportService(
            self.store,
            self.artifacts,
            acquirer=DocumentAcquirer(max_pdf_bytes=4),
        )

        with self.assertRaisesRegex(RuntimeError, "size limit"):
            service.import_pdf(self.run.run_id, "memorypaper", source)


if __name__ == "__main__":
    unittest.main()
