from dataclasses import replace
import json
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory
import unittest

from src.literature_review import cli
from src.literature_review.discovery import ApprovalService
from src.literature_review.models import (
    CandidatePaper,
    CandidateStatus,
    ResearchRun,
    RunStatus,
    ScreeningRecommendation,
    WorkflowStage,
)
from src.literature_review.storage import (
    LocalArtifactStore,
    RunNotFoundError,
    SQLiteWorkflowStore,
)
from src.literature_review.workbench import PendingCandidatesError, WorkbenchService
from src.literature_review.workflow import PersistentWorkflowEngine


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


class NoCandidateHydrationStore(SQLiteWorkflowStore):
    def list_candidates(
        self,
        *args: object,
        **kwargs: object,
    ) -> list[CandidatePaper]:
        raise AssertionError("list_runs must not hydrate candidates")


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
        service = WorkbenchService(NoCandidateHydrationStore(self.store.path))

        result = service.list_runs()

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

    def test_approve_candidate_delegates_with_workbench_actor_and_safe_command(
        self,
    ) -> None:
        reason = "Strong evidence; don't execute $(touch /tmp/nope)"
        category = "memory mechanism"
        contribution = "Explains 'reflection' and recall."
        tags = ("memory systems", "reviewer's-choice")

        result = self.service.approve_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
            reason,
            category,
            contribution,
            tags,
        )

        stored_candidate = self.store.get_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
        )
        decision, details = self.store.list_corpus_decisions(
            self.older_run.run_id
        )[0]
        self.assertEqual(stored_candidate.status, CandidateStatus.APPROVED)
        self.assertEqual(decision.actor, "workbench")
        self.assertEqual(
            details,
            {
                "category": category,
                "contribution": contribution,
                "tags": list(tags),
            },
        )
        self.assertEqual(result["candidate"], stored_candidate.to_dict())
        self.assertEqual(result["decision"], decision.to_dict())
        self.assertEqual(
            result["equivalent_command"],
            shlex.join(
                [
                    "python3",
                    "-m",
                    "src.memory_review_pipeline",
                    "approve",
                    self.older_run.run_id,
                    self.pending.candidate_id,
                    f"--reason={reason}",
                    f"--category={category}",
                    f"--contribution={contribution}",
                    *(f"--tags={tag}" for tag in tags),
                ]
            ),
        )
        json.dumps(result)

    def test_approve_equivalent_command_replays_dash_and_spaced_values(
        self,
    ) -> None:
        cases = (
            ("-reason", "-category", "-contribution", ("-tag", "-second")),
            (
                "-reason with spaces",
                "-category with spaces",
                "-contribution with spaces",
                ("-tag with spaces", "-second tag"),
            ),
        )
        for reason, category, contribution, tags in cases:
            with self.subTest(reason=reason):
                result = self.service.approve_candidate(
                    self.older_run.run_id,
                    self.pending.candidate_id,
                    reason,
                    category,
                    contribution,
                    tags,
                )
                tokens = shlex.split(result["equivalent_command"])

                self.assertEqual(
                    tokens[:3],
                    ["python3", "-m", "src.memory_review_pipeline"],
                )
                try:
                    parsed = cli._parser().parse_args(tokens[3:])
                except SystemExit as exc:
                    self.fail(f"equivalent command did not parse: {exc}")
                self.assertEqual(parsed.command, "approve")
                self.assertEqual(parsed.run_id, self.older_run.run_id)
                self.assertEqual(parsed.candidate_id, self.pending.candidate_id)
                self.assertEqual(parsed.reason, reason)
                self.assertEqual(parsed.category, category)
                self.assertEqual(parsed.contribution, contribution)
                self.assertEqual(parsed.tags, list(tags))

    def test_approve_parser_preserves_legacy_multi_value_tags(self) -> None:
        parsed = cli._parser().parse_args(
            [
                "approve",
                self.older_run.run_id,
                self.pending.candidate_id,
                "--reason",
                "Useful",
                "--category",
                "Memory",
                "--contribution",
                "Adds evidence",
                "--tags",
                "memory",
                "reflection",
            ]
        )

        self.assertEqual(parsed.tags, ["memory", "reflection"])

    def test_reject_candidate_delegates_with_workbench_actor(self) -> None:
        reason = "Outside scope; quoted as 'irrelevant'"

        result = self.service.reject_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
            reason,
        )

        stored_candidate = self.store.get_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
        )
        decision, details = self.store.list_corpus_decisions(
            self.older_run.run_id
        )[0]
        self.assertEqual(stored_candidate.status, CandidateStatus.REJECTED)
        self.assertEqual(decision.actor, "workbench")
        self.assertEqual(details, {})
        self.assertEqual(result["candidate"], stored_candidate.to_dict())
        self.assertEqual(result["decision"], decision.to_dict())
        self.assertEqual(
            result["equivalent_command"],
            shlex.join(
                [
                    "python3",
                    "-m",
                    "src.memory_review_pipeline",
                    "reject",
                    self.older_run.run_id,
                    self.pending.candidate_id,
                    f"--reason={reason}",
                ]
            ),
        )
        json.dumps(result)

    def test_defer_candidate_delegates_with_workbench_actor(self) -> None:
        reason = "Read full text before deciding"

        result = self.service.defer_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
            reason,
        )

        stored_candidate = self.store.get_candidate(
            self.older_run.run_id,
            self.pending.candidate_id,
        )
        decision, details = self.store.list_corpus_decisions(
            self.older_run.run_id
        )[0]
        self.assertEqual(stored_candidate.status, CandidateStatus.DEFERRED)
        self.assertEqual(decision.actor, "workbench")
        self.assertEqual(details, {})
        self.assertEqual(result["candidate"], stored_candidate.to_dict())
        self.assertEqual(result["decision"], decision.to_dict())
        self.assertEqual(
            result["equivalent_command"],
            shlex.join(
                [
                    "python3",
                    "-m",
                    "src.memory_review_pipeline",
                    "defer",
                    self.older_run.run_id,
                    self.pending.candidate_id,
                    f"--reason={reason}",
                ]
            ),
        )
        json.dumps(result)

    def test_defer_candidate_rejects_blank_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "reason is required"):
            self.service.defer_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
                " ",
            )

        self.assertEqual(
            self.store.get_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
            ).status,
            CandidateStatus.PENDING,
        )
        self.assertEqual(
            self.store.list_corpus_decisions(self.older_run.run_id),
            [],
        )

    def test_decision_validation_errors_remain_meaningful(self) -> None:
        with self.assertRaisesRegex(ValueError, "category is required"):
            self.service.approve_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
                "Useful",
                " ",
                "Contribution",
                ("memory",),
            )
        with self.assertRaisesRegex(ValueError, "reason is required"):
            self.service.reject_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
                " ",
            )
        with self.assertRaisesRegex(ValueError, "nonblank tag"):
            self.service.approve_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
                "Useful",
                "Memory",
                "Contribution",
                ("memory", " "),
            )

        self.assertEqual(
            self.store.get_candidate(
                self.older_run.run_id,
                self.pending.candidate_id,
            ).status,
            CandidateStatus.PENDING,
        )
        self.assertEqual(
            self.store.list_corpus_decisions(self.older_run.run_id),
            [],
        )

    def test_close_discovery_refuses_when_candidates_remain_pending(self) -> None:
        with self.assertRaises(PendingCandidatesError) as raised:
            self.service.close_discovery(self.older_run.run_id)

        self.assertEqual(raised.exception.pending_count, 1)
        self.assertEqual(raised.exception.run_id, self.older_run.run_id)
        self.assertEqual(
            self.store.get_run(self.older_run.run_id),
            self.older_run,
        )

    def test_close_discovery_returns_ready_without_mutating_run(self) -> None:
        ApprovalService(self.store).defer(
            self.older_run.run_id,
            self.pending.candidate_id,
            reason="Review later",
        )

        result = self.service.close_discovery(self.older_run.run_id)

        self.assertEqual(
            result,
            {
                "run_id": self.older_run.run_id,
                "status": "ready_to_resume",
                "equivalent_command": shlex.join(
                    [
                        "python3",
                        "-m",
                        "src.memory_review_pipeline",
                        "close-discovery",
                        self.older_run.run_id,
                    ]
                ),
            },
        )
        self.assertEqual(
            self.store.get_run(self.older_run.run_id),
            self.older_run,
        )
        json.dumps(result)

    def test_cancel_run_delegates_to_engine_and_serializes_result(self) -> None:
        engine = PersistentWorkflowEngine(
            self.store,
            LocalArtifactStore(Path(self.tmp.name) / "artifacts"),
            {},
        )
        calls: list[str] = []

        def cancel(run_id: str) -> ResearchRun:
            calls.append(run_id)
            return engine.cancel(run_id)

        service = WorkbenchService(self.store, cancel=cancel)

        result = service.cancel_run(self.newer_run.run_id)

        cancelled = self.store.get_run(self.newer_run.run_id)
        self.assertEqual(calls, [self.newer_run.run_id])
        self.assertEqual(cancelled.status, RunStatus.CANCELLED)
        self.assertEqual(result["run"], cancelled.to_dict())
        self.assertEqual(
            result["equivalent_command"],
            shlex.join(
                [
                    "python3",
                    "-m",
                    "src.memory_review_pipeline",
                    "cancel",
                    self.newer_run.run_id,
                ]
            ),
        )
        self.assertEqual(
            [
                event.event_type
                for event in self.store.list_events(self.newer_run.run_id)
            ],
            ["run_cancelled"],
        )
        json.dumps(result)

    def test_cancel_run_propagates_unknown_run_from_engine(self) -> None:
        engine = PersistentWorkflowEngine(
            self.store,
            LocalArtifactStore(Path(self.tmp.name) / "artifacts"),
            {},
        )
        calls: list[str] = []

        def cancel(run_id: str) -> ResearchRun:
            calls.append(run_id)
            return engine.cancel(run_id)

        service = WorkbenchService(self.store, cancel=cancel)
        missing_run_id = ResearchRun.create("Missing run").run_id

        with self.assertRaisesRegex(RunNotFoundError, missing_run_id):
            service.cancel_run(missing_run_id)

        self.assertEqual(calls, [missing_run_id])


if __name__ == "__main__":
    unittest.main()
