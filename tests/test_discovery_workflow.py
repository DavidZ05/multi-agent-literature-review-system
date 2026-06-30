from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.literature_review.config import AgentRuntimeConfig
from src.literature_review.discovery import (
    ApprovalService,
    DiscoveryService,
    QueryPlanner,
)
from src.literature_review.models import RunStatus, WorkflowStage
from src.literature_review.providers import (
    ArxivProvider,
    HttpResponse,
    SemanticScholarProvider,
)
from src.literature_review.storage import LocalArtifactStore, SQLiteWorkflowStore
from src.literature_review.workflow import (
    ApprovalGateHandler,
    DiscoveryHandler,
    DraftingHandler,
    PersistentWorkflowEngine,
    PlanningHandler,
    ScreeningHandler,
)


FIXTURES = Path(__file__).parent / "fixtures" / "providers"


class MemoryCache:
    def __init__(self) -> None:
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def put(self, key, value, ttl_seconds):
        self.values[key] = value


class FixtureTransport:
    def get(self, url, headers):
        if "semanticscholar" in url:
            body = (FIXTURES / "semantic_scholar_memory.json").read_bytes()
            return HttpResponse(200, body, {"content-type": "application/json"})
        body = (FIXTURES / "arxiv_memory.xml").read_bytes()
        return HttpResponse(200, body, {"content-type": "application/atom+xml"})


class DiscoveryWorkflowTests(unittest.TestCase):
    def test_fixture_discovery_approval_and_drafting_end_to_end(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SQLiteWorkflowStore(root / "workflow.db")
            artifacts = LocalArtifactStore(root / "artifacts")
            cache = MemoryCache()
            transport = FixtureTransport()

            def clock():
                return 10.0

            def sleeper(_delay):
                return None

            providers = {
                "arxiv": ArxivProvider(transport, cache, clock=clock, sleeper=sleeper),
                "semantic_scholar": SemanticScholarProvider(
                    transport, cache, clock=clock, sleeper=sleeper
                ),
            }
            approval = ApprovalService(store)
            runtime = AgentRuntimeConfig()
            engine = PersistentWorkflowEngine(
                store,
                artifacts,
                {
                    WorkflowStage.PLANNING: PlanningHandler(discovery_enabled=True),
                    WorkflowStage.DISCOVERING: DiscoveryHandler(
                        DiscoveryService(QueryPlanner(max_results=2), providers)
                    ),
                    WorkflowStage.SCREENING: ScreeningHandler(),
                    WorkflowStage.AWAITING_CORPUS_APPROVAL: ApprovalGateHandler(
                        approval
                    ),
                    WorkflowStage.DRAFTING: DraftingHandler(runtime),
                },
                runtime_config={
                    **runtime.public_dict(),
                    "discovery_enabled": True,
                    "discovery_providers": ["arxiv", "semantic_scholar"],
                    "discovery_max_results": 2,
                },
            )
            seed = Path(__file__).resolve().parents[1] / "data" / "papers.json"

            waiting = engine.start("LLM agent memory", seed)

            self.assertEqual(waiting.status, RunStatus.WAITING)
            candidates = store.list_candidates(waiting.run_id)
            generative = [item for item in candidates if item.arxiv_id == "2304.03442"]
            self.assertEqual(len(generative), 1)
            self.assertEqual(len(generative[0].provenance), 2)
            approval.approve(
                waiting.run_id,
                generative[0].candidate_id,
                reason="Cross-provider core evidence",
                category="multi-agent and embodied memory",
                contribution=(
                    "Connects observation, reflection, and retrieval in "
                    "interactive agent memory."
                ),
                tags=("memory", "reflection", "multi-agent"),
            )
            for item in candidates:
                if item.candidate_id != generative[0].candidate_id:
                    approval.reject(
                        waiting.run_id,
                        item.candidate_id,
                        reason="Not selected for this bounded run",
                    )

            completed = engine.resume(waiting.run_id)

            self.assertEqual(completed.status, RunStatus.COMPLETED)
            self.assertTrue(artifacts.exists(completed.run_id, "final/survey.md"))
            survey = artifacts.read_text(completed.run_id, "final/survey.md")
            approved_corpus = artifacts.read_json(
                completed.run_id, "discovery/approved_corpus.json"
            )
            added_key = next(
                item["citation_key"]
                for item in approved_corpus
                if item["title"].startswith("Generative Agents")
                and item["citation_key"] != "park2023generative"
            )
            self.assertIn(f"[{added_key}]", survey)
            reopened = SQLiteWorkflowStore(root / "workflow.db")
            reopened.initialize()
            self.assertEqual(
                reopened.get_run(completed.run_id).status,
                RunStatus.COMPLETED,
            )
            self.assertGreater(
                len(reopened.list_corpus_decisions(completed.run_id)),
                0,
            )


if __name__ == "__main__":
    unittest.main()
