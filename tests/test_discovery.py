import json
import unittest

from src.literature_review.discovery.deduplication import (
    deduplicate_papers,
)
from src.literature_review.discovery.normalization import (
    normalize_arxiv_id,
    normalize_doi,
    normalize_space,
    normalize_title_key,
)
from src.literature_review.discovery.planner import QueryPlanner
from src.literature_review.discovery.screening import screen_candidate
from src.literature_review.discovery.service import DiscoveryService
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    CorpusDecision,
    ProviderPaper,
    ProviderSearchResult,
    ScreeningRecommendation,
    SearchQuery,
)
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from pathlib import Path
from tempfile import TemporaryDirectory


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


class QueryPlannerTests(unittest.TestCase):
    def test_emits_four_bounded_queries_per_provider(self) -> None:
        queries = QueryPlanner(max_results=12).plan(
            "Memory-Augmented LLM Agents",
            ("arxiv", "semantic_scholar"),
        )
        self.assertEqual(len(queries), 8)
        self.assertEqual({query.max_results for query in queries}, {12})
        self.assertEqual(
            {query.provider for query in queries},
            {"arxiv", "semantic_scholar"},
        )
        self.assertEqual(
            len({(query.provider, query.text.lower()) for query in queries}),
            8,
        )


class NormalizationTests(unittest.TestCase):
    def test_normalizes_identifiers_and_matching_text(self) -> None:
        self.assertEqual(normalize_space("A\u00a0  title\n"), "A title")
        self.assertEqual(
            normalize_doi("https://doi.org/10.1145/ABC."),
            "10.1145/abc",
        )
        self.assertEqual(
            normalize_arxiv_id("https://arxiv.org/abs/2304.03442v2"),
            "2304.03442",
        )
        self.assertEqual(
            normalize_title_key("The Memory-Agent: A System!"),
            "memory agent system",
        )


def provider_paper(
    provider: str,
    provider_id: str,
    *,
    doi: str | None = None,
    arxiv_id: str | None = None,
    semantic_id: str | None = None,
    title: str = "Generative Agents",
    authors=("Joon Sung Park",),
    year: int = 2023,
) -> ProviderPaper:
    return ProviderPaper(
        provider=provider,
        provider_id=provider_id,
        title=title,
        authors=authors,
        year=year,
        venue="UIST",
        abstract="Memory reflection and retrieval for agents.",
        doi=doi,
        arxiv_id=arxiv_id,
        semantic_scholar_id=semantic_id,
        source_url=f"https://example.com/{provider_id}",
        open_access_pdf_url=None,
    )


class DeduplicationTests(unittest.TestCase):
    def test_merges_cross_provider_records_by_doi(self) -> None:
        candidates, ambiguous = deduplicate_papers(
            [
                provider_paper(
                    "arxiv",
                    "2304.03442",
                    doi="10.1145/3586183.3606763",
                    arxiv_id="2304.03442",
                ),
                provider_paper(
                    "semantic_scholar",
                    "s2-paper",
                    doi="https://doi.org/10.1145/3586183.3606763",
                    semantic_id="s2-paper",
                ),
            ]
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(ambiguous, [])
        self.assertEqual(
            candidates[0].provenance,
            ("arxiv:2304.03442", "semantic_scholar:s2-paper"),
        )
        self.assertEqual(candidates[0].semantic_scholar_id, "s2-paper")

    def test_conflicting_year_is_ambiguous_instead_of_merged(self) -> None:
        candidates, ambiguous = deduplicate_papers(
            [
                provider_paper("arxiv", "one", arxiv_id="2304.03442", year=2023),
                provider_paper(
                    "semantic_scholar",
                    "two",
                    arxiv_id="2304.03442",
                    semantic_id="two",
                    year=2024,
                ),
            ]
        )
        self.assertEqual(len(candidates), 2)
        self.assertEqual(len({item.candidate_id for item in candidates}), 2)
        self.assertEqual(len(ambiguous), 1)


class ScreeningTests(unittest.TestCase):
    def test_scoring_is_transparent_and_does_not_approve(self) -> None:
        candidate = deduplicate_papers(
            [
                provider_paper(
                    "arxiv",
                    "2304.03442",
                    arxiv_id="2304.03442",
                    title="Memory Reflection and Retrieval for LLM Agents",
                )
            ]
        )[0][0]

        result = screen_candidate(
            candidate,
            topic="LLM agent memory",
            coverage_gap_terms=("reflection", "retrieval"),
            seed_title_keys=(),
        )

        self.assertEqual(result.version, "screening-v1")
        self.assertGreaterEqual(result.score, 0.65)
        self.assertEqual(result.recommendation, ScreeningRecommendation.INCLUDE)
        self.assertEqual(candidate.status, CandidateStatus.PENDING)
        self.assertIn("topic_overlap", result.components)


class FixtureProvider:
    def __init__(self, provider_id, papers=(), error=None) -> None:
        self.provider_id = provider_id
        self.papers = tuple(papers)
        self.error = error
        self.calls = 0

    def search(self, query):
        self.calls += 1
        if self.error:
            raise self.error
        return ProviderSearchResult(
            self.provider_id,
            query.query_id,
            f"https://example.com/{query.query_id}",
            self.papers,
            b"fixture",
            {},
        )


class DiscoveryServiceTests(unittest.TestCase):
    def test_partial_provider_failure_keeps_successful_candidates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SQLiteWorkflowStore(root / "workflow.db")
            store.initialize()
            from src.literature_review.models import ResearchRun

            run = ResearchRun.create("LLM agent memory")
            store.create_run(run)
            paper = provider_paper("arxiv", "2304.03442", arxiv_id="2304.03442")
            service = DiscoveryService(
                QueryPlanner(max_results=2),
                {
                    "arxiv": FixtureProvider("arxiv", (paper,)),
                    "semantic_scholar": FixtureProvider(
                        "semantic_scholar",
                        error=RuntimeError("quota"),
                    ),
                },
            )

            outcome = service.run(
                run,
                LocalArtifactStore(root / "artifacts"),
                store,
            )

            self.assertGreater(len(outcome.candidates), 0)
            self.assertIn("semantic_scholar", outcome.failed_providers)
            self.assertTrue(
                all(
                    item.status == CandidateStatus.PENDING
                    for item in outcome.candidates
                )
            )
            event_types = [event.event_type for event in store.list_events(run.run_id)]
            self.assertIn("provider_failed", event_types)

    def test_cancellation_check_stops_between_provider_requests(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SQLiteWorkflowStore(root / "workflow.db")
            store.initialize()
            from src.literature_review.models import ResearchRun

            run = ResearchRun.create("LLM agent memory")
            store.create_run(run)
            provider = FixtureProvider(
                "arxiv",
                (provider_paper("arxiv", "2304.03442", arxiv_id="2304.03442"),),
            )
            checks = iter((False, True))
            service = DiscoveryService(QueryPlanner(max_results=1), {"arxiv": provider})

            service.run(
                run,
                LocalArtifactStore(root / "artifacts"),
                store,
                cancellation_check=lambda: next(checks),
            )

            self.assertEqual(provider.calls, 1)


if __name__ == "__main__":
    unittest.main()
