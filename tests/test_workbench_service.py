from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    ResearchRun,
    ScreeningRecommendation,
    WorkflowStage,
)
from src.literature_review.storage import SQLiteWorkflowStore
from src.literature_review.workbench import WorkbenchService


def candidate(candidate_id: str, status: CandidateStatus) -> CandidatePaper:
    return CandidatePaper(
        candidate_id=candidate_id,
        title=f"Paper {candidate_id}",
        authors=("Ada Researcher",),
        year=2025,
        venue="Test Conference",
        abstract="A test candidate.",
        doi=f"10.1000/{candidate_id}",
        arxiv_id=None,
        semantic_scholar_id=None,
        source_urls=(f"https://example.test/{candidate_id}",),
        open_access_pdf_url=None,
        provenance=(f"test:{candidate_id}",),
        recommendation=ScreeningRecommendation.INCLUDE,
        relevance_score=0.9,
        status=status,
    )


class WorkbenchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.store = SQLiteWorkflowStore(Path(self.tmp.name) / "workflow.db")
        self.store.initialize()
        self.older_run = replace(
            ResearchRun.create("Older topic"),
            created_at="2025-01-01T00:00:00+00:00",
            updated_at="2025-01-01T00:00:00+00:00",
        )
        self.newer_run = replace(
            ResearchRun.create("Newer topic"),
            created_at="2025-01-02T00:00:00+00:00",
            updated_at="2025-01-02T00:00:00+00:00",
        )
        self.store.create_run(self.older_run)
        self.store.create_run(self.newer_run)
        self.approved = candidate("cand_alpha", CandidateStatus.APPROVED)
        self.pending = candidate("cand_zulu", CandidateStatus.PENDING)
        self.store.upsert_candidate(self.older_run.run_id, self.pending)
        self.store.upsert_candidate(self.older_run.run_id, self.approved)
        self.service = WorkbenchService(self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_list_runs_is_newest_first_with_complete_candidate_counts(self) -> None:
        result = self.service.list_runs()

        self.assertEqual(
            [item["run_id"] for item in result],
            [self.newer_run.run_id, self.older_run.run_id],
        )
        self.assertEqual(
            result[0],
            {
                **self.newer_run.to_dict(),
                "candidate_counts": {
                    "pending": 0,
                    "approved": 0,
                    "rejected": 0,
                    "deferred": 0,
                },
            },
        )
        self.assertEqual(
            result[1]["candidate_counts"],
            {
                "pending": 1,
                "approved": 1,
                "rejected": 0,
                "deferred": 0,
            },
        )

    def test_get_run_detail_returns_json_native_run_activity(self) -> None:
        event = self.store.append_event(
            self.older_run.run_id,
            "screening_completed",
            {"candidate_count": 2},
            WorkflowStage.SCREENING,
        )

        detail = self.service.get_run_detail(self.older_run.run_id)

        self.assertEqual(
            detail,
            {
                "run": self.older_run.to_dict(),
                "candidate_counts": {
                    "pending": 1,
                    "approved": 1,
                    "rejected": 0,
                    "deferred": 0,
                },
                "events": [event.to_dict()],
                "candidates": [
                    self.approved.to_dict(),
                    self.pending.to_dict(),
                ],
            },
        )
        json.dumps(detail)

    def test_list_candidates_preserves_store_order_and_filters_by_status(self) -> None:
        self.assertEqual(
            self.service.list_candidates(self.older_run.run_id),
            [self.approved.to_dict(), self.pending.to_dict()],
        )
        self.assertEqual(
            self.service.list_candidates(
                self.older_run.run_id,
                CandidateStatus.APPROVED,
            ),
            [self.approved.to_dict()],
        )


if __name__ == "__main__":
    unittest.main()
