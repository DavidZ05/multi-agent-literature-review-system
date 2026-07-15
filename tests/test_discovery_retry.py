from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.literature_review.models import (
    ProviderPaper,
    ProviderSearchResult,
    ResearchRun,
    RunStatus,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.plugins import ProviderRegistry
from src.literature_review.runtime import retry_discovery
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore


class FixtureProvider:
    provider_id = "fixture"
    artifact_extension = "json"

    def __init__(
        self,
        *,
        fail: bool = False,
        invalidate_artifact_after_search: bool = False,
    ) -> None:
        self.fail = fail
        self.invalidate_artifact_after_search = invalidate_artifact_after_search
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("fixture provider unavailable")
        paper = ProviderPaper(
            provider="fixture",
            provider_id="paper-1",
            title="Memory Verification for Language Agents",
            authors=("Ada Researcher",),
            year=2026,
            venue="FixtureConf",
            abstract="Evaluates evidence-grounded memory for language agents.",
            doi="10.1000/fixture.1",
            arxiv_id=None,
            semantic_scholar_id=None,
            source_url="https://example.test/paper-1",
            open_access_pdf_url=None,
        )
        result = ProviderSearchResult(
            provider="fixture",
            query_id=query.query_id,
            request_url="https://example.test/search",
            papers=(paper,),
            raw_body=b"{}",
            response_headers={},
        )
        if self.invalidate_artifact_after_search:
            self.artifact_extension = "INVALID!"
        return result

    def fetch_details(self, provider_id):
        return None


class DiscoveryRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = SQLiteWorkflowStore(root / "workflow.db")
        self.store.initialize()
        self.artifacts = root / "artifacts"
        self.run = replace(
            ResearchRun.create("Memory agents"),
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            updated_at=utc_now_iso(),
        )
        self.store.create_run(self.run)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def registry(provider: FixtureProvider) -> ProviderRegistry:
        registry = ProviderRegistry()
        registry.register("fixture", lambda context: provider)
        return registry

    def test_retry_adds_attempt_candidates_funnel_and_artifact(self) -> None:
        provider = FixtureProvider()

        result = retry_discovery(
            self.store,
            self.artifacts,
            self.run.run_id,
            providers=("fixture",),
            max_results=4,
            query_texts=("agent memory verification",),
            provider_registry=self.registry(provider),
            environment={},
        )

        self.assertEqual(result.status, RunStatus.WAITING)
        self.assertEqual(result.current_stage, WorkflowStage.AWAITING_CORPUS_APPROVAL)
        attempts = self.store.list_discovery_attempts(self.run.run_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].status, "succeeded")
        self.assertEqual(attempts[0].raw_result_count, 1)
        self.assertEqual(attempts[0].deduplicated_count, 1)
        self.assertEqual(attempts[0].new_candidate_count, 1)
        self.assertEqual(provider.queries[0].text, "agent memory verification")
        self.assertEqual(len(self.store.list_candidates(self.run.run_id)), 1)
        artifact_store = LocalArtifactStore(self.artifacts)
        self.assertTrue(
            artifact_store.exists(
                self.run.run_id,
                f"discovery/attempts/{attempts[0].attempt_id}/summary.json",
            )
        )

    def test_repeated_paper_is_not_counted_as_a_new_candidate(self) -> None:
        provider = FixtureProvider()
        registry = self.registry(provider)
        for _ in range(2):
            retry_discovery(
                self.store,
                self.artifacts,
                self.run.run_id,
                providers=("fixture",),
                max_results=2,
                provider_registry=registry,
                environment={},
            )

        attempts = self.store.list_discovery_attempts(self.run.run_id)
        self.assertEqual([attempt.new_candidate_count for attempt in attempts], [1, 0])
        self.assertEqual(len(self.store.list_candidates(self.run.run_id)), 1)

    def test_failed_retry_preserves_existing_approval_gate(self) -> None:
        provider = FixtureProvider(fail=True)

        result = retry_discovery(
            self.store,
            self.artifacts,
            self.run.run_id,
            providers=("fixture",),
            max_results=1,
            query_texts=("one query",),
            provider_registry=self.registry(provider),
            environment={},
        )

        self.assertEqual(result.status, RunStatus.WAITING)
        self.assertEqual(result.current_stage, WorkflowStage.AWAITING_CORPUS_APPROVAL)
        attempt = self.store.list_discovery_attempts(self.run.run_id)[0]
        self.assertEqual(attempt.status, "failed")
        self.assertEqual(attempt.failed_providers, ("fixture",))

    def test_retry_rejects_non_discovery_gate(self) -> None:
        self.store.update_run(
            replace(
                self.run,
                status=RunStatus.COMPLETED,
                current_stage=WorkflowStage.COMPLETED,
                updated_at=utc_now_iso(),
            )
        )

        with self.assertRaisesRegex(ValueError, "review or retry gate"):
            retry_discovery(
                self.store,
                self.artifacts,
                self.run.run_id,
                providers=("fixture",),
                max_results=1,
                provider_registry=self.registry(FixtureProvider()),
                environment={},
            )

    def test_unexpected_retry_failure_closes_attempt_and_restores_gate(self) -> None:
        provider = FixtureProvider(invalidate_artifact_after_search=True)

        with self.assertRaisesRegex(ValueError, "artifact_extension"):
            retry_discovery(
                self.store,
                self.artifacts,
                self.run.run_id,
                providers=("fixture",),
                max_results=1,
                provider_registry=self.registry(provider),
                environment={},
            )

        attempt = self.store.list_discovery_attempts(self.run.run_id)[0]
        restored = self.store.get_run(self.run.run_id)
        self.assertEqual(attempt.status, "failed")
        self.assertIsNotNone(attempt.completed_at)
        self.assertEqual(restored.status, RunStatus.WAITING)
        self.assertEqual(restored.current_stage, WorkflowStage.AWAITING_CORPUS_APPROVAL)


if __name__ == "__main__":
    unittest.main()
