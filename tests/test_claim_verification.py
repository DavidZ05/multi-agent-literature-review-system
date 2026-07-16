from dataclasses import replace
import unittest

from src.literature_review.documents import DocumentRecord, DocumentStatus, EvidenceChunk
from src.literature_review.models import ResearchRun, utc_now_iso
from src.literature_review.verification import (
    CitationScopedRetriever,
    ClaimExtractor,
    ClaimType,
    ClaimVerifier,
    VerificationStatus,
)


class ClaimVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run = ResearchRun.create("Agent memory")
        acquired = DocumentRecord.acquired(
            self.run.run_id,
            "memorypaper",
            "https://example.test/memory.pdf",
            relative_path="documents/memorypaper.pdf",
            sha256="a" * 64,
            byte_size=100,
            access_method="downloaded",
        )
        self.document = replace(
            acquired,
            status=DocumentStatus.PARSED,
            parser="pdfplumber",
            parser_version="0.11.9",
            parse_quality=0.95,
            page_count=3,
            parsed_at=utc_now_iso(),
        )
        self.chunk = EvidenceChunk.create(
            run_id=self.run.run_id,
            document_id=self.document.document_id,
            document_sha256=self.document.sha256 or "",
            citation_key="memorypaper",
            section="Results",
            page_start=2,
            page_end=2,
            text=(
                "The reflective memory method improved evaluation accuracy and reduced "
                "repeated errors across later agent trials."
            ),
            char_start=100,
            char_end=220,
            settings_fingerprint="c" * 64,
        )

    def test_extractor_records_positions_citations_and_missing_citation(self) -> None:
        markdown = """# Review
## Results
Reflective memory improved evaluation accuracy [memorypaper]. It reduced repeated errors.

## References
- [memorypaper] Example reference.
"""
        claims = ClaimExtractor().extract(self.run.run_id, markdown, draft_version=1)

        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0].citation_keys, ("memorypaper",))
        self.assertEqual(claims[0].section, "Results")
        self.assertEqual(claims[0].claim_type, ClaimType.FACTUAL)
        self.assertTrue(claims[1].requires_citation)
        self.assertEqual(claims[1].citation_keys, ())

    def test_retrieval_is_strictly_citation_scoped(self) -> None:
        wrong_source = replace(
            self.chunk,
            chunk_id="chunk_" + "b" * 32,
            citation_key="otherpaper",
        )
        hits = CitationScopedRetriever().retrieve(
            "Reflective memory improved evaluation accuracy.",
            "memorypaper",
            (wrong_source, self.chunk),
        )

        self.assertEqual([hit.chunk.chunk_id for hit in hits], [self.chunk.chunk_id])

    def test_compound_sentence_is_split_and_inherits_trailing_citation(self) -> None:
        claims = ClaimExtractor().extract(
            self.run.run_id,
            "## Results\nMemory improved accuracy; however, it increased latency [memorypaper].",
            draft_version=1,
        )

        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0].citation_keys, ("memorypaper",))
        self.assertEqual(claims[1].citation_keys, ("memorypaper",))

    def test_verifier_supports_grounded_claim_and_blocks_missing_citation(self) -> None:
        claims = ClaimExtractor().extract(
            self.run.run_id,
            "## Results\nReflective memory improved evaluation accuracy [memorypaper]. "
            "It reduced repeated errors.",
            draft_version=1,
        )
        verifier = ClaimVerifier()
        results = verifier.verify(claims, (self.document,), (self.chunk,))

        self.assertEqual(results[0].status, VerificationStatus.SUPPORTED)
        self.assertFalse(results[0].blocking)
        self.assertEqual(results[0].evidence_pages, (2,))
        self.assertEqual(results[1].status, VerificationStatus.MISSING_CITATION)
        self.assertTrue(results[1].blocking)
        report = verifier.report(claims, results)
        self.assertFalse(report["accepted"])
        self.assertEqual(report["blocking_count"], 1)

    def test_unavailable_full_text_is_explicitly_blocking(self) -> None:
        unavailable = DocumentRecord.unavailable(
            self.run.run_id,
            "memorypaper",
            "https://example.test/memory.pdf",
            "http_404",
        )
        claims = ClaimExtractor().extract(
            self.run.run_id,
            "## Results\nReflective memory improved evaluation accuracy [memorypaper].",
            draft_version=1,
        )

        result = ClaimVerifier().verify(claims, (unavailable,), ())[0]

        self.assertEqual(result.status, VerificationStatus.FULL_TEXT_UNAVAILABLE)
        self.assertTrue(result.blocking)

    def test_claim_with_wrong_source_content_is_not_supported(self) -> None:
        claims = ClaimExtractor().extract(
            self.run.run_id,
            "## Results\nThe system achieved ninety percent legal accuracy [memorypaper].",
            draft_version=1,
        )

        result = ClaimVerifier().verify(claims, (self.document,), (self.chunk,))[0]

        self.assertIn(
            result.status,
            {VerificationStatus.NOT_FOUND, VerificationStatus.PARTIALLY_SUPPORTED},
        )
        self.assertTrue(result.blocking)


if __name__ == "__main__":
    unittest.main()
