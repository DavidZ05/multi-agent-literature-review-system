from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.literature_review.discovery.approval import ApprovalService
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    CorpusDecision,
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    SearchQuery,
    WorkflowStage,
    utc_now_iso,
)
from src.literature_review.storage import (
    CandidateNotFoundError,
    SQLiteResponseCache,
    SQLiteWorkflowStore,
)


def candidate(
    candidate_id: str = "cand_one",
    provenance=("arxiv:2304.03442",),
) -> CandidatePaper:
    return CandidatePaper(
        candidate_id=candidate_id,
        title="Novel Reflective Memory Agents",
        authors=("Joon Sung Park",),
        year=2023,
        venue="UIST",
        abstract="Agent memory.",
        doi="10.1145/3586183.3606763",
        arxiv_id="2304.03442",
        semantic_scholar_id=None,
        source_urls=("https://arxiv.org/abs/2304.03442",),
        open_access_pdf_url=None,
        provenance=provenance,
        recommendation=ScreeningRecommendation.INCLUDE,
        relevance_score=0.9,
        status=CandidateStatus.PENDING,
    )


class CandidateRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workflow.db"
        self.store = SQLiteWorkflowStore(self.path)
        self.store.initialize()
        self.run = ResearchRun.create("Memory agents")
        self.store.create_run(self.run)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_queries_and_candidates_survive_reopen(self) -> None:
        query = SearchQuery("q1", "memory", "arxiv", 10, None, None)
        self.store.save_search_query(self.run.run_id, query)
        self.store.upsert_candidate(self.run.run_id, candidate())
        reopened = SQLiteWorkflowStore(self.path)
        reopened.initialize()
        self.assertEqual(reopened.list_search_queries(self.run.run_id), [query])
        self.assertEqual(reopened.list_candidates(self.run.run_id), [candidate()])

    def test_candidate_upsert_preserves_cross_provider_provenance(self) -> None:
        self.store.upsert_candidate(self.run.run_id, candidate())
        self.store.upsert_candidate(
            self.run.run_id,
            candidate(provenance=("semantic_scholar:s2-paper",)),
        )
        stored = self.store.get_candidate(self.run.run_id, "cand_one")
        self.assertEqual(
            stored.provenance,
            ("arxiv:2304.03442", "semantic_scholar:s2-paper"),
        )

    def test_decisions_are_append_only_and_update_candidate_status(self) -> None:
        self.run = replace(
            self.run,
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            updated_at=utc_now_iso(),
        )
        self.store.update_run(self.run)
        self.store.upsert_candidate(self.run.run_id, candidate())
        decision = CorpusDecision.create(
            self.run.run_id,
            "cand_one",
            CandidateStatus.APPROVED,
            "Core evidence",
            "human",
        )
        details = {
            "category": "memory mechanism",
            "contribution": "Introduces reflective memory.",
            "tags": ["memory", "reflection"],
        }
        self.store.append_corpus_decision(decision, details=details)
        self.assertEqual(
            self.store.get_candidate(self.run.run_id, "cand_one").status,
            CandidateStatus.APPROVED,
        )
        self.assertEqual(
            self.store.list_corpus_decisions(self.run.run_id),
            [(decision, details)],
        )

    def test_unknown_candidate_decision_is_rejected(self) -> None:
        self.run = replace(
            self.run,
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            updated_at=utc_now_iso(),
        )
        self.store.update_run(self.run)
        decision = CorpusDecision.create(
            self.run.run_id,
            "cand_missing",
            CandidateStatus.REJECTED,
            "Not relevant",
            "human",
        )
        with self.assertRaises(CandidateNotFoundError):
            self.store.append_corpus_decision(decision)

    def test_sqlite_response_cache_expires_values(self) -> None:
        now = [100.0]
        cache = SQLiteResponseCache(self.path, clock=lambda: now[0])
        cache.put("arxiv:key", b"body", ttl_seconds=10)
        self.assertEqual(cache.get("arxiv:key"), b"body")
        now[0] = 111.0
        self.assertIsNone(cache.get("arxiv:key"))

    def test_sqlite_response_cache_prunes_unrelated_expired_values(self) -> None:
        now = [100.0]
        cache = SQLiteResponseCache(self.path, clock=lambda: now[0])
        cache.put("old:key", b"old", ttl_seconds=10)
        now[0] = 111.0
        cache.put("new:key", b"new", ttl_seconds=10)

        self.assertEqual(cache.prune_expired(), 0)
        self.assertIsNone(cache.get("old:key"))
        self.assertEqual(cache.get("new:key"), b"new")


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = SQLiteWorkflowStore(self.root / "workflow.db")
        self.store.initialize()
        self.run = ResearchRun.create("Memory agents")
        self.run = replace(
            self.run,
            status=RunStatus.WAITING,
            current_stage=WorkflowStage.AWAITING_CORPUS_APPROVAL,
            updated_at=utc_now_iso(),
        )
        self.store.create_run(self.run)
        self.store.upsert_candidate(self.run.run_id, candidate())
        self.service = ApprovalService(self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_approval_requires_writer_visible_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "category"):
            self.service.approve(
                self.run.run_id,
                "cand_one",
                reason="Useful",
                category="",
                contribution="Contribution",
                tags=("memory",),
            )

    def test_decision_is_rejected_outside_approval_gate(self) -> None:
        active = replace(
            self.run,
            status=RunStatus.ACTIVE,
            current_stage=WorkflowStage.DISCOVERING,
            updated_at=utc_now_iso(),
        )
        self.store.update_run(active)

        with self.assertRaisesRegex(
            RuntimeError,
            "waiting for corpus approval",
        ):
            self.service.reject(
                self.run.run_id,
                "cand_one",
                reason="Outside scope",
            )

    def test_only_approved_candidate_enters_validated_corpus(self) -> None:
        self.service.approve(
            self.run.run_id,
            "cand_one",
            reason="Core evidence",
            category="memory mechanism",
            contribution="Introduces reflective agent memory.",
            tags=("memory", "reflection"),
        )
        seed_path = Path(__file__).resolve().parents[1] / "data" / "papers.json"

        records = self.service.build_approved_corpus(self.run.run_id, seed_path)

        added = next(
            record
            for record in records
            if record["title"] == "Novel Reflective Memory Agents"
        )
        self.assertTrue(added["citation_key"].startswith("park2023"))
        self.assertEqual(
            added["evidence"],
            "metadata verified; full-text verification pending",
        )

    def test_rejected_candidate_never_enters_corpus(self) -> None:
        self.service.reject(
            self.run.run_id,
            "cand_one",
            reason="Outside scope",
        )
        seed_path = Path(__file__).resolve().parents[1] / "data" / "papers.json"
        records = self.service.build_approved_corpus(self.run.run_id, seed_path)
        self.assertNotIn(
            "Novel Reflective Memory Agents",
            [item["title"] for item in records],
        )


if __name__ == "__main__":
    unittest.main()
