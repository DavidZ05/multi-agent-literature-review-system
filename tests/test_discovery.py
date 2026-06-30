import json
import unittest

from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    CorpusDecision,
    ProviderPaper,
    ProviderSearchResult,
    ScreeningRecommendation,
    SearchQuery,
)


class DiscoveryModelTests(unittest.TestCase):
    def test_search_query_round_trip(self) -> None:
        query = SearchQuery(
            query_id="query_01",
            text="LLM agent memory",
            provider="arxiv",
            max_results=20,
            year_from=2020,
            year_to=2026,
        )
        self.assertEqual(SearchQuery.from_dict(query.to_dict()), query)

    def test_provider_result_serializes_metadata_without_raw_body(self) -> None:
        paper = ProviderPaper(
            provider="arxiv",
            provider_id="2304.03442",
            title="Generative Agents",
            authors=("Joon Sung Park",),
            year=2023,
            venue="UIST",
            abstract="Agent memory.",
            doi=None,
            arxiv_id="2304.03442",
            semantic_scholar_id=None,
            source_url="https://arxiv.org/abs/2304.03442",
            open_access_pdf_url="https://arxiv.org/pdf/2304.03442",
        )
        result = ProviderSearchResult(
            provider="arxiv",
            query_id="query_01",
            request_url="https://export.arxiv.org/api/query",
            papers=(paper,),
            raw_body=b"<feed />",
            response_headers={"content-type": "application/atom+xml"},
        )

        serialized = result.to_dict()

        self.assertNotIn("raw_body", serialized)
        self.assertEqual(json.loads(json.dumps(serialized)), serialized)
        self.assertEqual(
            ProviderSearchResult.from_dict(serialized).papers,
            result.papers,
        )

    def test_candidate_round_trip_preserves_enums(self) -> None:
        candidate = CandidatePaper(
            candidate_id="cand_abc123",
            title="Generative Agents",
            authors=("Joon Sung Park",),
            year=2023,
            venue="UIST",
            abstract="Agent memory.",
            doi=None,
            arxiv_id="2304.03442",
            semantic_scholar_id="s2-paper",
            source_urls=("https://arxiv.org/abs/2304.03442",),
            open_access_pdf_url="https://arxiv.org/pdf/2304.03442",
            provenance=("arxiv:2304.03442", "semantic_scholar:s2-paper"),
            recommendation=ScreeningRecommendation.INCLUDE,
            relevance_score=0.9,
            status=CandidateStatus.PENDING,
        )

        self.assertEqual(CandidatePaper.from_dict(candidate.to_dict()), candidate)

    def test_decision_round_trip(self) -> None:
        decision = CorpusDecision.create(
            run_id="run_0123456789abcdef0123456789abcdef",
            candidate_id="cand_abc123",
            status=CandidateStatus.APPROVED,
            reason="Core mechanism paper",
            actor="human",
        )
        self.assertEqual(CorpusDecision.from_dict(decision.to_dict()), decision)

    def test_invalid_provider_and_missing_identifier_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider"):
            SearchQuery("q", "memory", "unknown", 10, None, None)
        with self.assertRaisesRegex(ValueError, "stable identifier"):
            CandidatePaper(
                candidate_id="cand_missing",
                title="No identifier",
                authors=("A. Author",),
                year=2024,
                venue=None,
                abstract=None,
                doi=None,
                arxiv_id=None,
                semantic_scholar_id=None,
                source_urls=("https://example.com",),
                open_access_pdf_url=None,
                provenance=("arxiv:none",),
                recommendation=ScreeningRecommendation.REVIEW,
                relevance_score=0.5,
                status=CandidateStatus.PENDING,
            )


if __name__ == "__main__":
    unittest.main()
